package status

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
)

type PostgresRecorder struct {
	pool              *pgxpool.Pool
	instanceID        string
	leaseTTL          time.Duration
	heartbeatInterval time.Duration
	recomputeInterval time.Duration
	events            chan event
	logger            *slog.Logger
	metrics           *telemetry.Metrics
	activeMu          sync.Mutex
	active            map[string]group.Identity
	closed            atomic.Bool
	done              chan struct{}
	ctx               context.Context
	cancel            context.CancelFunc
}

type event struct {
	kind             string
	identity         group.Identity
	groupKey         string
	generation       uint64
	version          string
	requiredTypes    []string
	appliedOnPublish bool
	typeURL          string
	nonce            string
	reason           string
}

func NewPostgresRecorder(
	ctx context.Context,
	databaseURL, instanceID string,
	queueSize int,
	leaseTTL, heartbeatInterval, recomputeInterval time.Duration,
	logger *slog.Logger,
	metrics *telemetry.Metrics,
) (*PostgresRecorder, error) {
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse controller database URL: %w", err)
	}
	config.MaxConns = 4
	config.MinConns = 1
	config.MaxConnLifetime = 30 * time.Minute
	config.MaxConnIdleTime = 5 * time.Minute
	config.ConnConfig.RuntimeParams["application_name"] = "joysafeter-egress-controller"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("create controller state pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping controller state database: %w", err)
	}
	recorderContext, cancel := context.WithCancel(ctx)
	recorder := &PostgresRecorder{
		pool: pool, instanceID: instanceID, leaseTTL: leaseTTL,
		heartbeatInterval: heartbeatInterval, recomputeInterval: recomputeInterval, events: make(chan event, queueSize),
		logger: logger, metrics: metrics, active: make(map[string]group.Identity), done: make(chan struct{}),
		ctx: recorderContext, cancel: cancel,
	}
	go recorder.run()
	return recorder, nil
}

func (r *PostgresRecorder) Published(groupKey string, generation uint64, version string, requiredTypes []string, appliedOnPublish bool) {
	r.enqueue(event{kind: "published", groupKey: groupKey, generation: generation, version: version, requiredTypes: append([]string(nil), requiredTypes...), appliedOnPublish: appliedOnPublish})
}

func (r *PostgresRecorder) Connected(identity group.Identity) {
	r.activeMu.Lock()
	r.active[connectionKey(identity)] = identity
	r.activeMu.Unlock()
	r.enqueue(event{kind: "connected", identity: identity})
}

func (r *PostgresRecorder) Disconnected(identity group.Identity) {
	r.activeMu.Lock()
	delete(r.active, connectionKey(identity))
	r.activeMu.Unlock()
	r.enqueue(event{kind: "disconnected", identity: identity})
}

func (r *PostgresRecorder) ACK(identity group.Identity, generation uint64, version, typeURL, nonce string) {
	r.enqueue(event{kind: "ack", identity: identity, generation: generation, version: version, typeURL: typeURL, nonce: nonce})
}

func (r *PostgresRecorder) NACK(identity group.Identity, generation uint64, version, typeURL, nonce, reason string) {
	r.enqueue(event{kind: "nack", identity: identity, generation: generation, version: version, typeURL: typeURL, nonce: nonce, reason: reason})
}

func (r *PostgresRecorder) Close(ctx context.Context) error {
	if r.closed.CompareAndSwap(false, true) {
		close(r.events)
	}
	select {
	case <-r.done:
		r.pool.Close()
		return nil
	case <-ctx.Done():
		r.cancel()
		r.pool.Close()
		return ctx.Err()
	}
}

func (r *PostgresRecorder) enqueue(value event) {
	if r.closed.Load() {
		return
	}
	select {
	case r.events <- value:
		r.metrics.StatusEvents.WithLabelValues(value.kind, "queued").Inc()
		r.metrics.StatusQueueDepth.Set(float64(len(r.events)))
	default:
		r.metrics.StatusEvents.WithLabelValues(value.kind, "dropped").Inc()
		r.logger.Error("durable status queue full; generation remains fail-closed", "kind", value.kind)
	}
}

