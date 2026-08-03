//go:build integration

package source

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/prometheus/client_golang/prometheus"
)

func TestPostgresReconcilerNotificationAndFullFallback(t *testing.T) {
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
	truncateEgressControlPlane(t, pool)

	metadata := group.Metadata{
		DeploymentID: "test", Environment: "test", Region: "local", Provider: "k8s",
		ShardID: "0", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
	}
	groupKey, err := metadata.Key()
	if err != nil {
		t.Fatal(err)
	}
	publisher := &recordingPublisher{published: make(chan uint64, 4)}
	compiler := CompilerFunc(func(_ context.Context, desired DesiredGeneration) (snapshot.Compiled, error) {
		value, err := cachev3.NewSnapshot(fmt.Sprintf("g%d", desired.Generation), map[resourcev3.Type][]cachetypes.Resource{
			resourcev3.ClusterType: {}, resourcev3.RouteType: {}, resourcev3.ListenerType: {},
		})
		if err != nil {
			return snapshot.Compiled{}, err
		}
		if err := value.ConstructVersionMap(); err != nil {
			return snapshot.Compiled{}, err
		}
		return snapshot.Compiled{
			GroupKey: desired.GroupKey, Generation: desired.Generation, Version: fmt.Sprintf("g%d", desired.Generation),
			RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType}, Snapshot: value,
		}, nil
	})
	reconciler, err := NewPostgresReconciler(
		ctx, databaseURL, time.Second, compiler, publisher, slog.Default(), telemetry.New(prometheus.NewRegistry()),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer reconciler.Close()
	if err := reconciler.Initial(ctx); err != nil {
		t.Fatal(err)
	}
	runDone := make(chan struct{})
	go func() {
		defer close(runDone)
		reconciler.Run(ctx)
	}()

	insertDesiredGeneration(t, pool, groupKey, metadata, 1, true)
	waitForGeneration(t, publisher.published, 1, 5*time.Second)

	insertDesiredGeneration(t, pool, groupKey, metadata, 2, false)
	waitForGeneration(t, publisher.published, 2, 5*time.Second)
	cancel()
	select {
	case <-runDone:
	case <-time.After(5 * time.Second):
		t.Fatal("PostgreSQL reconciler did not stop after cancellation")
	}
}

func TestPostgresReconcilerRestoresAppliedAndSkipsDurableNACK(t *testing.T) {
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
	truncateEgressControlPlane(t, pool)
	metadata := group.Metadata{
		DeploymentID: "test", Environment: "test", Region: "local", Provider: "k8s",
		ShardID: "0", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
	}
	groupKey, err := metadata.Key()
	if err != nil {
		t.Fatal(err)
	}
	insertDesiredGeneration(t, pool, groupKey, metadata, 1, false)
	insertApplyState(t, pool, groupKey, 1, "applied")
	insertDesiredGeneration(t, pool, groupKey, metadata, 2, false)
	insertApplyState(t, pool, groupKey, 2, "failed")

	publisher := &recordingPublisher{
		published: make(chan uint64, 4), restored: make(chan uint64, 4),
	}
	reconciler, err := NewPostgresReconciler(
		ctx, databaseURL, time.Second, emptyCompiler(), publisher, slog.Default(), telemetry.New(prometheus.NewRegistry()),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer reconciler.Close()
	if err := reconciler.Initial(ctx); err != nil {
		t.Fatal(err)
	}
	waitForGeneration(t, publisher.restored, 1, 5*time.Second)
	select {
	case generation := <-publisher.published:
		t.Fatalf("durably rejected generation was published: %d", generation)
	case <-time.After(250 * time.Millisecond):
	}
}

type recordingPublisher struct {
	mu        sync.Mutex
	values    []uint64
	published chan uint64
	restored  chan uint64
}

func (p *recordingPublisher) Publish(_ context.Context, compiled snapshot.Compiled) error {
	p.mu.Lock()
	p.values = append(p.values, compiled.Generation)
	p.mu.Unlock()
	p.published <- compiled.Generation
	return nil
}

func (p *recordingPublisher) Restore(_ context.Context, compiled snapshot.Compiled) error {
	if p.restored != nil {
		p.restored <- compiled.Generation
	}
	return nil
}

func emptyCompiler() CompilerFunc {
	return func(_ context.Context, desired DesiredGeneration) (snapshot.Compiled, error) {
		value, err := cachev3.NewSnapshot(fmt.Sprintf("g%d", desired.Generation), map[resourcev3.Type][]cachetypes.Resource{
			resourcev3.ClusterType: {}, resourcev3.RouteType: {}, resourcev3.ListenerType: {},
		})
		if err != nil {
			return snapshot.Compiled{}, err
		}
		if err := value.ConstructVersionMap(); err != nil {
			return snapshot.Compiled{}, err
		}
		return snapshot.Compiled{
			GroupKey: desired.GroupKey, Generation: desired.Generation, Version: fmt.Sprintf("g%d", desired.Generation),
			RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType}, Snapshot: value,
		}, nil
	}
}

func truncateEgressControlPlane(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	lockEgressIntegrationTables(t, pool)
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

func insertDesiredGeneration(t *testing.T, pool *pgxpool.Pool, groupKey string, metadata group.Metadata, generation uint64, notify bool) {
	t.Helper()
	selector, err := json.Marshal(metadata)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(context.Background(), `
		INSERT INTO joysafeter_egress_group_generations (
			id, group_key, generation, node_selector, policy_schema_version,
			desired_policies, content_sha256, state
		) VALUES ($1, $2, $3, $4, 1, '[]'::jsonb, $5, 'desired')
	`, uuid.New(), groupKey, generation, selector, strings.Repeat(fmt.Sprintf("%x", generation%16), 64))
	if err != nil {
		t.Fatal(err)
	}
	if notify {
		_, err = pool.Exec(context.Background(), `
			INSERT INTO joysafeter_egress_outbox_events (id, group_key, generation, event_type)
			VALUES ($1, $2, $3, 'egress.group_generation.desired')
		`, uuid.New(), groupKey, generation)
		if err != nil {
			t.Fatal(err)
		}
	}
}

func insertApplyState(t *testing.T, pool *pgxpool.Pool, groupKey string, generation uint64, state string) {
	t.Helper()
	_, err := pool.Exec(context.Background(), `
		INSERT INTO joysafeter_egress_apply_status (
			id, group_key, generation, xds_version, required_type_urls, state,
			connected_nodes, required_acks, acked_acks
		) VALUES (
			$1, $2, $3, $4,
			'["type.googleapis.com/envoy.config.cluster.v3.Cluster","type.googleapis.com/envoy.config.listener.v3.Listener"]'::jsonb,
			$5::varchar, 1, 2, CASE WHEN $5::varchar = 'applied' THEN 2 ELSE 0 END
		)
	`, uuid.New(), groupKey, generation, fmt.Sprintf("g%d", generation), state)
	if err != nil {
		t.Fatal(err)
	}
}

func waitForGeneration(t *testing.T, published <-chan uint64, expected uint64, timeout time.Duration) {
	t.Helper()
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	for {
		select {
		case generation := <-published:
			if generation == expected {
				return
			}
		case <-timer.C:
			t.Fatalf("generation %d was not published", expected)
		}
	}
}
