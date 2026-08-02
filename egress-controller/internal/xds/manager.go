package xds

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"sync"
	"time"

	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/status"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
)

var ErrRejectedVersion = errors.New("snapshot version was previously rejected")

type Manager struct {
	mu          sync.Mutex
	cache       cachev3.SnapshotCache
	groups      map[string]*groupState
	nodeStreams map[string]int
	logger      *slog.Logger
	metrics     *telemetry.Metrics
	recorder    status.Recorder
}

type groupState struct {
	current   versionedSnapshot
	candidate versionedSnapshot
	lastGood  versionedSnapshot
	connected map[string]int
	acks      map[string]map[string]bool
	failed    map[string]struct{}
}

type versionedSnapshot struct {
	version       string
	generation    uint64
	requiredTypes []string
	snapshot      *cachev3.Snapshot
}

func NewManager(cache cachev3.SnapshotCache, logger *slog.Logger, metrics *telemetry.Metrics, recorders ...status.Recorder) *Manager {
	recorder := status.Recorder(status.NopRecorder{})
	if len(recorders) > 0 && recorders[0] != nil {
		recorder = recorders[0]
	}
	return &Manager{
		cache: cache, groups: make(map[string]*groupState), nodeStreams: make(map[string]int),
		logger: logger, metrics: metrics, recorder: recorder,
	}
}

func (m *Manager) Publish(ctx context.Context, compiled snapshot.Compiled) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	state, err := m.ensureGroupLocked(compiled.GroupKey)
	if err != nil {
		return err
	}
	if _, rejected := state.failed[compiled.Version]; rejected {
		m.metrics.Snapshots.WithLabelValues("rejected_duplicate").Inc()
		return fmt.Errorf("%w: %s", ErrRejectedVersion, compiled.Version)
	}
	if state.current.version == compiled.Version {
		m.metrics.Snapshots.WithLabelValues("unchanged").Inc()
		return nil
	}
	if compiled.Generation < state.current.generation {
		return fmt.Errorf("generation regression: current=%d candidate=%d", state.current.generation, compiled.Generation)
	}

	candidate := versionedSnapshot{
		version: compiled.Version, generation: compiled.Generation,
		requiredTypes: append([]string(nil), compiled.RequiredTypes...), snapshot: compiled.Snapshot,
	}
	// Delta xDS only re-ACKs resource types whose resources actually changed.
	// Requiring an ACK on an unchanged type (e.g. the shared credential clusters
	// that every sandbox on a host reuses) would never be satisfied for the 2nd+
	// generation, stalling the apply. Require ACKs only for the types that
	// changed vs the currently-published snapshot; unchanged types keep the
	// prior generation's ACK.
	candidate.requiredTypes = changedRequiredTypes(state.current.snapshot, compiled.Snapshot, compiled.RequiredTypes)
	if err := m.cache.SetSnapshot(ctx, compiled.GroupKey, compiled.Snapshot); err != nil {
		m.metrics.Snapshots.WithLabelValues("publish_error").Inc()
		return fmt.Errorf("publish snapshot: %w", err)
	}
	state.current = candidate
	state.candidate = candidate
	state.acks = make(map[string]map[string]bool)
	// No resource type changed (content identical to the current snapshot):
	// Envoy will send no delta and thus no ACK, but it is already applying this
	// exact config. Promote immediately and record it applied-on-publish with
	// the full (non-empty) type list so the apply gate does not wait forever.
	appliedOnPublish := len(candidate.requiredTypes) == 0
	recordedTypes := candidate.requiredTypes
	if appliedOnPublish {
		state.lastGood = candidate
		state.candidate = versionedSnapshot{}
		recordedTypes = compiled.RequiredTypes
	}
	m.metrics.Snapshots.WithLabelValues("published").Inc()
	m.metrics.SnapshotGeneration.Set(float64(compiled.Generation))
	m.recorder.Published(compiled.GroupKey, compiled.Generation, compiled.Version, recordedTypes, appliedOnPublish)
	m.logger.Info("published xDS candidate", "group", compiled.GroupKey, "generation", compiled.Generation, "version", compiled.Version, "required_types", candidate.requiredTypes)
	return nil
}