func (r *PostgresRecorder) run() {
	defer close(r.done)
	defer r.cancel()
	ticker := time.NewTicker(r.heartbeatInterval)
	defer ticker.Stop()
	recomputeTicker := time.NewTicker(r.recomputeInterval)
	defer recomputeTicker.Stop()
	for {
		select {
		case value, ok := <-r.events:
			if !ok {
				r.drain()
				return
			}
			r.persist(value)
			r.metrics.StatusQueueDepth.Set(float64(len(r.events)))
		case <-ticker.C:
			r.heartbeat()
		case <-recomputeTicker.C:
			if err := r.recomputeAllNonTerminal(r.ctx); err != nil {
				r.logger.Error("periodic apply-status recompute sweep failed", "error", err)
			}
		case <-r.ctx.Done():
			return
		}
	}
}

func (r *PostgresRecorder) drain() {
	for value := range r.events {
		r.persist(value)
	}
}

func (r *PostgresRecorder) persist(value event) {
	backoff := 100 * time.Millisecond
	for {
		err := r.writeOnce(value)
		if err == nil {
			r.metrics.StatusEvents.WithLabelValues(value.kind, "persisted").Inc()
			return
		}
		r.metrics.StatusEvents.WithLabelValues(value.kind, "retry").Inc()
		r.logger.Error("persist durable egress status; retrying", "kind", value.kind, "error", err, "backoff", backoff)
		timer := time.NewTimer(backoff)
		select {
		case <-timer.C:
		case <-r.ctx.Done():
			timer.Stop()
			return
		}
		if backoff < 5*time.Second {
			backoff *= 2
			if backoff > 5*time.Second {
				backoff = 5 * time.Second
			}
		}
	}
}

func (r *PostgresRecorder) writeOnce(value event) error {
	ctx, cancel := context.WithTimeout(r.ctx, 5*time.Second)
	defer cancel()
	var err error
	switch value.kind {
	case "published":
		err = r.writePublished(ctx, value)
	case "connected":
		err = r.writeConnected(ctx, value.identity)
	case "disconnected":
		err = r.writeDisconnected(ctx, value.identity)
	case "ack", "nack":
		err = r.writeACK(ctx, value)
	default:
		err = fmt.Errorf("unsupported status event %q", value.kind)
	}
	return err
}

