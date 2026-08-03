//go:build integration

package status

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
)

const concurrencyType = "type.googleapis.com/envoy.config.listener.v3.Listener"

func concurrencyPool(t *testing.T) (*pgxpool.Pool, string) {
	t.Helper()
	databaseURL := os.Getenv("JOYSAFETER_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("JOYSAFETER_TEST_DATABASE_URL is not set")
	}
	pool, err := pgxpool.New(context.Background(), databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool, databaseURL
}

func insertPublishedApplyStatus(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64, version string, requiredTypes []string) {
	t.Helper()
	types, err := json.Marshal(requiredTypes)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(context.Background(), `
		INSERT INTO joysafeter_egress_apply_status (
			id, group_key, generation, xds_version, required_type_urls, state,
			connected_nodes, required_acks, acked_acks, first_published_at
		) VALUES ($1, $2, $3, $4, $5::jsonb, 'published', 0, 0, 0, now())
	`, uuid.New(), groupKey, generation, version, types); err != nil {
		t.Fatal(err)
	}
}

func insertActiveConnection(t *testing.T, pool *pgxpool.Pool, groupKey, nodeID string) {
	t.Helper()
	if _, err := pool.Exec(context.Background(), `
		INSERT INTO joysafeter_egress_node_connections (
			id, group_key, node_id, controller_instance, envoy_version,
			connected_at, last_seen_at, lease_expires_at, disconnected_at
		) VALUES ($1, $2, $3, 'controller-test', '1.39.0', now(), now(), now() + interval '30 seconds', NULL)
	`, uuid.New(), groupKey, nodeID); err != nil {
		t.Fatal(err)
	}
}

func insertNodeACKTx(ctx context.Context, tx pgx.Tx, groupKey string, generation uint64, nodeID, typeURL, version string) error {
	_, err := tx.Exec(ctx, `
		INSERT INTO joysafeter_egress_node_apply_status (
			id, group_key, generation, node_id, type_url, xds_version,
			status, nonce_sha256, controller_instance, error_summary, observed_at
		) VALUES ($1, $2, $3, $4, $5, $6, 'ack', NULL, 'controller-test', NULL, now())
		ON CONFLICT (group_key, generation, node_id, type_url) DO UPDATE SET
			status = 'ack', xds_version = EXCLUDED.xds_version, observed_at = now()
	`, uuid.New(), groupKey, generation, nodeID, typeURL, version)
	return err
}

func readAggregate(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64) (string, int, int, int) {
	t.Helper()
	var state string
	var connected, required, acked int
	if err := pool.QueryRow(context.Background(), `
		SELECT state, connected_nodes, required_acks, acked_acks
		FROM joysafeter_egress_apply_status
		WHERE group_key = $1 AND generation = $2
	`, groupKey, generation).Scan(&state, &connected, &required, &acked); err != nil {
		t.Fatal(err)
	}
	return state, connected, required, acked
}

// With the advisory lock, two replicas ACKing different nodes concurrently
// converge to applied with both ACKs counted.
func TestApplyStatusConcurrentACKsAppliedWithLock(t *testing.T) {
	pool, _ := concurrencyPool(t)
	ctx := context.Background()
	truncateStatusTables(t, pool)

	groupKey := "v1:" + strings.Repeat("C", 43)
	version := "gen1-with-lock"
	insertGeneration(t, pool, groupKey, 1)
	insertPublishedApplyStatus(t, pool, groupKey, 1, version, []string{concurrencyType})
	insertActiveConnection(t, pool, groupKey, "node-a")
	insertActiveConnection(t, pool, groupKey, "node-b")

	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for _, node := range []string{"node-a", "node-b"} {
		node := node
		wg.Add(1)
		go func() {
			defer wg.Done()
			tx, err := pool.Begin(ctx)
			if err != nil {
				errs <- err
				return
			}
			defer tx.Rollback(ctx)
			if err := insertNodeACKTx(ctx, tx, groupKey, 1, node, concurrencyType, version); err != nil {
				errs <- err
				return
			}
			if err := withGenerationLock(ctx, tx, groupKey, 1, func() error {
				return recomputeApplyStatus(ctx, tx, groupKey, 1)
			}); err != nil {
				errs <- err
				return
			}
			errs <- tx.Commit(ctx)
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}

	state, connected, required, acked := readAggregate(t, pool, groupKey, 1)
	if state != "applied" || connected != 2 || required != 2 || acked != 2 {
		t.Fatalf("with lock: state=%s connected=%d required=%d acked=%d; want applied/2/2/2", state, connected, required, acked)
	}
}

// Without the advisory lock, the second writer's counts CTE snapshot predates
// the first writer's committed ACK, so it overwrites the aggregate and one ACK
// is lost. This documents the exact defect the lock prevents.
func TestApplyStatusConcurrentACKsLoseUpdateWithoutLock(t *testing.T) {
	pool, _ := concurrencyPool(t)
	ctx := context.Background()
	truncateStatusTables(t, pool)

	groupKey := "v1:" + strings.Repeat("D", 43)
	version := "gen1-no-lock"
	insertGeneration(t, pool, groupKey, 1)
	insertPublishedApplyStatus(t, pool, groupKey, 1, version, []string{concurrencyType})
	insertActiveConnection(t, pool, groupKey, "node-a")
	insertActiveConnection(t, pool, groupKey, "node-b")

	txFirst, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer txFirst.Rollback(ctx)
	if err := insertNodeACKTx(ctx, txFirst, groupKey, 1, "node-b", concurrencyType, version); err != nil {
		t.Fatal(err)
	}
	// Recompute WITHOUT the lock: takes the apply_status row lock, snapshot sees only node-b.
	if err := recomputeApplyStatus(ctx, txFirst, groupKey, 1); err != nil {
		t.Fatal(err)
	}

	txSecond, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer txSecond.Rollback(ctx)
	if err := insertNodeACKTx(ctx, txSecond, groupKey, 1, "node-a", concurrencyType, version); err != nil {
		t.Fatal(err)
	}
	recomputed := make(chan error, 1)
	go func() { recomputed <- recomputeApplyStatus(ctx, txSecond, groupKey, 1) }()

	// Let txSecond's UPDATE take its snapshot and block on txFirst's row lock.
	time.Sleep(500 * time.Millisecond)
	if err := txFirst.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err := <-recomputed; err != nil {
		t.Fatal(err)
	}
	if err := txSecond.Commit(ctx); err != nil {
		t.Fatal(err)
	}

	state, _, required, acked := readAggregate(t, pool, groupKey, 1)
	if acked != 1 || required != 2 || state != "published" {
		t.Fatalf("no lock: expected lost-update artifact required=2/acked=1/published, got required=%d acked=%d state=%s", required, acked, state)
	}
}

// A published generation with one un-ACKed node becomes applied once that node
// disconnects, because the recompute on disconnect shrinks the required set.
func TestApplyStatusDisconnectUnblocksApplied(t *testing.T) {
	pool, databaseURL := concurrencyPool(t)
	ctx := context.Background()
	truncateStatusTables(t, pool)

	groupKey := "v1:" + strings.Repeat("E", 43)
	insertGeneration(t, pool, groupKey, 1)
	recorder := newTestRecorder(t, ctx, databaseURL, "controller-disc")

	nodeA := makeIdentity(groupKey, "node-a")
	nodeB := makeIdentity(groupKey, "node-b")
	recorder.Connected(nodeA)
	recorder.Connected(nodeB)
	recorder.Published(groupKey, 1, "gen1-disc", []string{concurrencyType}, false)
	recorder.ACK(nodeA, 1, "gen1-disc", concurrencyType, "nonce-a")
	// node-b never ACKs; it disconnects instead.
	recorder.Disconnected(nodeB)
	closeTestRecorder(t, ctx, recorder)

	state, connected, required, acked := readAggregate(t, pool, groupKey, 1)
	if state != "applied" || connected != 1 || required != 1 || acked != 1 {
		t.Fatalf("disconnect: state=%s connected=%d required=%d acked=%d; want applied/1/1/1", state, connected, required, acked)
	}
}

func makeIdentity(groupKey, nodeID string) group.Identity {
	return group.Identity{
		NodeID: nodeID, GroupKey: groupKey,
		Metadata: group.Metadata{EnvoyVersion: "1.39.0"},
	}
}
