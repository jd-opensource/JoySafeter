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
	if _, err := pool.Exec(ctx, `
		TRUNCATE joysafeter_egress_node_apply_status,
		         joysafeter_egress_apply_status,
		         joysafeter_egress_node_connections,
		         joysafeter_egress_outbox_events,
		         joysafeter_egress_group_generations CASCADE
	`); err != nil {
		t.Fatal(err)
	}

	groupKey := "v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	insertGeneration(t, pool, groupKey, 1)
	insertGeneration(t, pool, groupKey, 2)
	recorder, err := NewPostgresRecorder(
		ctx, databaseURL, "controller-test", 128, 30*time.Second, 10*time.Second,
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
