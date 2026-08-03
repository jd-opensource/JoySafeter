//go:build integration

package status

import (
	"context"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/prometheus/client_golang/prometheus"
)

func TestPostgresRecorderLifecycle(t *testing.T) {
	databaseURL := os.Getenv("JOYSAFETER_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("JOYSAFETER_TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	truncateStatusTables(t, pool)

	groupKey := "v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	insertGeneration(t, pool, groupKey, 1)
	insertGeneration(t, pool, groupKey, 2)
	recorder, err := NewPostgresRecorder(
		ctx, databaseURL, "controller-test", 128, 30*time.Second, 10*time.Second, time.Hour,
		slog.Default(), telemetry.New(prometheus.NewRegistry()),
	)
	if err != nil {
		t.Fatal(err)
	}
	identity := group.Identity{
		NodeID: "envoy-test-1", GroupKey: groupKey,
		Metadata: group.Metadata{EnvoyVersion: "1.39.0"},
	}
	required := []string{
		"type.googleapis.com/envoy.config.cluster.v3.Cluster",
		"type.googleapis.com/envoy.config.listener.v3.Listener",
	}
	recorder.Connected(identity)
	recorder.Published(groupKey, 1, "g1-test", required, false)
	recorder.ACK(identity, 1, "g1-test", required[0], "raw-nonce-cds")
	recorder.ACK(identity, 1, "g1-test", required[1], "raw-nonce-lds")
	recorder.Published(groupKey, 2, "g2-test", required, false)
	recorder.NACK(identity, 2, "g2-test", required[1], "raw-nonce-nack", "invalid listener")
	closeContext, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if err := recorder.Close(closeContext); err != nil {
		t.Fatal(err)
	}

	var appliedState string
	var connectedNodes, requiredACKs, ackedACKs int
	if err := pool.QueryRow(ctx, `
		SELECT state, connected_nodes, required_acks, acked_acks
		FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND generation = 1
	`, groupKey).Scan(&appliedState, &connectedNodes, &requiredACKs, &ackedACKs); err != nil {
		t.Fatal(err)
	}
	if appliedState != "applied" || connectedNodes != 1 || requiredACKs != 2 || ackedACKs != 2 {
		t.Fatalf("unexpected applied status: %s nodes=%d required=%d acked=%d", appliedState, connectedNodes, requiredACKs, ackedACKs)
	}

	var failedState, reasonCode string
	if err := pool.QueryRow(ctx, `
		SELECT state, reason_code
		FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND generation = 2
	`, groupKey).Scan(&failedState, &reasonCode); err != nil {
		t.Fatal(err)
	}
	if failedState != "failed" || reasonCode != "ENVOY_NACK" {
		t.Fatalf("unexpected failed status: %s %s", failedState, reasonCode)
	}

	var nonceHash string
	if err := pool.QueryRow(ctx, `
		SELECT nonce_sha256
		FROM joysafeter_egress_node_apply_status
		WHERE group_key = $1 AND generation = 1 AND type_url = $2
	`, groupKey, required[0]).Scan(&nonceHash); err != nil {
		t.Fatal(err)
	}
	if nonceHash == "" || nonceHash == "raw-nonce-cds" || len(nonceHash) != 64 {
		t.Fatalf("nonce was not safely hashed: %q", nonceHash)
	}
}

func TestPostgresRecorderTerminalStatesAreMonotonicAcrossControllers(t *testing.T) {
	databaseURL := os.Getenv("JOYSAFETER_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("JOYSAFETER_TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	truncateStatusTables(t, pool)

	groupKey := "v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
	insertGeneration(t, pool, groupKey, 1)
	insertGeneration(t, pool, groupKey, 2)
	requiredType := "type.googleapis.com/envoy.config.listener.v3.Listener"
	identity := group.Identity{
		NodeID: "envoy-monotonic-1", GroupKey: groupKey,
		Metadata: group.Metadata{EnvoyVersion: "1.39.0"},
	}

	first := newTestRecorder(t, ctx, databaseURL, "controller-first")
	first.Connected(identity)
	first.Published(groupKey, 1, "g1-monotonic", []string{requiredType}, false)
	first.NACK(identity, 1, "g1-monotonic", requiredType, "nonce-g1-nack", "invalid listener")
	first.Published(groupKey, 2, "g2-monotonic", []string{requiredType}, false)
	closeTestRecorder(t, ctx, first)

	if _, err := pool.Exec(ctx, `
		UPDATE joysafeter_egress_apply_status
		SET state = 'superseded', updated_at = now()
		WHERE group_key = $1 AND generation = 2
	`, groupKey); err != nil {
		t.Fatal(err)
	}

	second := newTestRecorder(t, ctx, databaseURL, "controller-second")
	second.Connected(identity)
	second.Published(groupKey, 1, "g1-monotonic", []string{requiredType}, false)
	second.Published(groupKey, 1, "g1-monotonic", []string{requiredType}, true)
	second.ACK(identity, 1, "g1-monotonic", requiredType, "nonce-g1-late-ack")
	second.Published(groupKey, 2, "g2-monotonic", []string{requiredType}, true)
	second.ACK(identity, 2, "g2-monotonic", requiredType, "nonce-g2-late-ack")
	second.NACK(identity, 2, "g2-monotonic", requiredType, "nonce-g2-late-nack", "late nack")
	closeTestRecorder(t, ctx, second)

	assertApplyState(t, pool, groupKey, 1, "failed")
	assertApplyState(t, pool, groupKey, 2, "superseded")

	var nodeStatus string
	if err := pool.QueryRow(ctx, `
		SELECT status
		FROM joysafeter_egress_node_apply_status
		WHERE group_key = $1 AND generation = 1 AND node_id = $2 AND type_url = $3
	`, groupKey, identity.NodeID, requiredType).Scan(&nodeStatus); err != nil {
		t.Fatal(err)
	}
	if nodeStatus != "nack" {
		t.Fatalf("late ACK overwrote terminal node NACK: %s", nodeStatus)
	}
}

func TestPostgresRecorderPublishRecomputesPreexistingACK(t *testing.T) {
	databaseURL := os.Getenv("JOYSAFETER_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("JOYSAFETER_TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	truncateStatusTables(t, pool)

	groupKey := "v1:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
	requiredType := "type.googleapis.com/envoy.config.listener.v3.Listener"
	insertGeneration(t, pool, groupKey, 1)
	identity := group.Identity{
		NodeID: "envoy-prepublish-1", GroupKey: groupKey,
		Metadata: group.Metadata{EnvoyVersion: "1.39.0"},
	}

	recorder := newTestRecorder(t, ctx, databaseURL, "controller-prepublish")
	recorder.Connected(identity)
	recorder.ACK(identity, 1, "g1-prepublish", requiredType, "nonce-before-publish")
	recorder.Published(groupKey, 1, "g1-prepublish", []string{requiredType}, false)
	closeTestRecorder(t, ctx, recorder)

	var state string
	var connectedNodes, requiredACKs, ackedACKs int
	if err := pool.QueryRow(ctx, `
		SELECT state, connected_nodes, required_acks, acked_acks
		FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND generation = 1
	`, groupKey).Scan(&state, &connectedNodes, &requiredACKs, &ackedACKs); err != nil {
		t.Fatal(err)
	}
	if state != "applied" || connectedNodes != 1 || requiredACKs != 1 || ackedACKs != 1 {
		t.Fatalf("publish did not recompute preexisting ACK: state=%s nodes=%d required=%d acked=%d", state, connectedNodes, requiredACKs, ackedACKs)
	}
}

func newTestRecorder(t *testing.T, ctx context.Context, databaseURL, instanceID string) *PostgresRecorder {
	t.Helper()
	recorder, err := NewPostgresRecorder(
		ctx, databaseURL, instanceID, 128, 30*time.Second, 10*time.Second, time.Hour,
		slog.Default(), telemetry.New(prometheus.NewRegistry()),
	)
	if err != nil {
		t.Fatal(err)
	}
	return recorder
}

func closeTestRecorder(t *testing.T, ctx context.Context, recorder *PostgresRecorder) {
	t.Helper()
	closeContext, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if err := recorder.Close(closeContext); err != nil {
		t.Fatal(err)
	}
}

func assertApplyState(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64, expected string) {
	t.Helper()
	var actual string
	if err := pool.QueryRow(context.Background(), `
		SELECT state
		FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND generation = $2
	`, groupKey, generation).Scan(&actual); err != nil {
		t.Fatal(err)
	}
	if actual != expected {
		t.Fatalf("generation %d state regressed: got %s want %s", generation, actual, expected)
	}
}

func truncateStatusTables(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	lockEgressIntegrationTables(t, pool)
	if _, err := pool.Exec(context.Background(), `
		TRUNCATE joysafeter_egress_node_apply_status,
		         joysafeter_egress_apply_status,
		         joysafeter_egress_node_connections,
		         joysafeter_egress_outbox_events,
		         joysafeter_egress_group_generations CASCADE
	`); err != nil {
		t.Fatal(err)
	}
}

func lockEgressIntegrationTables(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	const lockKey = "joysafeter-egress-integration-tests"
	ctx := context.Background()
	lockConfig := pool.Config()
	lockConfig.MinConns = 0
	lockConfig.MaxConns = 1
	lockPool, err := pgxpool.NewWithConfig(ctx, lockConfig)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := lockPool.Acquire(ctx)
	if err != nil {
		lockPool.Close()
		t.Fatal(err)
	}
	if _, err := conn.Exec(ctx, `SELECT pg_advisory_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		conn.Release()
		lockPool.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := conn.Exec(context.Background(), `SELECT pg_advisory_unlock(hashtextextended($1, 0))`, lockKey); err != nil {
			t.Errorf("release egress integration DB lock: %v", err)
		}
		conn.Release()
		lockPool.Close()
	})
}

func insertGeneration(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64) {
	t.Helper()
	_, err := pool.Exec(context.Background(), `
		INSERT INTO joysafeter_egress_group_generations (
			id, group_key, generation, node_selector, policy_schema_version,
			desired_policies, content_sha256, state
		) VALUES (
			$1, $2, $3,
			'{"deployment_id":"test","environment":"test","region":"local","provider":"k8s","shard_id":"0","envoy_version":"1.39.0","config_schema_version":"1"}'::jsonb,
			1, '[]'::jsonb, $4, 'desired'
		)
	`, uuid.New(), groupKey, generation, strings.Repeat("0", 64))
	if err != nil {
		t.Fatal(err)
	}
}
