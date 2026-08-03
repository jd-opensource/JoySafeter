package compiler

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"sort"
	"testing"

	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
)

type parityFixture struct {
	PolicySchemaVersion int             `json:"policy_schema_version"`
	GroupKey            string          `json:"group_key"`
	Generation          uint64          `json:"generation"`
	ContentSHA256       string          `json:"content_sha256"`
	Policies            json.RawMessage `json:"policies"`
	ExpectedResources   struct {
		Clusters  []string `json:"clusters"`
		Routes    []string `json:"routes"`
		Listeners []string `json:"listeners"`
	} `json:"expected_resources"`
}

func TestGoCompilerMatchesSharedRustParityFixture(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/compiler/parity-kubernetes-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture parityFixture
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	metadata := group.Metadata{
		DeploymentID: "test", Environment: "test", Region: "local", Provider: "k8s",
		ShardID: "0", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
	}
	compiler, err := New(DefaultConfig())
	if err != nil {
		t.Fatal(err)
	}
	compiled, err := compiler.Compile(context.Background(), source.DesiredGeneration{
		GroupKey: fixture.GroupKey, Generation: fixture.Generation, NodeSelector: metadata,
		PolicySchemaVersion: fixture.PolicySchemaVersion, DesiredPolicies: fixture.Policies,
		ContentSHA256: fixture.ContentSHA256,
	})
	if err != nil {
		t.Fatal(err)
	}

	assertResourceNames(t, compiled.Snapshot.GetResources(resourcev3.ClusterType), fixture.ExpectedResources.Clusters)
	assertResourceNames(t, compiled.Snapshot.GetResources(resourcev3.RouteType), fixture.ExpectedResources.Routes)
	assertResourceNames(t, compiled.Snapshot.GetResources(resourcev3.ListenerType), fixture.ExpectedResources.Listeners)
}

func assertResourceNames(t *testing.T, resources map[string]cachetypes.Resource, expected []string) {
	t.Helper()
	actual := make([]string, 0, len(resources))
	for name := range resources {
		actual = append(actual, name)
	}
	sort.Strings(actual)
	if !reflect.DeepEqual(actual, expected) {
		t.Fatalf("resource names = %#v, want %#v", actual, expected)
	}
}
