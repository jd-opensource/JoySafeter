//go:build integration

package xds_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"testing"
	"time"

	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	logv3 "github.com/envoyproxy/go-control-plane/pkg/log"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/compiler"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
	"github.com/joysafeter/joysafeter/egress-controller/internal/status"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/joysafeter/joysafeter/egress-controller/internal/xds"
	"github.com/prometheus/client_golang/prometheus"
)

type publishingManager struct {
	manager   *xds.Manager
	published chan snapshot.Compiled
}

func (p publishingManager) Publish(ctx context.Context, compiled snapshot.Compiled) error {
	if err := p.manager.Publish(ctx, compiled); err != nil {
		return err
	}
	p.published <- compiled
	return nil
}

func (p publishingManager) Restore(ctx context.Context, compiled snapshot.Compiled) error {
	return p.manager.Restore(ctx, compiled)
}

func TestPostgresDesiredGenerationCompilesPublishesAndPersistsACKAndNACK(t *testing.T) {
	databaseURL := os.Getenv("JOYSAFETER_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("JOYSAFETER_TEST_DATABASE_URL is not set")
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	truncateEgressTables(t, pool)

	metadata := group.Metadata{
		DeploymentID: "prod", Environment: "production", Region: "cn-east-1", Provider: "k8s",
		ShardID: "0", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
	}
	groupKey, err := metadata.Key()
	if err != nil {
		t.Fatal(err)
	}
	identity := group.Identity{NodeID: "envoy-prod-1", GroupKey: groupKey, Metadata: metadata}

	registry := prometheus.NewRegistry()
	metrics := telemetry.New(registry)
	recorder, err := status.NewPostgresRecorder(
		ctx, databaseURL, "controller-e2e", 256, 30*time.Second, 10*time.Second, time.Hour, slog.Default(), metrics,
	)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		closeCtx, closeCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer closeCancel()
		if err := recorder.Close(closeCtx); err != nil {
			t.Fatalf("close recorder: %v", err)
		}
	}()

	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger())
	manager := xds.NewManager(cache, slog.Default(), metrics, recorder)
	publisher := publishingManager{manager: manager, published: make(chan snapshot.Compiled, 4)}
	compile, err := compiler.New(testCompilerConfig())
	if err != nil {
		t.Fatal(err)
	}
	reconciler, err := source.NewPostgresReconciler(
		ctx, databaseURL, time.Second, compile, publisher, slog.Default(), metrics,
	)
	if err != nil {
		t.Fatal(err)
	}
	defer reconciler.Close()
	if err := reconciler.Initial(ctx); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		reconciler.Run(ctx)
	}()
	defer func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Fatal("PostgreSQL reconciler did not stop")
		}
	}()

	insertDesiredPolicyGeneration(t, pool, groupKey, metadata, 1, "018ff000-0000-7000-8000-000000000101")
	compiled1 := waitForPublished(t, publisher.published, 1)
	if err := manager.Connect(ctx, identity); err != nil {
		t.Fatal(err)
	}
	for index, typeURL := range compiled1.RequiredTypes {
		manager.ACK(identity, typeURL, compiled1.Version, fmt.Sprintf("nonce-g1-%d", index))
	}
	waitForApplyState(t, pool, groupKey, 1, "applied", len(compiled1.RequiredTypes), len(compiled1.RequiredTypes))

	insertDesiredPolicyGeneration(t, pool, groupKey, metadata, 2, "018ff000-0000-7000-8000-000000000102")
	compiled2 := waitForPublished(t, publisher.published, 2)
	manager.NACK(ctx, identity, compiled2.RequiredTypes[len(compiled2.RequiredTypes)-1], compiled2.Version, "nonce-g2-nack", "listener rejected")
	waitForApplyState(t, pool, groupKey, 2, "failed", 0, 0)
}

