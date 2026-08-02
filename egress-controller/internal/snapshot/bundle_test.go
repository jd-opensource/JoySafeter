package snapshot

import (
	"encoding/json"
	"testing"

	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
)

func TestCompileIsDeterministic(t *testing.T) {
	first, err := Compile(testBundle([]json.RawMessage{
		json.RawMessage(`{"name":"b","connectTimeout":"1s","type":"STATIC"}`),
		json.RawMessage(`{"name":"a","connectTimeout":"1s","type":"STATIC"}`),
	}))
	if err != nil {
		t.Fatal(err)
	}
	second, err := Compile(testBundle([]json.RawMessage{
		json.RawMessage(`{"name":"a","connectTimeout":"1s","type":"STATIC"}`),
		json.RawMessage(`{"name":"b","connectTimeout":"1s","type":"STATIC"}`),
	}))
	if err != nil {
		t.Fatal(err)
	}
	if first[0].Version != second[0].Version {
		t.Fatalf("resource order changed version: %q != %q", first[0].Version, second[0].Version)
	}
}

func TestCompileRejectsDuplicateNames(t *testing.T) {
	_, err := Compile(testBundle([]json.RawMessage{
		json.RawMessage(`{"name":"same","connectTimeout":"1s","type":"STATIC"}`),
		json.RawMessage(`{"name":"same","connectTimeout":"1s","type":"STATIC"}`),
	}))
	if err == nil {
		t.Fatal("expected duplicate resource name to fail")
	}
}

func testBundle(clusters []json.RawMessage) Bundle {
	return Bundle{
		SchemaVersion: BundleSchemaVersion,
		Groups: []GroupBundle{{
			Metadata: group.Metadata{
				DeploymentID: "test", Environment: "test", Region: "local", Provider: "k8s",
				ShardID: "0", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
			},
			Generation: 1,
			Resources:  Resources{Clusters: clusters},
		}},
	}
}