func (r *PostgresRecorder) writePublished(ctx context.Context, value event) error {
	requiredTypes, err := json.Marshal(value.requiredTypes)
	if err != nil {
		return err
	}
	// appliedOnPublish: the generation's content is identical to the currently
	// serving one, so no resource type changed and Envoy sends no delta/ACK. It
	// is already applied; record it 'applied' on insert with the full (non-empty)
	// type list so the schema's non-empty required_type_urls check holds and the
	// decision plane's apply wait resolves without an ACK that will never arrive.
	if value.appliedOnPublish {
		_, err = r.pool.Exec(ctx, `
			INSERT INTO joysafeter_egress_apply_status (
				id, group_key, generation, xds_version, required_type_urls, state,
				connected_nodes, required_acks, acked_acks, first_published_at, applied_at
			) VALUES ($1, $2, $3, $4, $5::jsonb, 'applied', 0, 0, 0, now(), now())
			ON CONFLICT (group_key, generation) DO UPDATE SET
				xds_version = EXCLUDED.xds_version,
				required_type_urls = EXCLUDED.required_type_urls,
				state = 'applied',
				first_published_at = COALESCE(
					joysafeter_egress_apply_status.first_published_at, EXCLUDED.first_published_at
				),
				applied_at = COALESCE(joysafeter_egress_apply_status.applied_at, EXCLUDED.applied_at),
				updated_at = now()
			WHERE joysafeter_egress_apply_status.state IN ('pending', 'published')
		`, uuid.New(), value.groupKey, value.generation, value.version, requiredTypes)
		return err
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO joysafeter_egress_apply_status (
			id, group_key, generation, xds_version, required_type_urls, state,
			connected_nodes, required_acks, acked_acks, first_published_at
		) VALUES ($1, $2, $3, $4, $5::jsonb, 'published', 0, 0, 0, now())
		ON CONFLICT (group_key, generation) DO UPDATE SET
			xds_version = EXCLUDED.xds_version,
			required_type_urls = EXCLUDED.required_type_urls,
			state = 'published',
			first_published_at = COALESCE(
				joysafeter_egress_apply_status.first_published_at,
				EXCLUDED.first_published_at
			),
			updated_at = now()
		WHERE joysafeter_egress_apply_status.state IN ('pending', 'published')
	`, uuid.New(), value.groupKey, value.generation, value.version, requiredTypes)
	if err != nil {
		return err
	}
	return r.recomputeGeneration(ctx, value.groupKey, value.generation, "publish")
}

func (r *PostgresRecorder) writeConnected(ctx context.Context, identity group.Identity) error {
	now := time.Now().UTC()
	_, err := r.pool.Exec(ctx, `
		INSERT INTO joysafeter_egress_node_connections (
			id, group_key, node_id, controller_instance, envoy_version,
			connected_at, last_seen_at, lease_expires_at, disconnected_at
		) VALUES ($1, $2, $3, $4, $5, $6, $6, $7, NULL)
		ON CONFLICT (group_key, node_id) DO UPDATE SET
			controller_instance = EXCLUDED.controller_instance,
			envoy_version = EXCLUDED.envoy_version,
			connected_at = EXCLUDED.connected_at,
			last_seen_at = EXCLUDED.last_seen_at,
			lease_expires_at = EXCLUDED.lease_expires_at,
			disconnected_at = NULL,
			updated_at = now()
	`, uuid.New(), identity.GroupKey, identity.NodeID, r.instanceID, identity.Metadata.EnvoyVersion, now, now.Add(r.leaseTTL))
	if err != nil {
		return err
	}
	return r.recomputeGroupNonTerminal(ctx, identity.GroupKey, "connect")
}

func (r *PostgresRecorder) writeDisconnected(ctx context.Context, identity group.Identity) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE joysafeter_egress_node_connections
		SET disconnected_at = now(), lease_expires_at = now(), updated_at = now()
		WHERE group_key = $1 AND node_id = $2 AND controller_instance = $3
	`, identity.GroupKey, identity.NodeID, r.instanceID)
	if err != nil {
		return err
	}
	return r.recomputeGroupNonTerminal(ctx, identity.GroupKey, "disconnect")
}

func (r *PostgresRecorder) recomputeGeneration(ctx context.Context, groupKey string, generation uint64, trigger string) error {
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		r.metrics.Recompute.WithLabelValues(trigger, "error").Inc()
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := withGenerationLock(ctx, tx, groupKey, generation, func() error {
		return recomputeApplyStatus(ctx, tx, groupKey, generation)
	}); err != nil {
		r.metrics.Recompute.WithLabelValues(trigger, "error").Inc()
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		r.metrics.Recompute.WithLabelValues(trigger, "error").Inc()
		return err
	}
	r.metrics.Recompute.WithLabelValues(trigger, "ok").Inc()
	return nil
}

