package compiler

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"path"
	"sort"
	"strconv"
	"strings"

	clusterv3 "github.com/envoyproxy/go-control-plane/envoy/config/cluster/v3"
	listenerv3 "github.com/envoyproxy/go-control-plane/envoy/config/listener/v3"
	routev3 "github.com/envoyproxy/go-control-plane/envoy/config/route/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/clusters/dynamic_forward_proxy/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/filters/http/dynamic_forward_proxy/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/filters/http/ext_authz/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/filters/http/router/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/filters/network/http_connection_manager/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/transport_sockets/tls/v3"
	_ "github.com/envoyproxy/go-control-plane/envoy/extensions/upstreams/http/v3"
	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	"github.com/joysafeter/joysafeter/egress-controller/internal/policy"
	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const (
	credentialRoutesName  = "joysafeter_credential_routes"
	forwardRoutesName     = "joysafeter_forward_proxy_routes"
	dynamicForwardCluster = "joysafeter_dynamic_forward_proxy"
)

type Compiler struct {
	config Config
}

func New(config Config) (*Compiler, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	return &Compiler{config: config}, nil
}

func (c *Compiler) Compile(_ context.Context, desired source.DesiredGeneration) (snapshot.Compiled, error) {
	policies, err := policy.Decode(desired.PolicySchemaVersion, desired.DesiredPolicies)
	if err != nil {
		return snapshot.Compiled{}, err
	}
	deniedRanges, err := c.deniedRanges(policies)
	if err != nil {
		return snapshot.Compiled{}, err
	}
	clusters, err := c.buildClusters(policies, deniedRanges)
	if err != nil {
		return snapshot.Compiled{}, err
	}
	var routes, listeners []cachetypes.Resource
	switch desired.NodeSelector.Provider {
	case "k8s", "kubernetes":
		routes, listeners, err = c.buildKubernetesResources(policies, deniedRanges, desired.GroupKey, desired.Generation)
	case "docker":
		routes, listeners, err = c.buildDockerResources(policies, deniedRanges, desired.GroupKey, desired.Generation)
	default:
		return snapshot.Compiled{}, fmt.Errorf("unsupported egress provider %q", desired.NodeSelector.Provider)
	}
	if err != nil {
		return snapshot.Compiled{}, err
	}
	return snapshot.BuildCompiled(desired.GroupKey, desired.Generation, clusters, routes, listeners)
}