func testCompilerConfig() compiler.Config {
	config := compiler.DefaultConfig()
	config.AuthzTLS = false
	config.DownstreamTLS = false
	config.PublicCA = "/etc/ssl/certs/ca-certificates.crt"
	return config
}

func insertDesiredPolicyGeneration(t *testing.T, pool *pgxpool.Pool, groupKey string, metadata group.Metadata, generation uint64, sandboxID string) {
	t.Helper()
	selector, err := json.Marshal(metadata)
	if err != nil {
		t.Fatal(err)
	}
	policies := []map[string]any{{
		"sandbox_id": sandboxID,
		"mode":       "limited",
		"credential_routes": []map[string]any{{
			"route_id":          "external-direct:crm:0",
			"consumer_route_id": "external-direct:crm",
			"kind":              "external",
			"match_authority":   "external-egress.internal",
			"match_path":        map[string]any{"kind": "exact", "value": "/api/customers/current"},
			"methods":           []string{"GET"},
			"upstream": map[string]any{
				"scheme": "https", "host": "crm.example.com", "port": 443,
				"base_path": "/api/customers/current", "protocol": "http1",
			},
			"credential_ref":  map[string]any{"kind": "external", "secret_name": "crm-prod", "secret_key": "ACCESS_TOKEN"},
			"inject_header":   "authorization",
			"inject_scheme":   map[string]any{"kind": "bearer"},
			"remove_headers":  []string{"cookie", "x-api-key"},
			"timeout_profile": "default",
			"websocket":       false,
		}},
		"allowed_public_hosts": []string{"downloads.example.com"},
		"denied_cidrs":         []string{"10.0.0.0/8"},
	}}
	desiredPolicies, err := json.Marshal(policies)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(desiredPolicies)
	ctx := context.Background()
	if _, err := pool.Exec(ctx, `
		UPDATE joysafeter_egress_group_generations
		SET state = 'superseded', superseded_at = now(), updated_at = now()
		WHERE group_key = $1 AND state = 'desired'
	`, groupKey); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO joysafeter_egress_group_generations (
			id, group_key, generation, node_selector, policy_schema_version,
			desired_policies, content_sha256, state
		) VALUES ($1, $2, $3, $4, 1, $5, $6, 'desired')
	`, uuid.New(), groupKey, generation, selector, desiredPolicies, hex.EncodeToString(digest[:])); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO joysafeter_egress_outbox_events (id, group_key, generation, event_type)
		VALUES ($1, $2, $3, 'egress.group_generation.desired')
	`, uuid.New(), groupKey, generation); err != nil {
		t.Fatal(err)
	}
}

func truncateEgressTables(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(context.Background(), `
		TRUNCATE joysafeter_egress_node_apply_status,
		         joysafeter_egress_apply_status,
		         joysafeter_egress_node_connections,
		         joysafeter_egress_outbox_events,
		         joysafeter_egress_group_generations CASCADE
	`)
	if err != nil {
		t.Fatal(err)
	}
}

func waitForPublished(t *testing.T, published <-chan snapshot.Compiled, generation uint64) snapshot.Compiled {
	t.Helper()
	timer := time.NewTimer(10 * time.Second)
	defer timer.Stop()
	for {
		select {
		case compiled := <-published:
			if compiled.Generation == generation {
				return compiled
			}
		case <-timer.C:
			t.Fatalf("generation %d was not published as xDS candidate", generation)
		}
	}
}

func waitForApplyState(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64, expected string, requiredACKs, ackedACKs int) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		var state string
		var required, acked int
		err := pool.QueryRow(context.Background(), `
			SELECT state, required_acks, acked_acks
			FROM joysafeter_egress_apply_status
			WHERE group_key = $1 AND generation = $2
		`, groupKey, generation).Scan(&state, &required, &acked)
		if err == nil && state == expected {
			if expected != "applied" || (required == requiredACKs && acked == ackedACKs) {
				return
			}
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("generation %d did not reach state %q", generation, expected)
}