func (m *Manager) Restore(ctx context.Context, compiled snapshot.Compiled) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if compiled.Snapshot == nil || compiled.Version == "" || compiled.Generation == 0 || len(compiled.RequiredTypes) == 0 {
		return errors.New("restored snapshot is incomplete")
	}
	state, err := m.ensureGroupLocked(compiled.GroupKey)
	if err != nil {
		return err
	}
	if state.current.generation > compiled.Generation {
		return fmt.Errorf("restore generation regression: current=%d restored=%d", state.current.generation, compiled.Generation)
	}
	value := versionedSnapshot{
		version: compiled.Version, generation: compiled.Generation,
		requiredTypes: append([]string(nil), compiled.RequiredTypes...), snapshot: compiled.Snapshot,
	}
	if err := m.cache.SetSnapshot(ctx, compiled.GroupKey, compiled.Snapshot); err != nil {
		return fmt.Errorf("restore snapshot: %w", err)
	}
	state.current = value
	state.lastGood = value
	state.candidate = versionedSnapshot{}
	state.acks = make(map[string]map[string]bool)
	m.metrics.Snapshots.WithLabelValues("restored").Inc()
	m.metrics.SnapshotGeneration.Set(float64(compiled.Generation))
	m.logger.Info("restored xDS last-known-good", "group", compiled.GroupKey, "generation", compiled.Generation, "version", compiled.Version)
	return nil
}

func (m *Manager) Connect(ctx context.Context, identity group.Identity) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	state, err := m.ensureGroupLocked(identity.GroupKey)
	if err != nil {
		return err
	}
	if state.current.snapshot == nil {
		return errors.New("node group has no bootstrap snapshot")
	}
	if err := m.cache.SetSnapshot(ctx, identity.GroupKey, state.current.snapshot); err != nil {
		return fmt.Errorf("attach node group snapshot: %w", err)
	}
	state.connected[identity.NodeID]++
	m.nodeStreams[nodeStreamKey(identity)]++
	m.metrics.ConnectedNodes.Set(float64(len(m.nodeStreams)))
	m.recorder.Connected(identity)
	return nil
}

func (m *Manager) Disconnect(identity group.Identity) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if state := m.groups[identity.GroupKey]; state != nil {
		decrement(state.connected, identity.NodeID)
	}
	decrement(m.nodeStreams, nodeStreamKey(identity))
	m.metrics.ConnectedNodes.Set(float64(len(m.nodeStreams)))
	m.recorder.Disconnected(identity)
}

func (m *Manager) ACK(identity group.Identity, typeURL, version, nonce string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	state := m.groups[identity.GroupKey]
	if state == nil || state.candidate.version == "" || state.candidate.version != version {
		return
	}
	if !containsType(state.candidate.requiredTypes, typeURL) {
		return
	}
	if state.acks[identity.NodeID] == nil {
		state.acks[identity.NodeID] = make(map[string]bool)
	}
	state.acks[identity.NodeID][typeURL] = true
	m.metrics.XDSACKs.WithLabelValues("ack", shortType(typeURL)).Inc()
	m.recorder.ACK(identity, state.candidate.generation, version, typeURL, nonce)
	if quorumACKed(state) {
		state.lastGood = state.candidate
		state.candidate = versionedSnapshot{}
		m.metrics.Snapshots.WithLabelValues("accepted").Inc()
		m.logger.Info("xDS candidate accepted by connected-node quorum", "group", identity.GroupKey, "version", version)
	}
}

