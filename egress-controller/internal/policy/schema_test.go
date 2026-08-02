package policy

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestDecodeNormalizesStrictRefOnlyPolicy(t *testing.T) {
	raw := validPolicyJSON()
	policies, err := Decode(SchemaVersion, raw)
	if err != nil {
		t.Fatal(err)
	}
	if len(policies) != 1 {
		t.Fatalf("policies = %d", len(policies))
	}
	policy := policies[0]
	if policy.AllowedPublicHosts[0] != "*.example.com" || policy.AllowedPublicHosts[1] != "api.example.com" {
		t.Fatalf("hosts = %#v", policy.AllowedPublicHosts)
	}
	route := policy.CredentialRoutes[0]
	if route.ConsumerRouteID != route.RouteID {
		t.Fatalf("consumer route id = %q, route id = %q", route.ConsumerRouteID, route.RouteID)
	}
	if route.Upstream.Host != "xn--bcher-kva.example" || route.Upstream.Port != 443 {
		t.Fatalf("upstream = %#v", route.Upstream)
	}
	if route.RemoveHeaders[0] != "authorization" {
		t.Fatalf("remove headers = %#v", route.RemoveHeaders)
	}
}

func TestDecodeAcceptsDistinctConsumerRouteID(t *testing.T) {
	var policies []map[string]any
	if err := json.Unmarshal(validPolicyJSON(), &policies); err != nil {
		t.Fatal(err)
	}
	routes := policies[0]["credential_routes"].([]any)
	routes[0].(map[string]any)["kind"] = "external"
	routes[0].(map[string]any)["credential_ref"] = map[string]any{
		"kind": "external", "secret_name": "crm-secret", "secret_key": "ACCESS_TOKEN",
	}
	routes[0].(map[string]any)["consumer_route_id"] = "external-direct:crm"
	raw, err := json.Marshal(policies)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := Decode(SchemaVersion, raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := decoded[0].CredentialRoutes[0].ConsumerRouteID; got != "external-direct:crm" {
		t.Fatalf("consumer route id = %q", got)
	}
}

func TestDecodeRejectsSharedConsumerRouteForNonExternalKind(t *testing.T) {
	raw := strings.Replace(
		string(validPolicyJSON()),
		`"route_id":"llm:primary"`,
		`"route_id":"llm:primary","consumer_route_id":"shared"`,
		1,
	)
	if _, err := Decode(SchemaVersion, []byte(raw)); err == nil || !strings.Contains(err.Error(), "only for external") {
		t.Fatalf("expected shared non-external consumer route rejection, got %v", err)
	}
}

func TestDecodeRejectsDuplicateConsumerPathMethod(t *testing.T) {
	var policies []map[string]any
	if err := json.Unmarshal(validPolicyJSON(), &policies); err != nil {
		t.Fatal(err)
	}
	routes := policies[0]["credential_routes"].([]any)
	first := routes[0].(map[string]any)
	first["route_id"] = "external-direct:crm:0"
	first["consumer_route_id"] = "external-direct:crm"
	first["kind"] = "external"
	first["credential_ref"] = map[string]any{
		"kind": "external", "secret_name": "crm-secret", "secret_key": "ACCESS_TOKEN",
	}
	second := make(map[string]any, len(first))
	for key, value := range first {
		second[key] = value
	}
	second["route_id"] = "external-direct:crm:1"
	policies[0]["credential_routes"] = []any{first, second}
	raw, err := json.Marshal(policies)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Decode(SchemaVersion, raw); err == nil || !strings.Contains(err.Error(), "duplicate path/method") {
		t.Fatalf("expected duplicate consumer match rejection, got %v", err)
	}
}

func TestDecodeRejectsSecretBearingUnknownField(t *testing.T) {
	raw := strings.Replace(string(validPolicyJSON()), `"secret_key":"API_KEY"`, `"secret_key":"API_KEY","secret_value":"actual-secret"`, 1)
	if _, err := Decode(SchemaVersion, []byte(raw)); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("expected unknown secret field rejection, got %v", err)
	}
}

func TestDecodeRejectsIPUpstreamAndReservedHeader(t *testing.T) {
	for _, replacement := range []struct {
		old string
		new string
	}{
		{`"host":"bücher.example"`, `"host":"169.254.169.254"`},
		{`"inject_header":"authorization"`, `"inject_header":"host"`},
	} {
		raw := strings.Replace(string(validPolicyJSON()), replacement.old, replacement.new, 1)
		if _, err := Decode(SchemaVersion, []byte(raw)); err == nil {
			t.Fatalf("expected invalid policy for replacement %q", replacement.new)
		}
	}
}

func TestDecodeRejectsCredentialRefShapeMismatch(t *testing.T) {
	var policies []map[string]any
	if err := json.Unmarshal(validPolicyJSON(), &policies); err != nil {
		t.Fatal(err)
	}
	routes := policies[0]["credential_routes"].([]any)
	credentialRef := routes[0].(map[string]any)["credential_ref"].(map[string]any)
	credentialRef["kind"] = "mcp"
	raw, err := json.Marshal(policies)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Decode(SchemaVersion, raw); err == nil {
		t.Fatal("expected mismatched credential ref to be rejected")
	}
}

func validPolicyJSON() []byte {
	value := []map[string]any{{
		"sandbox_id": "018ff000-0000-7000-8000-000000000001",
		"project_id": "018ff000-0000-7000-8000-000000000002",
		"mode":       "limited",
		"credential_routes": []map[string]any{{
			"route_id": "llm:primary", "kind": "llm", "match_authority": "llm-egress.internal",
			"match_path": map[string]any{"kind": "prefix", "value": "/"},
			"methods":    []string{"POST"},
			"upstream": map[string]any{
				"scheme": "https", "host": "bücher.example", "port": 0, "base_path": "/v1", "protocol": "http2",
			},
			"credential_ref": map[string]any{
				"kind": "llm", "secret_name": "provider", "secret_key": "API_KEY",
			},
			"inject_header": "authorization", "inject_scheme": map[string]any{"kind": "bearer"},
			"remove_headers": []string{"x-api-key"}, "timeout_profile": "streaming", "websocket": false,
		}},
		"allowed_public_hosts": []string{"API.Example.com.", "*.Example.com", "api.example.com"},
		"denied_cidrs":         []string{"10.0.0.1/8", "169.254.169.254/32"},
	}}
	raw, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return raw
}
