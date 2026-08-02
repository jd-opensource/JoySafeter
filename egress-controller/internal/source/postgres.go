package source

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
)

const generationNotificationChannel = "joysafeter_egress_generation"

type DesiredGeneration struct {
	GroupKey            string
	Generation          uint64
	NodeSelector        group.Metadata
	PolicySchemaVersion int
	DesiredPolicies     json.RawMessage
	ContentSHA256       string
	ApplyState          string
}

type GenerationCompiler interface {
	Compile(context.Context, DesiredGeneration) (snapshot.Compiled, error)
}

type CompilerFunc func(context.Context, DesiredGeneration) (snapshot.Compiled, error)

func (f CompilerFunc) Compile(ctx context.Context, desired DesiredGeneration) (snapshot.Compiled, error) {
	return f(ctx, desired)
}

type PostgresReconciler struct {
	databaseURL string
	interval    time.Duration
	pool        *pgxpool.Pool
	compiler    GenerationCompiler
	publisher   Publisher
	restorer    Restorer
	logger      *slog.Logger
	metrics     *telemetry.Metrics

	mu      sync.Mutex
	applied map[string]generationIdentity
}

type generationIdentity struct {
	generation    uint64
	contentSHA256 string
}

func NewPostgresReconciler(
	ctx context.Context,
	databaseURL string,
	interval time.Duration,
	compiler GenerationCompiler,
	publisher Publisher,
	logger *slog.Logger,
	metrics *telemetry.Metrics,
) (*PostgresReconciler, error) {
	if strings.TrimSpace(databaseURL) == "" {
		return nil, errors.New("PostgreSQL desired-state source requires a database URL")
	}
	if interval < time.Second {
		return nil, errors.New("PostgreSQL reconciliation interval must be at least 1s")
	}
	if compiler == nil || publisher == nil || logger == nil || metrics == nil {
		return nil, errors.New("PostgreSQL desired-state source dependencies are required")
	}
	restorer, ok := publisher.(Restorer)
	if !ok {
		return nil, errors.New("PostgreSQL desired-state publisher must support last-known-good restoration")
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("configure PostgreSQL desired-state source: %w", err)
	}
	pingContext, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingContext); err != nil {
		pool.Close()
		return nil, fmt.Errorf("connect PostgreSQL desired-state source: %w", err)
	}
	return &PostgresReconciler{
		databaseURL: databaseURL,
		interval:    interval,
		pool:        pool,
		compiler:    compiler,
		publisher:   publisher,
		restorer:    restorer,
		logger:      logger,
		metrics:     metrics,
		applied:     make(map[string]generationIdentity),
	}, nil
}

func (r *PostgresReconciler) Initial(ctx context.Context) error {
	if err := r.restoreApplied(ctx); err != nil {
		r.observeReconcile("restore", false, err)
		return err
	}
	changed, err := r.reconcileAll(ctx)
	r.observeReconcile("initial", changed, err)
	return err
}

func (r *PostgresReconciler) restoreApplied(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	rows, err := r.pool.Query(ctx, `
		SELECT DISTINCT ON (g.group_key)
			g.group_key, g.generation, g.node_selector, g.policy_schema_version,
			g.desired_policies, g.content_sha256, a.state
		FROM joysafeter_egress_group_generations AS g
		JOIN joysafeter_egress_apply_status AS a
		  ON a.group_key = g.group_key AND a.generation = g.generation
		WHERE a.state = 'applied'
		ORDER BY g.group_key, g.generation DESC
	`)
	if err != nil {
		return fmt.Errorf("query applied egress generations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		desired, err := scanDesiredGeneration(rows)
		if err != nil {
			return err
		}
		compiled, err := r.compiler.Compile(ctx, desired)
		if err != nil {
			return fmt.Errorf("compile applied generation %s/%d: %w", desired.GroupKey, desired.Generation, err)
		}
		if err := r.restorer.Restore(ctx, compiled); err != nil {
			return fmt.Errorf("restore applied generation %s/%d: %w", desired.GroupKey, desired.Generation, err)
		}
		r.applied[desired.GroupKey] = generationIdentity{
			generation: desired.Generation, contentSHA256: desired.ContentSHA256,
		}
		r.logger.Info("restored durable last-known-good snapshot", "group", desired.GroupKey, "generation", desired.Generation)
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate applied egress generations: %w", err)
	}
	return nil
}

func (r *PostgresReconciler) Run(ctx context.Context) {
	listenerDone := make(chan struct{})
	go func() {
		defer close(listenerDone)
		r.listen(ctx)
	}()

	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			<-listenerDone
			return
		case <-ticker.C:
			changed, err := r.reconcileAll(ctx)
			r.observeReconcile("full", changed, err)
			if err != nil {
				r.logger.Error("PostgreSQL full reconciliation failed; retaining active snapshots", "error", err)
			}
		}
	}
}

func (r *PostgresReconciler) Close() {
	r.pool.Close()
}

