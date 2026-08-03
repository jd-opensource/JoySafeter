package group

import (
	"testing"

	corev3 "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestFromNodeDeterministic(t *testing.T) {
	metadata, err := structpb.NewStruct(map[string]any{
		"deployment_id": "Prod-A", "environment": "Production", "region": "cn-east-1",
		"provider": "k8s", "shard_id": "17", "envoy_version": "1.39.0",
		"config_schema_version": "1",
	})
	if err != nil {
		t.Fatal(err)
	}
	first, err := FromNode(&corev3.Node{Id: "envoy-1", Metadata: metadata})
	if err != nil {
		t.Fatal(err)
	}
	second, err := FromNode(&corev3.Node{Id: "envoy-2", Metadata: metadata})
	if err != nil {
		t.Fatal(err)
	}
	if first.GroupKey != second.GroupKey {
		t.Fatalf("same metadata produced different groups: %q != %q", first.GroupKey, second.GroupKey)
	}
	if first.NodeID == second.NodeID {
		t.Fatal("node identities should remain distinct")
	}
}

func TestDockerRequiresHostID(t *testing.T) {
	metadata, err := structpb.NewStruct(map[string]any{
		"deployment_id": "a", "environment": "prod", "region": "local",
		"provider": "docker", "shard_id": "0", "envoy_version": "1.39.0",
		"config_schema_version": "1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := FromNode(&corev3.Node{Id: "envoy-1", Metadata: metadata}); err == nil {
		t.Fatal("expected missing host_id to fail")
	}
}

func TestK8sHostIDIsForwardCompatibleWithSharedGroup(t *testing.T) {
	base := map[string]any{
		"deployment_id": "a", "environment": "prod", "region": "local",
		"provider": "k8s", "shard_id": "0", "envoy_version": "1.39.0",
		"config_schema_version": "1",
	}
	firstMetadata, err := structpb.NewStruct(base)
	if err != nil {
		t.Fatal(err)
	}
	withHost := make(map[string]any, len(base)+1)
	for key, value := range base {
		withHost[key] = value
	}
	withHost["host_id"] = "worker-a"
	secondMetadata, err := structpb.NewStruct(withHost)
	if err != nil {
		t.Fatal(err)
	}
	first, err := FromNode(&corev3.Node{Id: "envoy-1", Metadata: firstMetadata})
	if err != nil {
		t.Fatal(err)
	}
	second, err := FromNode(&corev3.Node{Id: "envoy-2", Metadata: secondMetadata})
	if err != nil {
		t.Fatal(err)
	}
	if first.GroupKey != second.GroupKey {
		t.Fatalf("K8s host_id must not split the compatibility group: %q != %q", first.GroupKey, second.GroupKey)
	}
}