func (r *PostgresRecorder) recomputeGroupNonTerminal(ctx context.Context, groupKey, trigger string) error {
	rows, err := r.pool.Query(ctx, `
		SELECT generation FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND state IN ('pending', 'published')
	`, groupKey)
	if err != nil {
		return err
	}
	var generations []uint64
	for rows.Next() {
		var generation int64
		if err := rows.Scan(&generation); err != nil {
			rows.Close()
			return err
		}
		generations = append(generations, uint64(generation))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, generation := range generations {
		if err := r.recomputeGeneration(ctx, groupKey, generation, trigger); err != nil {
			return err
		}
	}
	return nil
}

func (r *PostgresRecorder) recomputeAllNonTerminal(ctx context.Context) error {
	rows, err := r.pool.Query(ctx, `
		SELECT group_key, generation FROM joysafeter_egress_apply_status
		WHERE state IN ('pending', 'published')
	`)
	if err != nil {
		return err
	}
	type ref struct {
		groupKey   string
		generation uint64
	}
	var refs []ref
	for rows.Next() {
		var groupKey string
		var generation int64
		if err := rows.Scan(&groupKey, &generation); err != nil {
			rows.Close()
			return err
		}
		refs = append(refs, ref{groupKey: groupKey, generation: uint64(generation)})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, rf := range refs {
		if err := r.recomputeGeneration(ctx, rf.groupKey, rf.generation, "ticker"); err != nil {
			r.logger.Error("periodic apply-status recompute failed", "group", rf.groupKey, "generation", rf.generation, "error", err)
			continue
		}
	}
	return nil
}

func (r *PostgresRecorder) writeACK(ctx context.Context, value event) error {
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	status := value.kind
	var errorSummary *string
	if value.kind == "nack" {
		reason := value.reason
		errorSummary = &reason
	}
	_, err = tx.Exec(ctx, `
		INSERT INTO joysafeter_egress_node_apply_status (
			id, group_key, generation, node_id, type_url, xds_version,
			status, nonce_sha256, controller_instance, error_summary, observed_at
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
		ON CONFLICT (group_key, generation, node_id, type_url) DO UPDATE SET
			xds_version = EXCLUDED.xds_version,
			status = EXCLUDED.status,
			nonce_sha256 = EXCLUDED.nonce_sha256,
			controller_instance = EXCLUDED.controller_instance,
			error_summary = EXCLUDED.error_summary,
			observed_at = now(),
			updated_at = now()
		WHERE joysafeter_egress_node_apply_status.status <> 'nack'
		   OR EXCLUDED.status = 'nack'
	`, uuid.New(), value.identity.GroupKey, value.generation, value.identity.NodeID, value.typeURL,
		value.version, status, hashNonce(value.nonce), r.instanceID, errorSummary)
	if err != nil {
		return err
	}
	err = withGenerationLock(ctx, tx, value.identity.GroupKey, value.generation, func() error {
		if value.kind == "nack" {
			_, execErr := tx.Exec(ctx, `
				UPDATE joysafeter_egress_apply_status
				SET state = 'failed', reason_code = 'ENVOY_NACK', error_summary = $4,
					failed_at = now(), updated_at = now()
				WHERE group_key = $1 AND generation = $2 AND xds_version = $3
				  AND state IN ('pending', 'published', 'applied')
			`, value.identity.GroupKey, value.generation, value.version, value.reason)
			return execErr
		}
		return recomputeApplyStatus(ctx, tx, value.identity.GroupKey, value.generation)
	})
	if err != nil {
		if value.kind == "ack" {
			r.metrics.Recompute.WithLabelValues("ack", "error").Inc()
		}
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		if value.kind == "ack" {
			r.metrics.Recompute.WithLabelValues("ack", "error").Inc()
		}
		return err
	}
	if value.kind == "ack" {
		r.metrics.Recompute.WithLabelValues("ack", "ok").Inc()
	}
	return nil
}

func (r *PostgresRecorder) heartbeat() {
	r.activeMu.Lock()
	active := make([]group.Identity, 0, len(r.active))
	for _, identity := range r.active {
		active = append(active, identity)
	}
	r.activeMu.Unlock()
	if len(active) == 0 {
		return
	}
	ctx, cancel := context.WithTimeout(r.ctx, 5*time.Second)
	defer cancel()
	now := time.Now().UTC()
	for _, identity := range active {
		_, err := r.pool.Exec(ctx, `
			UPDATE joysafeter_egress_node_connections
			SET last_seen_at = $4, lease_expires_at = $5, updated_at = now()
			WHERE group_key = $1 AND node_id = $2 AND controller_instance = $3
			  AND disconnected_at IS NULL
		`, identity.GroupKey, identity.NodeID, r.instanceID, now, now.Add(r.leaseTTL))
		if err != nil {
			r.metrics.StatusEvents.WithLabelValues("heartbeat", "error").Inc()
			r.logger.Error("renew Envoy connection lease", "node", identity.NodeID, "error", err)
		}
	}
}

func hashNonce(value string) *string {
	if value == "" {
		return nil
	}
	digest := sha256.Sum256([]byte(value))
	encoded := hex.EncodeToString(digest[:])
	return &encoded
}

func connectionKey(identity group.Identity) string {
	return identity.GroupKey + "\x00" + identity.NodeID
}