func (r *PostgresReconciler) listen(ctx context.Context) {
	backoff := 100 * time.Millisecond
	for ctx.Err() == nil {
		conn, err := pgx.Connect(ctx, r.databaseURL)
		if err != nil {
			r.metrics.SourceEvents.WithLabelValues("listener", "connect_error").Inc()
			r.logger.Error("connect PostgreSQL generation listener", "error", err, "backoff", backoff)
			if !waitForRetry(ctx, backoff) {
				return
			}
			backoff = nextBackoff(backoff)
			continue
		}
		if _, err := conn.Exec(ctx, "LISTEN "+generationNotificationChannel); err != nil {
			_ = conn.Close(context.Background())
			r.metrics.SourceEvents.WithLabelValues("listener", "listen_error").Inc()
			r.logger.Error("subscribe PostgreSQL generation listener", "error", err, "backoff", backoff)
			if !waitForRetry(ctx, backoff) {
				return
			}
			backoff = nextBackoff(backoff)
			continue
		}

		r.metrics.SourceEvents.WithLabelValues("listener", "connected").Inc()
		backoff = 100 * time.Millisecond
		changed, err := r.reconcileAll(ctx)
		r.observeReconcile("listener_catchup", changed, err)
		if err != nil {
			r.logger.Error("PostgreSQL listener catch-up reconciliation failed", "error", err)
		}

		for ctx.Err() == nil {
			notification, err := conn.WaitForNotification(ctx)
			if err != nil {
				if ctx.Err() == nil {
					r.metrics.SourceEvents.WithLabelValues("listener", "disconnected").Inc()
					r.logger.Error("PostgreSQL generation listener disconnected", "error", err)
				}
				break
			}
			groupKey, _, err := parseGenerationNotification(notification.Payload)
			if err != nil {
				r.metrics.SourceEvents.WithLabelValues("notification", "invalid").Inc()
				r.logger.Error("ignore invalid PostgreSQL generation notification", "error", err)
				continue
			}
			changed, err := r.reconcileGroup(ctx, groupKey)
			r.observeReconcile("notification", changed, err)
			if err != nil {
				r.logger.Error("PostgreSQL notification reconciliation failed; periodic reconciliation will retry", "group", groupKey, "error", err)
			}
		}
		_ = conn.Close(context.Background())
	}
}

func (r *PostgresReconciler) reconcileAll(ctx context.Context) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	rows, err := r.pool.Query(ctx, `
		SELECT DISTINCT ON (g.group_key)
			g.group_key, g.generation, g.node_selector, g.policy_schema_version,
			g.desired_policies, g.content_sha256, COALESCE(a.state, '')
		FROM joysafeter_egress_group_generations AS g
		LEFT JOIN joysafeter_egress_apply_status AS a
		  ON a.group_key = g.group_key AND a.generation = g.generation
		WHERE g.state = 'desired'
		ORDER BY g.group_key, g.generation DESC
	`)
	if err != nil {
		return false, fmt.Errorf("query desired egress generations: %w", err)
	}
	defer rows.Close()

	changed := false
	for rows.Next() {
		desired, err := scanDesiredGeneration(rows)
		if err != nil {
			r.metrics.Reconcile.WithLabelValues("row_error").Inc()
			r.logger.Error("invalid desired egress generation row; skipping fail-closed", "error", err)
			continue
		}
		published, err := r.publishLocked(ctx, desired)
		if err != nil {
			r.metrics.Reconcile.WithLabelValues("group_error").Inc()
			r.logger.Error(
				"desired egress group reconciliation failed; retaining its active snapshot",
				"group", desired.GroupKey, "generation", desired.Generation, "error", err,
			)
			continue
		}
		changed = changed || published
	}
	if err := rows.Err(); err != nil {
		return changed, fmt.Errorf("iterate desired egress generations: %w", err)
	}
	return changed, nil
}

func (r *PostgresReconciler) reconcileGroup(ctx context.Context, groupKey string) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	row := r.pool.QueryRow(ctx, `
		SELECT g.group_key, g.generation, g.node_selector, g.policy_schema_version,
		       g.desired_policies, g.content_sha256, COALESCE(a.state, '')
		FROM joysafeter_egress_group_generations AS g
		LEFT JOIN joysafeter_egress_apply_status AS a
		  ON a.group_key = g.group_key AND a.generation = g.generation
		WHERE g.group_key = $1 AND g.state = 'desired'
		ORDER BY g.generation DESC
		LIMIT 1
	`, groupKey)
	desired, err := scanDesiredGeneration(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return r.publishLocked(ctx, desired)
}