func (m *Manager) NACK(ctx context.Context, identity group.Identity, typeURL, version, nonce, reason string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	state := m.groups[identity.GroupKey]
	if state == nil || state.candidate.version == "" || state.candidate.version != version {
		return
	}
	state.failed[version] = struct{}{}
	m.recorder.NACK(identity, state.candidate.generation, version, typeURL, nonce, reason)
	m.metrics.XDSACKs.WithLabelValues("nack", shortType(typeURL)).Inc()
	m.metrics.Snapshots.WithLabelValues("rejected").Inc()
	rollback := state.lastGood
	if rollback.snapshot == nil {
		var err error
		rollback, err = emptyVersionedSnapshot()
		if err != nil {
			m.logger.Error("build emergency empty snapshot", "error", err)
			return
		}
	}
	if err := m.cache.SetSnapshot(ctx, identity.GroupKey, rollback.snapshot); err != nil {
		m.metrics.Snapshots.WithLabelValues("rollback_error").Inc()
		m.logger.Error("roll back rejected xDS snapshot", "group", identity.GroupKey, "error", err)
		return
	}
	state.current = rollback
	state.candidate = versionedSnapshot{}
	state.acks = make(map[string]map[string]bool)
	m.metrics.Snapshots.WithLabelValues("rolled_back").Inc()
	m.logger.Error("xDS candidate NACKed; restored last-known-good", "group", identity.GroupKey, "node", identity.NodeID, "type", shortType(typeURL), "version", version, "reason", reason, "rollback_version", rollback.version)
}

func (m *Manager) ensureGroupLocked(groupKey string) (*groupState, error) {
	if state := m.groups[groupKey]; state != nil {
		return state, nil
	}
	empty, err := emptyVersionedSnapshot()
	if err != nil {
		return nil, err
	}
	state := &groupState{
		current: empty, lastGood: empty, connected: make(map[string]int),
		acks: make(map[string]map[string]bool), failed: make(map[string]struct{}),
	}
	m.groups[groupKey] = state
	return state, nil
}

func emptyVersionedSnapshot() (versionedSnapshot, error) {
	const version = "bootstrap-empty-v1"
	value, err := cachev3.NewSnapshot(version, map[resourcev3.Type][]cachetypes.Resource{
		resourcev3.ClusterType: {}, resourcev3.RouteType: {}, resourcev3.ListenerType: {},
	})
	if err != nil {
		return versionedSnapshot{}, err
	}
	if err := value.ConstructVersionMap(); err != nil {
		return versionedSnapshot{}, err
	}
	return versionedSnapshot{version: version, snapshot: value}, nil
}

func quorumACKed(state *groupState) bool {
	if len(state.connected) == 0 {
		return false
	}
	for nodeID := range state.connected {
		for _, typeURL := range state.candidate.requiredTypes {
			if !state.acks[nodeID][typeURL] {
				return false
			}
		}
	}
	return true
}

func containsType(types []string, typeURL string) bool {
	for _, required := range types {
		if typeURL == required {
			return true
		}
	}
	return false
}

// changedRequiredTypes returns the subset of candidateTypes whose per-resource
// version map differs between the previously-published snapshot and the next
// one. Delta xDS only sends (and Envoy only ACKs) resources that changed, so
// the apply gate must require ACKs only for changed types — otherwise a
// generation that leaves a type untouched (e.g. the shared credential clusters)
// would wait forever for an ACK that never comes. When prev is nil (first
// publish for a group), every candidate type is treated as changed.
func changedRequiredTypes(prev, next *cachev3.Snapshot, candidateTypes []string) []string {
	changed := make([]string, 0, len(candidateTypes))
	if prev == nil {
		return append(changed, candidateTypes...)
	}
	for _, typeURL := range candidateTypes {
		if !reflect.DeepEqual(prev.GetVersionMap(typeURL), next.GetVersionMap(typeURL)) {
			changed = append(changed, typeURL)
		}
	}
	return changed
}

func nodeStreamKey(identity group.Identity) string {
	return identity.GroupKey + "\x00" + identity.NodeID
}

func shortType(typeURL string) string {
	switch typeURL {
	case resourcev3.ClusterType:
		return "cds"
	case resourcev3.RouteType:
		return "rds"
	case resourcev3.ListenerType:
		return "lds"
	default:
		return "other"
	}
}

func decrement(values map[string]int, key string) {
	if values[key] <= 1 {
		delete(values, key)
		return
	}
	values[key]--
}

func rollbackContext() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 5*time.Second)
}