func (c *Compiler) deniedRanges(policies []policy.SandboxPolicy) ([]map[string]any, error) {
	values := make(map[string]netip.Prefix)
	for _, raw := range c.config.DeniedCIDRs {
		prefix, err := netip.ParsePrefix(strings.TrimSpace(raw))
		if err != nil {
			return nil, fmt.Errorf("invalid compiler denied CIDR %q: %w", raw, err)
		}
		values[prefix.Masked().String()] = prefix.Masked()
	}
	for _, sandboxPolicy := range policies {
		for _, raw := range sandboxPolicy.DeniedCIDRs {
			prefix, err := netip.ParsePrefix(raw)
			if err != nil {
				return nil, err
			}
			values[prefix.Masked().String()] = prefix.Masked()
		}
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	ranges := make([]map[string]any, 0, len(keys))
	for _, key := range keys {
		prefix := values[key]
		ranges = append(ranges, map[string]any{
			"address_prefix": prefix.Addr().String(),
			"prefix_len":     prefix.Bits(),
		})
	}
	return ranges, nil
}

func (c *Compiler) buildClusters(policies []policy.SandboxPolicy, deniedRanges []map[string]any) ([]cachetypes.Resource, error) {
	documents := []map[string]any{c.authzCluster(), dynamicForwardProxyCluster(deniedRanges)}
	seen := make(map[string]struct{})
	for _, sandboxPolicy := range policies {
		for _, route := range sandboxPolicy.CredentialRoutes {
			name := upstreamClusterName(route.Upstream)
			if _, exists := seen[name]; exists {
				continue
			}
			seen[name] = struct{}{}
			documents = append(documents, c.upstreamCluster(name, route.Upstream))
		}
	}
	sort.Slice(documents[2:], func(i, j int) bool {
		return documents[i+2]["name"].(string) < documents[j+2]["name"].(string)
	})
	return decodeDocuments(documents, func() proto.Message { return &clusterv3.Cluster{} })
}

func (c *Compiler) buildKubernetesResources(policies []policy.SandboxPolicy, deniedRanges []map[string]any, groupKey string, generation uint64) ([]cachetypes.Resource, []cachetypes.Resource, error) {
	credentialRoutes := buildKubernetesCredentialRoutes(policies, groupKey, generation)
	forwardRoutes := buildKubernetesForwardRoutes(c.config.AuthzCluster)
	routes, err := decodeDocuments([]map[string]any{credentialRoutes, forwardRoutes}, func() proto.Message { return &routev3.RouteConfiguration{} })
	if err != nil {
		return nil, nil, err
	}
	credentialListener := c.socketListener(
		"joysafeter_credential_listener", c.config.CredentialAddress, c.config.CredentialPort,
		credentialRoutesName, credentialHTTPFilters(c.config.AuthzCluster), false, true, deniedRanges,
	)
	forwardListener := c.socketListener(
		"joysafeter_forward_proxy_listener", c.config.ForwardAddress, c.config.ForwardPort,
		forwardRoutesName, forwardHTTPFilters(c.config.AuthzCluster, deniedRanges), true, true, deniedRanges,
	)
	listeners, err := decodeDocuments([]map[string]any{credentialListener, forwardListener}, func() proto.Message { return &listenerv3.Listener{} })
	return routes, listeners, err
}

const controlRoutesPrefix = "joysafeter_control_"

// grpcControlListener is the per-sandbox AgentBridge control channel: an HTTP/2
// pipe listener forwarding to the orchestrator. It is NOT external egress, so it
// carries no ext_authz filter — only the router. Emitting it here (alongside the
// http.sock egress listener) keeps Envoy's ADS the single config source for
// Docker sandboxes.
func (c *Compiler) grpcControlListener(sandboxID string) map[string]any {
	name := "joysafeter_" + strings.ReplaceAll(sandboxID, "-", "_") + "_grpc"
	routeName := controlRoutesPrefix + strings.ReplaceAll(sandboxID, "-", "_")
	return c.pipeListener(name, path.Join(c.config.SocketRoot, sandboxID, "grpc.sock"),
		routeName, []any{routerFilter()})
}

// dockerControlRoutes routes the control-channel listener to the static
// orchestrator_grpc bootstrap cluster (the AgentBridge upstream). No credential
// injection, no ext_authz.
func (c *Compiler) dockerControlRoutes(sandboxID string) map[string]any {
	cluster := c.config.OrchestratorGrpcCluster
	if cluster == "" {
		cluster = "orchestrator_grpc"
	}
	routeName := controlRoutesPrefix + strings.ReplaceAll(sandboxID, "-", "_")
	return map[string]any{
		"name": routeName,
		"virtual_hosts": []any{map[string]any{
			"name": "control", "domains": []any{"*"}, "routes": []any{
				map[string]any{
					"name":  "control_grpc",
					"match": map[string]any{"prefix": "/"},
					"route": map[string]any{"cluster": cluster, "timeout": "0s"},
				},
			},
		}},
	}
}

func (c *Compiler) buildDockerResources(policies []policy.SandboxPolicy, deniedRanges []map[string]any, groupKey string, generation uint64) ([]cachetypes.Resource, []cachetypes.Resource, error) {
	routeDocuments := make([]map[string]any, 0, len(policies)*2)
	listenerDocuments := make([]map[string]any, 0, len(policies)*2)
	for _, sandboxPolicy := range policies {
		routeName := "joysafeter_routes_" + strings.ReplaceAll(sandboxPolicy.SandboxID, "-", "_")
		routeDocuments = append(routeDocuments, buildDockerRoutes(routeName, sandboxPolicy, groupKey, generation))
		listenerDocuments = append(listenerDocuments, c.pipeListener(
			"joysafeter_"+strings.ReplaceAll(sandboxPolicy.SandboxID, "-", "_")+"_http",
			path.Join(c.config.SocketRoot, sandboxPolicy.SandboxID, "http.sock"), routeName,
			forwardHTTPFilters(c.config.AuthzCluster, deniedRanges),
		))
		// AgentBridge control channel (grpc.sock) — no ext_authz, routes to the orchestrator.
		routeDocuments = append(routeDocuments, c.dockerControlRoutes(sandboxPolicy.SandboxID))
		listenerDocuments = append(listenerDocuments, c.grpcControlListener(sandboxPolicy.SandboxID))
	}
	routes, err := decodeDocuments(routeDocuments, func() proto.Message { return &routev3.RouteConfiguration{} })
	if err != nil {
		return nil, nil, err
	}
	listeners, err := decodeDocuments(listenerDocuments, func() proto.Message { return &listenerv3.Listener{} })
	return routes, listeners, err
}

func decodeDocuments(documents []map[string]any, newMessage func() proto.Message) ([]cachetypes.Resource, error) {
	resources := make([]cachetypes.Resource, 0, len(documents))
	unmarshal := protojson.UnmarshalOptions{DiscardUnknown: false}
	for index, document := range documents {
		raw, err := json.Marshal(document)
		if err != nil {
			return nil, err
		}
		message := newMessage()
		if err := unmarshal.Unmarshal(raw, message); err != nil {
			return nil, fmt.Errorf("decode rendered xDS resource %d: %w", index, err)
		}
		resource, ok := message.(cachetypes.Resource)
		if !ok {
			return nil, errors.New("rendered protobuf is not an xDS resource")
		}
		resources = append(resources, resource)
	}
	return resources, nil
}

func upstreamClusterName(upstream policy.Upstream) string {
	digest := sha256.Sum256([]byte(strings.Join([]string{
		upstream.Scheme, upstream.Host, strconv.Itoa(int(upstream.Port)), upstream.Protocol,
	}, "\x00")))
	return "joysafeter_up_" + hex.EncodeToString(digest[:10])
}

func syntheticRouteBase(sandboxID, routeID string) string {
	segment := base64.RawURLEncoding.EncodeToString([]byte(routeID))
	return "/v1/sandbox/" + sandboxID + "/route/" + segment
}