func (r *PostgresReconciler) publishLocked(ctx context.Context, desired DesiredGeneration) (bool, error) {
	identity := generationIdentity{generation: desired.Generation, contentSHA256: desired.ContentSHA256}
	if r.applied[desired.GroupKey] == identity {
		return false, nil
	}
	if desired.ApplyState == "failed" {
		r.applied[desired.GroupKey] = identity
		r.metrics.Reconcile.WithLabelValues("rejected_durable").Inc()
		r.logger.Error("skip durably rejected egress generation", "group", desired.GroupKey, "generation", desired.Generation)
		return false, nil
	}
	compiled, err := r.compiler.Compile(ctx, desired)
	if err != nil {
		return false, fmt.Errorf("compile desired generation %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	if compiled.GroupKey != desired.GroupKey || compiled.Generation != desired.Generation {
		return false, fmt.Errorf(
			"compiler identity mismatch: desired=%s/%d compiled=%s/%d",
			desired.GroupKey, desired.Generation, compiled.GroupKey, compiled.Generation,
		)
	}
	if compiled.Snapshot == nil || len(compiled.RequiredTypes) == 0 || strings.TrimSpace(compiled.Version) == "" {
		return false, errors.New("compiler returned an incomplete xDS snapshot")
	}
	if err := r.publisher.Publish(ctx, compiled); err != nil {
		return false, fmt.Errorf("publish desired generation %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	r.applied[desired.GroupKey] = identity
	r.logger.Info("PostgreSQL desired generation reconciled", "group", desired.GroupKey, "generation", desired.Generation, "content_sha256", desired.ContentSHA256[:12])
	return true, nil
}

type rowScanner interface {
	Scan(...any) error
}

func scanDesiredGeneration(row rowScanner) (DesiredGeneration, error) {
	var desired DesiredGeneration
	var generation int64
	var selectorJSON []byte
	if err := row.Scan(
		&desired.GroupKey,
		&generation,
		&selectorJSON,
		&desired.PolicySchemaVersion,
		&desired.DesiredPolicies,
		&desired.ContentSHA256,
		&desired.ApplyState,
	); err != nil {
		return DesiredGeneration{}, err
	}
	if generation <= 0 {
		return DesiredGeneration{}, fmt.Errorf("invalid desired generation %d", generation)
	}
	desired.Generation = uint64(generation)
	decoder := json.NewDecoder(bytes.NewReader(selectorJSON))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&desired.NodeSelector); err != nil {
		return DesiredGeneration{}, fmt.Errorf("decode node selector for %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	if err := ensureJSONEOF(decoder); err != nil {
		return DesiredGeneration{}, fmt.Errorf("decode node selector for %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	computedKey, err := desired.NodeSelector.Key()
	if err != nil {
		return DesiredGeneration{}, fmt.Errorf("validate node selector for %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	if computedKey != desired.GroupKey {
		return DesiredGeneration{}, fmt.Errorf("node selector group key mismatch: stored=%s computed=%s", desired.GroupKey, computedKey)
	}
	if desired.PolicySchemaVersion <= 0 {
		return DesiredGeneration{}, fmt.Errorf("invalid policy schema version %d", desired.PolicySchemaVersion)
	}
	var policies []json.RawMessage
	policyDecoder := json.NewDecoder(bytes.NewReader(desired.DesiredPolicies))
	if err := policyDecoder.Decode(&policies); err != nil {
		return DesiredGeneration{}, fmt.Errorf("decode desired policies for %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	if err := ensureJSONEOF(policyDecoder); err != nil {
		return DesiredGeneration{}, fmt.Errorf("decode desired policies for %s/%d: %w", desired.GroupKey, desired.Generation, err)
	}
	if len(desired.ContentSHA256) != 64 || strings.Trim(desired.ContentSHA256, "0123456789abcdef") != "" {
		return DesiredGeneration{}, errors.New("content_sha256 must be lowercase SHA-256 hex")
	}
	return desired, nil
}

func parseGenerationNotification(payload string) (string, uint64, error) {
	separator := strings.LastIndexByte(payload, ':')
	if separator <= 0 || separator == len(payload)-1 {
		return "", 0, fmt.Errorf("invalid generation notification payload %q", payload)
	}
	groupKey := payload[:separator]
	generation, err := strconv.ParseUint(payload[separator+1:], 10, 64)
	if err != nil || generation == 0 {
		return "", 0, fmt.Errorf("invalid generation notification payload %q", payload)
	}
	if !strings.HasPrefix(groupKey, group.SchemaVersion+":") {
		return "", 0, fmt.Errorf("invalid generation notification group %q", groupKey)
	}
	return groupKey, generation, nil
}

func (r *PostgresReconciler) observeReconcile(trigger string, changed bool, err error) {
	result := "unchanged"
	if err != nil {
		result = "error"
	} else if changed {
		result = "applied"
	}
	r.metrics.Reconcile.WithLabelValues(trigger + "_" + result).Inc()
}

func ensureJSONEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); errors.Is(err, io.EOF) {
		return nil
	} else if err != nil {
		return fmt.Errorf("decode trailing JSON data: %w", err)
	}
	return errors.New("multiple JSON documents")
}

func waitForRetry(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

func nextBackoff(current time.Duration) time.Duration {
	if current >= 5*time.Second {
		return 5 * time.Second
	}
	next := current * 2
	if next > 5*time.Second {
		return 5 * time.Second
	}
	return next
}
