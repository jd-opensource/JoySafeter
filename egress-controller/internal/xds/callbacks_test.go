package xds

import (
	"log/slog"
	"testing"

	corev3 "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	logv3 "github.com/envoyproxy/go-control-plane/pkg/log"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/prometheus/client_golang/prometheus"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestSotWAndDeltaStreamIDsDoNotCollide(t *testing.T) {
	metrics := telemetry.New(prometheus.NewRegistry())
	manager := NewManager(cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.NewDefaultLogger()), slog.Default(), metrics)
	callbacks := NewCallbacks(manager, slog.Default(), metrics)

	sotwNode := testNode(t, "sotw-node", "sotw")
	deltaNode := testNode(t, "delta-node", "delta")
	if _, err := callbacks.bind(streamKey{protocol: "sotw", id: 1}, sotwNode); err != nil {
		t.Fatal(err)
	}
	if _, err := callbacks.bind(streamKey{protocol: "delta", id: 1}, deltaNode); err != nil {
		t.Fatal(err)
	}
	if len(callbacks.streams) != 2 {
		t.Fatalf("stream count = %d, want 2", len(callbacks.streams))
	}
	callbacks.closeStream(streamKey{protocol: "sotw", id: 1}, sotwNode)
	callbacks.closeStream(streamKey{protocol: "delta", id: 1}, deltaNode)
	if len(callbacks.streams) != 0 {
		t.Fatalf("stream count after close = %d", len(callbacks.streams))
	}
}

func testNode(t *testing.T, nodeID, shardID string) *corev3.Node {
	t.Helper()
	metadata, err := structpb.NewStruct(map[string]any{
		"deployment_id": "test", "environment": "test", "region": "local",
		"provider": "k8s", "shard_id": shardID, "envoy_version": "1.39.0",
		"config_schema_version": "1",
	})
	if err != nil {
		t.Fatal(err)
	}
	return &corev3.Node{Id: nodeID, Metadata: metadata}
}
