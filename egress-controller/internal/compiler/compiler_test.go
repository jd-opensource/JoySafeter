package compiler

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/policy"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
	"google.golang.org/protobuf/encoding/protojson"
)

func TestCompileKubernetesPolicyProducesStrictLDSRDSCDS(t *testing.T) {
	desired := testDesiredGeneration(t, "k8s")
	value, err := New(DefaultConfig())
	if err != nil {
		t.Fatal(err)
	}
	compiled, err := value.Compile(context.Background(), desired)
	if err != nil {
		t.Fatal(err)
	}
	if len(compiled.RequiredTypes) != 3 {
		t.Fatalf("required types = %#v", compiled.RequiredTypes)
	}
	if got := len(compiled.Snapshot.GetResources(resourcev3.ClusterType)); got != 3 {
		t.Fatalf("clusters = %d", got)
	}
	if got := len(compiled.Snapshot.GetResources(resourcev3.RouteType)); got != 2 {
		t.Fatalf("routes = %d", got)
	}
	if got := len(compiled.Snapshot.GetResources(resourcev3.ListenerType)); got != 2 {
		t.Fatalf("listeners = %d", got)
	}
	assertSnapshotContainsNoSecret(t, compiled.Snapshot.GetResources(resourcev3.ClusterType), "actual-secret")
	assertSnapshotContainsNoSecret(t, compiled.Snapshot.GetResources(resourcev3.RouteType), "actual-secret")
	assertSnapshotContainsNoSecret(t, compiled.Snapshot.GetResources(resourcev3.ListenerType), "actual-secret")
	assertSnapshotContains(t, compiled.Snapshot.GetResources(resourcev3.RouteType), desired.GroupKey)
	assertSnapshotContains(t, compiled.Snapshot.GetResources(resourcev3.RouteType), "joysafeter_policy_generation")
	assertSnapshotContains(t, compiled.Snapshot.GetResources(resourcev3.RouteType), `"1"`)
}

func TestCompileDockerPolicyProducesPerSandboxPipeListener(t *testing.T) {
	compiled := compileTestPolicy(t, "docker")
	listeners := compiled.Snapshot.GetResources(resourcev3.ListenerType)
	// Each Docker sandbox now yields two listeners: the http.sock egress
	// listener and the grpc.sock AgentBridge control-channel listener.
	if len(listeners) != 2 {
		t.Fatalf("listeners = %d, want 2", len(listeners))
	}
	raw, err := protojson.Marshal(listeners["joysafeter_018ff000_0000_7000_8000_000000000001_http"])
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), "/sockets/018ff000-0000-7000-8000-000000000001/http.sock") {
		t.Fatalf("listener does not use sandbox pipe: %s", raw)
	}
}

func TestCompileDockerPolicyEmitsControlChannelListener(t *testing.T) {
	compiled := compileTestPolicy(t, "docker")
	listeners := compiled.Snapshot.GetResources(resourcev3.ListenerType)
	httpName := "joysafeter_018ff000_0000_7000_8000_000000000001_http"
	grpcName := "joysafeter_018ff000_0000_7000_8000_000000000001_grpc"
	if _, ok := listeners[httpName]; !ok {
		t.Fatalf("missing http listener among %v", listenerNames(listeners))
	}
	grpcListener, ok := listeners[grpcName]
	if !ok {
		t.Fatalf("missing grpc control listener among %v", listenerNames(listeners))
	}
	raw, err := protojson.Marshal(grpcListener)
	if err != nil {
		t.Fatal(err)
	}
	// The control channel routes to the AgentBridge upstream over the grpc.sock pipe.
	if !strings.Contains(string(raw), "/sockets/018ff000-0000-7000-8000-000000000001/grpc.sock") {
		t.Fatalf("control listener does not use grpc.sock pipe: %s", raw)
	}
	// It is NOT external egress, so it must carry no ext_authz filter.
	if strings.Contains(string(raw), "ext_authz") {
		t.Fatalf("control-channel listener must not have ext_authz: %s", raw)
	}
}

func listenerNames(listeners map[string]cachetypes.Resource) []string {
	names := make([]string, 0, len(listeners))
	for name := range listeners {
		names = append(names, name)
	}
	return names
}

func TestCompileIsDeterministic(t *testing.T) {
	first := compileTestPolicy(t, "k8s")
	second := compileTestPolicy(t, "k8s")
	if first.Version != second.Version {
		t.Fatalf("versions differ: %s != %s", first.Version, second.Version)
	}
}

