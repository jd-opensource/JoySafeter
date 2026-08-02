package xds

import (
	"context"
	"log/slog"
	"testing"

	clusterv3 "github.com/envoyproxy/go-control-plane/envoy/config/cluster/v3"
	listenerv3 "github.com/envoyproxy/go-control-plane/envoy/config/listener/v3"
	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	logv3 "github.com/envoyproxy/go-control-plane/pkg/log"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/prometheus/client_golang/prometheus"
)

func TestManagerRejectsPreviouslyNACKedVersion(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := telemetry.New(registry)
	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger())
	manager := NewManager(cache, slog.Default(), metrics)
	identity := group.Identity{NodeID: "envoy-1", GroupKey: "group-1"}
	if err := manager.Connect(context.Background(), identity); err != nil {
		t.Fatal(err)
	}
	value := snapshotWithResources(t, "candidate", nil, []cachetypes.Resource{&listenerv3.Listener{Name: "l-nacked"}})
	compiled := snapshot.Compiled{
		GroupKey: identity.GroupKey, Generation: 1, Version: "candidate",
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType}, Snapshot: value,
	}
	if err := manager.Publish(context.Background(), compiled); err != nil {
		t.Fatal(err)
	}
	manager.NACK(context.Background(), identity, resourcev3.ListenerType, "candidate", "nonce", "invalid listener")
	if err := manager.Publish(context.Background(), compiled); !errorsIs(err, ErrRejectedVersion) {
		t.Fatalf("expected rejected version error, got %v", err)
	}
}

func TestManagerAcceptsSnapshotWithoutRDS(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := telemetry.New(registry)
	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger())
	manager := NewManager(cache, slog.Default(), metrics)
	identity := group.Identity{NodeID: "envoy-1", GroupKey: "group-1"}
	if err := manager.Connect(context.Background(), identity); err != nil {
		t.Fatal(err)
	}
	value := snapshotWithResources(t, "candidate", []cachetypes.Resource{&clusterv3.Cluster{Name: "c-accept"}}, []cachetypes.Resource{&listenerv3.Listener{Name: "l-accept"}})
	compiled := snapshot.Compiled{
		GroupKey: identity.GroupKey, Generation: 1, Version: "candidate",
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType}, Snapshot: value,
	}
	if err := manager.Publish(context.Background(), compiled); err != nil {
		t.Fatal(err)
	}
	manager.ACK(identity, resourcev3.ClusterType, "candidate", "nonce-cds")
	manager.ACK(identity, resourcev3.ListenerType, "candidate", "nonce-lds")

	manager.mu.Lock()
	defer manager.mu.Unlock()
	state := manager.groups[identity.GroupKey]
	if state.candidate.version != "" {
		t.Fatalf("candidate remained pending: %q", state.candidate.version)
	}
	if state.lastGood.version != "candidate" {
		t.Fatalf("last-known-good version = %q", state.lastGood.version)
	}
}

func TestManagerNACKRollsBackToDurablyRestoredSnapshot(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := telemetry.New(registry)
	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger())
	manager := NewManager(cache, slog.Default(), metrics)
	identity := group.Identity{NodeID: "envoy-1", GroupKey: "group-1"}
	restored := emptyCompiledSnapshot(t, identity.GroupKey, 1, "restored")
	if err := manager.Restore(context.Background(), restored); err != nil {
		t.Fatal(err)
	}
	if err := manager.Connect(context.Background(), identity); err != nil {
		t.Fatal(err)
	}
	// The candidate must actually change a resource type (a listener here) so it
	// is a real, NACK-able delta; an empty candidate identical to the restored
	// snapshot changes nothing and is applied on publish with no ACK to reject.
	candidate := snapshot.Compiled{
		GroupKey: identity.GroupKey, Generation: 2, Version: "candidate",
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType},
		Snapshot:      snapshotWithResources(t, "candidate", nil, []cachetypes.Resource{&listenerv3.Listener{Name: "l-candidate"}}),
	}
	if err := manager.Publish(context.Background(), candidate); err != nil {
		t.Fatal(err)
	}
	manager.NACK(context.Background(), identity, resourcev3.ListenerType, "candidate", "nonce", "invalid")

	manager.mu.Lock()
	defer manager.mu.Unlock()
	state := manager.groups[identity.GroupKey]
	if state.current.version != "restored" || state.lastGood.version != "restored" {
		t.Fatalf("rollback lost restored snapshot: current=%q last_good=%q", state.current.version, state.lastGood.version)
	}
}

