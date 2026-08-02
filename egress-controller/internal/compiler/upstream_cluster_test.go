package compiler

import (
	"testing"

	"github.com/joysafeter/joysafeter/egress-controller/internal/policy"
)

// A plaintext (non-TLS) upstream must NOT use ALPN-based auto protocol
// negotiation: Envoy NACKs a cluster that configures ALPN ("auto_config") on a
// non-ALPN (plaintext) transport socket. Only an https upstream, which carries
// a TLS transport socket, may negotiate via ALPN.
func TestUpstreamClusterPlaintextHasNoALPNAutoConfig(t *testing.T) {
	c, err := New(DefaultConfig())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	plain := c.upstreamCluster("up_plain", policy.Upstream{
		Scheme: "http", Host: "mock.egress.internal", Port: 8080, Protocol: "auto",
	})
	if _, hasTS := plain["transport_socket"]; hasTS {
		t.Fatalf("plaintext upstream must not have a TLS transport_socket: %#v", plain["transport_socket"])
	}
	if opts, ok := plain["typed_extension_protocol_options"].(map[string]any); ok {
		inner, _ := opts["envoy.extensions.upstreams.http.v3.HttpProtocolOptions"].(map[string]any)
		if _, hasAuto := inner["auto_config"]; hasAuto {
			t.Fatalf("plaintext upstream must not use ALPN auto_config: %#v", inner)
		}
	}

	tls := c.upstreamCluster("up_tls", policy.Upstream{
		Scheme: "https", Host: "api.example.com", Port: 443, Protocol: "auto",
	})
	if _, hasTS := tls["transport_socket"]; !hasTS {
		t.Fatalf("https upstream must have a TLS transport_socket")
	}
	opts, ok := tls["typed_extension_protocol_options"].(map[string]any)
	if !ok {
		t.Fatalf("https auto upstream must set http protocol options")
	}
	inner, _ := opts["envoy.extensions.upstreams.http.v3.HttpProtocolOptions"].(map[string]any)
	if _, hasAuto := inner["auto_config"]; !hasAuto {
		t.Fatalf("https auto upstream should negotiate via ALPN auto_config: %#v", inner)
	}
}

// The credential route must NOT list its ext_authz inject header in
// request_headers_to_remove: ext_authz overwrites that header with the platform
// credential, and the route-level removal runs in the router AFTER ext_authz, so
// listing it strips the injected credential before it reaches the upstream. All
// other sandbox-supplied credential headers MUST still be stripped.
func TestCredentialRouteDoesNotStripExtAuthzInjectHeader(t *testing.T) {
	route := policy.CredentialRoute{
		RouteID:      "llm",
		InjectHeader: "authorization",
		MatchPath:    policy.PathMatch{Kind: "prefix", Value: "/"},
		Methods:      []string{"POST"},
		Upstream:     policy.Upstream{Scheme: "http", Host: "mock.egress.internal", Port: 8080, Protocol: "auto", BasePath: "/v1/"},
		// As normalized by policy schema: inject header + other sensitive headers.
		RemoveHeaders: []string{"authorization", "x-api-key"},
	}
	r := credentialRoute("018ff000-0000-7000-8000-000000000001", route, "/", "POST", "test-group", 1)
	removed := map[string]bool{}
	for _, h := range r["request_headers_to_remove"].([]any) {
		removed[h.(string)] = true
	}
	if removed["authorization"] {
		t.Fatalf("inject header 'authorization' must NOT be in request_headers_to_remove (ext_authz overwrites it): %v", removed)
	}
	if !removed["x-api-key"] {
		t.Fatalf("other sandbox credential headers (x-api-key) must still be stripped: %v", removed)
	}
}