func TestKubernetesExternalAllowedPathsShareConsumerRouteBase(t *testing.T) {
	const sandboxID = "018ff000-0000-7000-8000-000000000001"
	consumerRouteID := "external-direct:crm"
	credentialRoutes := []policy.CredentialRoute{
		{
			RouteID: "external-direct:crm:0", ConsumerRouteID: consumerRouteID,
			MatchPath: policy.PathMatch{Kind: "exact", Value: "/api/customers/current"},
			Methods:   []string{"GET"}, Upstream: policy.Upstream{Host: "crm.example.com", BasePath: "/api/customers/current"},
		},
		{
			RouteID: "external-direct:crm:1", ConsumerRouteID: consumerRouteID,
			MatchPath: policy.PathMatch{Kind: "prefix", Value: "/api/orders/"},
			Methods:   []string{"GET"}, Upstream: policy.Upstream{Host: "crm.example.com", BasePath: "/api/orders/"},
		},
	}
	config := buildKubernetesCredentialRoutes([]policy.SandboxPolicy{{
		SandboxID: sandboxID, CredentialRoutes: credentialRoutes,
	}}, "test-group", 7)
	virtualHosts := config["virtual_hosts"].([]any)
	routes := virtualHosts[0].(map[string]any)["routes"].([]any)
	wantBase := syntheticRouteBase(sandboxID, consumerRouteID)
	wantedPaths := map[string]bool{
		wantBase + "/api/customers/current": false,
		wantBase + "/api/orders/":           false,
	}
	for _, raw := range routes[:len(credentialRoutes)] {
		match := raw.(map[string]any)["match"].(map[string]any)
		path := routeMatchPath(match)
		if _, ok := wantedPaths[path]; !ok {
			t.Fatalf("unexpected synthetic route path %q", path)
		}
		wantedPaths[path] = true
	}
	for path, found := range wantedPaths {
		if !found {
			t.Fatalf("missing synthetic route path %q", path)
		}
	}
}

func compileTestPolicy(t *testing.T, provider string) snapshot.Compiled {
	t.Helper()
	value, err := New(DefaultConfig())
	if err != nil {
		t.Fatal(err)
	}
	compiled, err := value.Compile(context.Background(), testDesiredGeneration(t, provider))
	if err != nil {
		t.Fatal(err)
	}
	return compiled
}

func testDesiredGeneration(t *testing.T, provider string) source.DesiredGeneration {
	t.Helper()
	metadata := group.Metadata{
		DeploymentID: "test", Environment: "test", Region: "local", Provider: provider,
		ShardID: "0", HostID: "host-1", EnvoyVersion: "1.39.0", ConfigSchemaVersion: "1",
	}
	if provider != "docker" {
		metadata.HostID = ""
	}
	groupKey, err := metadata.Key()
	if err != nil {
		t.Fatal(err)
	}
	secretName := "provider-secret"
	secretKey := "API_KEY"
	projectID := "018ff000-0000-7000-8000-000000000002"
	policies := []map[string]any{{
		"sandbox_id": "018ff000-0000-7000-8000-000000000001", "project_id": projectID, "mode": "limited",
		"credential_routes": []map[string]any{{
			"route_id": "llm:primary", "kind": "llm", "match_authority": "llm-egress.internal",
			"match_path": map[string]any{"kind": "prefix", "value": "/v1"}, "methods": []string{"POST"},
			"upstream":       map[string]any{"scheme": "https", "host": "api.example.com", "port": 443, "base_path": "/v1", "protocol": "http2"},
			"credential_ref": map[string]any{"kind": "llm", "secret_name": secretName, "secret_key": secretKey, "project_id": projectID},
			"inject_header":  "authorization", "inject_scheme": map[string]any{"kind": "bearer"},
			"remove_headers": []string{"x-api-key"}, "timeout_profile": "streaming", "websocket": false,
		}},
		"allowed_public_hosts": []string{"downloads.example.com"}, "denied_cidrs": []string{"10.0.0.0/8"},
	}}
	raw, err := json.Marshal(policies)
	if err != nil {
		t.Fatal(err)
	}
	return source.DesiredGeneration{
		GroupKey: groupKey, Generation: 1, NodeSelector: metadata, PolicySchemaVersion: 1,
		DesiredPolicies: raw, ContentSHA256: strings.Repeat("0", 64),
	}
}

func assertSnapshotContainsNoSecret(t *testing.T, resources map[string]cachetypes.Resource, forbidden string) {
	t.Helper()
	for name, resource := range resources {
		raw, err := protojson.Marshal(resource)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(raw), forbidden) {
			t.Fatalf("resource %s contains secret material", name)
		}
	}
}

func assertSnapshotContains(t *testing.T, resources map[string]cachetypes.Resource, expected string) {
	t.Helper()
	for _, resource := range resources {
		raw, err := protojson.Marshal(resource)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(raw), expected) {
			return
		}
	}
	t.Fatalf("snapshot resources do not contain %q", expected)
}