func emptyCompiledSnapshot(t *testing.T, groupKey string, generation uint64, version string) snapshot.Compiled {
	t.Helper()
	value, err := cachev3.NewSnapshot(version, map[resourcev3.Type][]cachetypes.Resource{
		resourcev3.ClusterType: {}, resourcev3.RouteType: {}, resourcev3.ListenerType: {},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := value.ConstructVersionMap(); err != nil {
		t.Fatal(err)
	}
	return snapshot.Compiled{
		GroupKey: groupKey, Generation: generation, Version: version,
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType}, Snapshot: value,
	}
}

func errorsIs(err, target error) bool {

	for err != nil {
		if err == target {
			return true
		}
		type unwrapper interface{ Unwrap() error }
		value, ok := err.(unwrapper)
		if !ok {
			return false
		}
		err = value.Unwrap()
	}
	return false
}

// snapshotWithResources builds a delta-ready snapshot from named clusters and
// listeners (routes empty). ConstructVersionMap is what lets the manager diff
// resource types across generations.
func snapshotWithResources(t *testing.T, version string, clusters, listeners []cachetypes.Resource) *cachev3.Snapshot {
	t.Helper()
	value, err := cachev3.NewSnapshot(version, map[resourcev3.Type][]cachetypes.Resource{
		resourcev3.ClusterType:  clusters,
		resourcev3.RouteType:    {},
		resourcev3.ListenerType: listeners,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := value.ConstructVersionMap(); err != nil {
		t.Fatal(err)
	}
	return value
}

// TestManagerRequiresOnlyChangedResourceTypes proves the apply gate does not
// wait for an ACK on a resource type whose resources did not change between
// generations. Delta xDS only re-ACKs changed types; requiring an ACK on an
// unchanged type (e.g. the shared credential clusters) would stall every
// generation after the first on a host — blocking the 2nd+ sandbox.
func TestManagerRequiresOnlyChangedResourceTypes(t *testing.T) {
	metrics := telemetry.New(prometheus.NewRegistry())
	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger())
	manager := NewManager(cache, slog.Default(), metrics)
	identity := group.Identity{NodeID: "envoy-1", GroupKey: "group-1"}
	if err := manager.Connect(context.Background(), identity); err != nil {
		t.Fatal(err)
	}

	sharedCluster := []cachetypes.Resource{&clusterv3.Cluster{Name: "shared-authz"}}

	// Generation 1: cluster + listener are both new (current is the empty
	// bootstrap), so both types are required and must be ACKed.
	gen1 := snapshot.Compiled{
		GroupKey: identity.GroupKey, Generation: 1, Version: "g1",
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType},
		Snapshot:      snapshotWithResources(t, "g1", sharedCluster, []cachetypes.Resource{&listenerv3.Listener{Name: "l-sbx-a"}}),
	}
	if err := manager.Publish(context.Background(), gen1); err != nil {
		t.Fatal(err)
	}
	manager.ACK(identity, resourcev3.ClusterType, "g1", "n-cds-1")
	manager.ACK(identity, resourcev3.ListenerType, "g1", "n-lds-1")

	// Generation 2: SAME cluster, different listener (a second sandbox added;
	// the credential clusters are shared and unchanged).
	gen2 := snapshot.Compiled{
		GroupKey: identity.GroupKey, Generation: 2, Version: "g2",
		RequiredTypes: []string{resourcev3.ClusterType, resourcev3.ListenerType},
		Snapshot:      snapshotWithResources(t, "g2", sharedCluster, []cachetypes.Resource{&listenerv3.Listener{Name: "l-sbx-b"}}),
	}
	if err := manager.Publish(context.Background(), gen2); err != nil {
		t.Fatal(err)
	}

	manager.mu.Lock()
	required := append([]string(nil), manager.groups[identity.GroupKey].candidate.requiredTypes...)
	manager.mu.Unlock()
	if containsType(required, resourcev3.ClusterType) {
		t.Fatalf("Cluster must NOT be required for gen 2 (unchanged); required=%v", required)
	}
	if !containsType(required, resourcev3.ListenerType) {
		t.Fatalf("Listener must be required for gen 2 (changed); required=%v", required)
	}

	// ACKing only the changed type (Listener) must accept the candidate; the
	// unchanged Cluster keeps its prior generation's ACK.
	manager.ACK(identity, resourcev3.ListenerType, "g2", "n-lds-2")
	manager.mu.Lock()
	pending := manager.groups[identity.GroupKey].candidate.version
	manager.mu.Unlock()
	if pending != "" {
		t.Fatalf("candidate not accepted after ACKing only the changed type; still pending %q", pending)
	}
}
