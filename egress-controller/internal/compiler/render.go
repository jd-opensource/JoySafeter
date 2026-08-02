package compiler

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/joysafeter/joysafeter/egress-controller/internal/policy"
)

func (c *Compiler) authzCluster() map[string]any {
	cluster := strictDNSCluster(c.config.AuthzCluster, c.config.AuthzHost, c.config.AuthzPort, "http2")
	if c.config.AuthzTLS {
		cluster["transport_socket"] = map[string]any{
			"name": "envoy.transport_sockets.tls",
			"typed_config": map[string]any{
				"@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
				"sni":   c.config.AuthzServerName,
				"common_tls_context": map[string]any{
					"tls_certificates": []any{map[string]any{
						"certificate_chain": map[string]any{"filename": c.config.AuthzClientCert},
						"private_key":       map[string]any{"filename": c.config.AuthzClientKey},
					}},
					"validation_context": validationContext(c.config.AuthzCA, c.config.AuthzServerName),
				},
			},
		}
	}
	return cluster
}

func (c *Compiler) upstreamCluster(name string, upstream policy.Upstream) map[string]any {
	// ALPN-based auto protocol negotiation ("auto_config") requires a TLS
	// transport socket. A plaintext (non-https) upstream has none, so Envoy
	// NACKs "ALPN configured for cluster ... non-ALPN transport socket". Fall
	// back to explicit HTTP/1.1 for plaintext auto; https keeps ALPN auto.
	protocol := upstream.Protocol
	if protocol == "auto" && upstream.Scheme != "https" {
		protocol = "http1"
	}
	cluster := strictDNSCluster(name, upstream.Host, uint32(upstream.Port), protocol)
	if upstream.Scheme == "https" {
		cluster["transport_socket"] = map[string]any{
			"name": "envoy.transport_sockets.tls",
			"typed_config": map[string]any{
				"@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
				"sni":   upstream.Host,
				"common_tls_context": map[string]any{
					"validation_context": validationContext(c.config.PublicCA, upstream.Host),
				},
			},
		}
	}
	return cluster
}

func strictDNSCluster(name, host string, port uint32, protocol string) map[string]any {
	cluster := map[string]any{
		"name": name, "connect_timeout": "5s", "type": "STRICT_DNS", "lb_policy": "ROUND_ROBIN",
		"dns_lookup_family": "V4_PREFERRED",
		"load_assignment": map[string]any{
			"cluster_name": name,
			"endpoints": []any{map[string]any{"lb_endpoints": []any{map[string]any{
				"endpoint": map[string]any{"address": map[string]any{"socket_address": map[string]any{
					"address": host, "port_value": port,
				}}},
			}}}},
		},
		"circuit_breakers": map[string]any{"thresholds": []any{map[string]any{
			"priority": "DEFAULT", "max_connections": 1024, "max_pending_requests": 1024,
			"max_requests": 4096, "max_retries": 3,
		}}},
		"outlier_detection": map[string]any{
			"consecutive_5xx": 5, "interval": "10s", "base_ejection_time": "30s", "max_ejection_percent": 50,
		},
	}
	if protocol == "http2" {
		cluster["typed_extension_protocol_options"] = httpProtocolOptions("http2")
	} else if protocol == "auto" {
		cluster["typed_extension_protocol_options"] = httpProtocolOptions("auto")
	}
	return cluster
}

func httpProtocolOptions(mode string) map[string]any {
	config := map[string]any{
		"@type": "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
	}
	if mode == "http2" {
		config["explicit_http_config"] = map[string]any{"http2_protocol_options": map[string]any{}}
	} else {
		config["auto_config"] = map[string]any{}
	}
	return map[string]any{"envoy.extensions.upstreams.http.v3.HttpProtocolOptions": config}
}

func validationContext(caPath, serverName string) map[string]any {
	return map[string]any{
		"trusted_ca": map[string]any{"filename": caPath},
		"match_typed_subject_alt_names": []any{map[string]any{
			"san_type": "DNS", "matcher": map[string]any{"exact": serverName},
		}},
	}
}

func dynamicForwardProxyCluster(deniedRanges []map[string]any) map[string]any {
	return map[string]any{
		"name": dynamicForwardCluster, "connect_timeout": "5s", "lb_policy": "CLUSTER_PROVIDED",
		"cluster_type": map[string]any{
			"name": "envoy.clusters.dynamic_forward_proxy",
			"typed_config": map[string]any{
				"@type":            "type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig",
				"dns_cache_config": dnsCacheConfig(deniedRanges),
			},
		},
		"circuit_breakers": map[string]any{"thresholds": []any{map[string]any{
			"priority": "DEFAULT", "max_connections": 4096, "max_pending_requests": 2048,
			"max_requests": 8192, "max_retries": 1,
		}}},
	}
}

func dnsCacheConfig(deniedRanges []map[string]any) map[string]any {
	return map[string]any{
		"name": "joysafeter_dynamic_forward_proxy_cache", "dns_lookup_family": "V4_PREFERRED",
		"dns_refresh_rate": "30s", "dns_failure_refresh_rate": map[string]any{"base_interval": "2s", "max_interval": "10s"},
		"host_ttl": "300s", "max_hosts": 8192,
		"resolved_address_filter": map[string]any{"ranges": deniedRanges},
	}
}

func credentialHTTPFilters(authzCluster string) []any {
	return []any{extAuthzFilter(authzCluster), routerFilter()}
}

func forwardHTTPFilters(authzCluster string, deniedRanges []map[string]any) []any {
	return []any{
		extAuthzFilter(authzCluster),
		map[string]any{
			"name": "envoy.filters.http.dynamic_forward_proxy",
			"typed_config": map[string]any{
				"@type":            "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
				"dns_cache_config": dnsCacheConfig(deniedRanges),
			},
		},
		routerFilter(),
	}
}

func extAuthzFilter(cluster string) map[string]any {
	return map[string]any{
		"name": "envoy.filters.http.ext_authz",
		"typed_config": map[string]any{
			"@type":                 "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz",
			"transport_api_version": "V3", "failure_mode_allow": false,
			"grpc_service": map[string]any{
				"envoy_grpc": map[string]any{"cluster_name": cluster},
				"timeout":    "2s",
			},
		},
	}
}

func routerFilter() map[string]any {
	return map[string]any{
		"name":         "envoy.filters.http.router",
		"typed_config": map[string]any{"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"},
	}
}

func (c *Compiler) socketListener(name, address string, port uint32, routeName string, filters []any, allowConnect, downstreamTLS bool, _ []map[string]any) map[string]any {
	listener := listenerBase(name, map[string]any{"socket_address": map[string]any{
		"address": address, "port_value": port,
	}}, routeName, filters, allowConnect)
	if downstreamTLS && c.config.DownstreamTLS {
		filterChain := listener["filter_chains"].([]any)[0].(map[string]any)
		filterChain["transport_socket"] = map[string]any{
			"name": "envoy.transport_sockets.tls",
			"typed_config": map[string]any{
				"@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext",
				"common_tls_context": map[string]any{
					"tls_params": map[string]any{"tls_minimum_protocol_version": "TLSv1_2"},
					"tls_certificates": []any{map[string]any{
						"certificate_chain": map[string]any{"filename": c.config.DownstreamCert},
						"private_key":       map[string]any{"filename": c.config.DownstreamKey},
					}},
				},
			},
		}
	}
	return listener
}

func (c *Compiler) pipeListener(name, socketPath, routeName string, filters []any) map[string]any {
	return listenerBase(name, map[string]any{"pipe": map[string]any{"path": socketPath, "mode": 438}}, routeName, filters, true)
}

func listenerBase(name string, address map[string]any, routeName string, filters []any, allowConnect bool) map[string]any {
	hcm := map[string]any{
		"@type":       "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
		"stat_prefix": name, "stream_idle_timeout": "0s", "request_timeout": "0s",
		"use_remote_address":           true,
		"common_http_protocol_options": map[string]any{"idle_timeout": "300s", "max_headers_count": 100},
		"http_protocol_options":        map[string]any{"allow_absolute_url": true},
		"rds": map[string]any{
			"route_config_name": routeName,
			"config_source":     map[string]any{"ads": map[string]any{}, "resource_api_version": "V3"},
		},
		"http_filters": filters,
	}
	if allowConnect {
		hcm["upgrade_configs"] = []any{
			map[string]any{"upgrade_type": "CONNECT"}, map[string]any{"upgrade_type": "websocket"},
		}
	} else {
		hcm["upgrade_configs"] = []any{map[string]any{"upgrade_type": "websocket"}}
	}
	return map[string]any{
		"name": name, "address": address,
		"per_connection_buffer_limit_bytes": 1 << 20,
		"filter_chains": []any{map[string]any{"filters": []any{map[string]any{
			"name": "envoy.filters.network.http_connection_manager", "typed_config": hcm,
		}}}},
	}
}

func buildKubernetesCredentialRoutes(policies []policy.SandboxPolicy, groupKey string, generation uint64) map[string]any {
	routes := make([]map[string]any, 0)
	for _, sandboxPolicy := range policies {
		for _, route := range sandboxPolicy.CredentialRoutes {
			base := syntheticRouteBase(sandboxPolicy.SandboxID, route.ConsumerRouteID)
			matchPath := joinRoutePath(base, route.MatchPath.Value)
			for _, method := range route.Methods {
				routes = append(routes, credentialRoute(sandboxPolicy.SandboxID, route, matchPath, method, groupKey, generation))
			}
		}
	}
	sort.Slice(routes, func(i, j int) bool {
		iMatch := routes[i]["match"].(map[string]any)
		jMatch := routes[j]["match"].(map[string]any)
		iPath := routeMatchPath(iMatch)
		jPath := routeMatchPath(jMatch)
		if len(iPath) != len(jPath) {
			return len(iPath) > len(jPath)
		}
		return routes[i]["name"].(string) < routes[j]["name"].(string)
	})
	routeValues := make([]any, 0, len(routes)+1)
	for _, route := range routes {
		routeValues = append(routeValues, route)
	}
	routeValues = append(routeValues, denyRoute("credential route not found"))
	return map[string]any{
		"name":          credentialRoutesName,
		"virtual_hosts": []any{map[string]any{"name": "credential", "domains": []any{"*"}, "routes": routeValues}},
	}
}

func credentialRoute(sandboxID string, route policy.CredentialRoute, matchPath, method, groupKey string, generation uint64) map[string]any {
	match := map[string]any{
		"headers": []any{map[string]any{"name": ":method", "string_match": map[string]any{"exact": method}}},
	}
	if route.MatchPath.Kind == "exact" {
		match["path"] = matchPath
	} else {
		match["prefix"] = matchPath
	}
	action := map[string]any{
		"cluster": upstreamClusterName(route.Upstream), "host_rewrite_literal": route.Upstream.Host,
		"timeout": timeoutFor(route.TimeoutProfile),
	}
	if route.MatchPath.Kind != "exact" {
		action["prefix_rewrite"] = route.Upstream.BasePath
	} else {
		action["regex_rewrite"] = map[string]any{
			"pattern":      map[string]any{"regex": "^" + regexp.QuoteMeta(matchPath) + "$"},
			"substitution": route.Upstream.BasePath,
		}
	}
	if route.Websocket {
		action["upgrade_configs"] = []any{map[string]any{"upgrade_type": "websocket", "enabled": true}}
	}
	return map[string]any{
		"name":  "credential_" + strings.ReplaceAll(sandboxID, "-", "_") + "_" + safeName(route.RouteID) + "_" + strings.ToLower(method),
		"match": match, "route": action,
		// Strip every sandbox-supplied credential header EXCEPT the ext_authz
		// inject header: ext_authz overwrites that one with the platform
		// credential, and route-level removal runs in the router AFTER ext_authz,
		// so listing it here would strip the injected credential before it
		// reaches the upstream.
		"request_headers_to_remove": sensitiveHeadersExcept(route.RemoveHeaders, route.InjectHeader),
		"typed_per_filter_config": extAuthzContext(map[string]string{
			"joysafeter_traffic_class": "credential", "joysafeter_sandbox_id": sandboxID, "joysafeter_route_id": route.RouteID,
			"joysafeter_group_key": groupKey, "joysafeter_policy_generation": strconv.FormatUint(generation, 10),
		}),
	}
}

func buildKubernetesForwardRoutes(_ string) map[string]any {
	context := extAuthzContext(map[string]string{"joysafeter_traffic_class": "forward_proxy"})
	return map[string]any{
		"name": forwardRoutesName,
		"virtual_hosts": []any{map[string]any{
			"name": "forward_proxy", "domains": []any{"*"}, "routes": []any{
				map[string]any{
					"name": "forward_connect", "match": map[string]any{"connect_matcher": map[string]any{}},
					"route": map[string]any{
						"cluster":         dynamicForwardCluster,
						"upgrade_configs": []any{map[string]any{"upgrade_type": "CONNECT", "connect_config": map[string]any{}}},
					},
					"request_headers_to_remove": []any{"proxy-authorization", "x-joysafeter-sandbox-id", "x-joysafeter-route-id"},
					"typed_per_filter_config":   context,
				},
				map[string]any{
					"name": "forward_http", "match": map[string]any{"prefix": "/"},
					"route":                     map[string]any{"cluster": dynamicForwardCluster, "timeout": "0s"},
					"request_headers_to_remove": []any{"proxy-authorization", "x-joysafeter-sandbox-id", "x-joysafeter-route-id"},
					"typed_per_filter_config":   context,
				},
			},
		}},
	}
}

func buildDockerRoutes(name string, sandboxPolicy policy.SandboxPolicy, groupKey string, generation uint64) map[string]any {
	byHost := make(map[string][]policy.CredentialRoute)
	for _, route := range sandboxPolicy.CredentialRoutes {
		byHost[route.MatchAuthority] = append(byHost[route.MatchAuthority], route)
	}
	hosts := make([]string, 0, len(byHost))
	for host := range byHost {
		hosts = append(hosts, host)
	}
	sort.Strings(hosts)
	vhosts := make([]any, 0, len(hosts)+2)
	allowed := make(map[string]struct{}, len(sandboxPolicy.AllowedPublicHosts))
	for _, host := range sandboxPolicy.AllowedPublicHosts {
		allowed[host] = struct{}{}
	}
	for _, host := range hosts {
		routes := byHost[host]
		sort.Slice(routes, func(i, j int) bool {
			if len(routes[i].MatchPath.Value) != len(routes[j].MatchPath.Value) {
				return len(routes[i].MatchPath.Value) > len(routes[j].MatchPath.Value)
			}
			return routes[i].RouteID < routes[j].RouteID
		})
		routeValues := make([]any, 0)
		for _, route := range routes {
			for _, method := range route.Methods {
				routeValues = append(routeValues, credentialRoute(sandboxPolicy.SandboxID, route, route.MatchPath.Value, method, groupKey, generation))
			}
		}
		if sandboxPolicy.Mode == "unrestricted" || hostAllowed(host, allowed) {
			routeValues = append(routeValues, plainForwardRoutes(true)...)
		} else {
			routeValues = append(routeValues, denyRoute("path not authorized"))
		}
		vhosts = append(vhosts, map[string]any{
			"name": "credential_" + safeName(host), "domains": hostDomains(host), "routes": routeValues,
		})
	}
	if sandboxPolicy.Mode == "limited" && len(sandboxPolicy.AllowedPublicHosts) > 0 {
		domains := make([]any, 0)
		for _, host := range sandboxPolicy.AllowedPublicHosts {
			domains = append(domains, host)
			if !strings.HasPrefix(host, "*.") {
				domains = append(domains, host+":80", host+":443")
			}
		}
		vhosts = append(vhosts, map[string]any{
			"name": "allowed", "domains": domains, "routes": plainForwardRoutes(true),
			"typed_per_filter_config": extAuthzDisabled(),
		})
	}
	if sandboxPolicy.Mode == "unrestricted" {
		vhosts = append(vhosts, map[string]any{
			"name": "unrestricted", "domains": []any{"*"}, "routes": plainForwardRoutes(true),
			"typed_per_filter_config": extAuthzDisabled(),
		})
	} else {
		vhosts = append(vhosts, map[string]any{
			"name": "deny_all", "domains": []any{"*"}, "routes": []any{denyRoute("host not authorized")},
			"typed_per_filter_config": extAuthzDisabled(),
		})
	}
	return map[string]any{"name": name, "virtual_hosts": vhosts}
}

func plainForwardRoutes(disableAuthz bool) []any {
	routes := []any{
		map[string]any{
			"name": "connect", "match": map[string]any{"connect_matcher": map[string]any{}},
			"route": map[string]any{
				"cluster":         dynamicForwardCluster,
				"upgrade_configs": []any{map[string]any{"upgrade_type": "CONNECT", "connect_config": map[string]any{}}},
			},
		},
		map[string]any{"name": "http", "match": map[string]any{"prefix": "/"}, "route": map[string]any{"cluster": dynamicForwardCluster, "timeout": "0s"}},
	}
	if disableAuthz {
		for _, value := range routes {
			value.(map[string]any)["typed_per_filter_config"] = extAuthzDisabled()
		}
	}
	return routes
}

func extAuthzContext(context map[string]string) map[string]any {
	return map[string]any{"envoy.filters.http.ext_authz": map[string]any{
		"@type":          "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
		"check_settings": map[string]any{"context_extensions": context},
	}}
}

func extAuthzDisabled() map[string]any {
	return map[string]any{"envoy.filters.http.ext_authz": map[string]any{
		"@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute", "disabled": true,
	}}
}

func denyRoute(message string) map[string]any {
	return map[string]any{
		"name": "deny", "match": map[string]any{"prefix": "/"},
		"direct_response":         map[string]any{"status": 403, "body": map[string]any{"inline_string": message}},
		"typed_per_filter_config": extAuthzDisabled(),
	}
}

func sensitiveHeaders(configured []string) []any {
	values := map[string]struct{}{
		"authorization": {}, "x-api-key": {}, "api-key": {}, "x-goog-api-key": {}, "proxy-authorization": {},
		"x-joysafeter-sandbox-id": {}, "x-joysafeter-route-id": {},
	}
	for _, header := range configured {
		values[header] = struct{}{}
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	result := make([]any, 0, len(keys))
	for _, key := range keys {
		result = append(result, key)
	}
	return result
}

// sensitiveHeadersExcept is sensitiveHeaders minus one header (the ext_authz
// inject header, which ext_authz overwrites and must survive to the upstream).
func sensitiveHeadersExcept(configured []string, keep string) []any {
	keep = strings.ToLower(strings.TrimSpace(keep))
	all := sensitiveHeaders(configured)
	if keep == "" {
		return all
	}
	result := make([]any, 0, len(all))
	for _, h := range all {
		if s, ok := h.(string); ok && s == keep {
			continue
		}
		result = append(result, h)
	}
	return result
}

func timeoutFor(profile string) string {
	switch profile {
	case "streaming":
		return "0s"
	case "long_running":
		return "300s"
	default:
		return "30s"
	}
}

func joinRoutePath(base, suffix string) string {
	if suffix == "/" {
		return base + "/"
	}
	return strings.TrimSuffix(base, "/") + "/" + strings.TrimPrefix(suffix, "/")
}

func routeMatchPath(match map[string]any) string {
	if value, ok := match["path"].(string); ok {
		return value
	}
	return match["prefix"].(string)
}

func hostDomains(host string) []any {
	return []any{host, host + ":80", host + ":443"}
}

func hostAllowed(host string, allowed map[string]struct{}) bool {
	if _, ok := allowed[host]; ok {
		return true
	}
	for pattern := range allowed {
		if strings.HasPrefix(pattern, "*.") && strings.HasSuffix(host, strings.TrimPrefix(pattern, "*")) {
			return true
		}
	}
	return false
}

func safeName(value string) string {
	var builder strings.Builder
	for _, character := range strings.ToLower(value) {
		if character >= 'a' && character <= 'z' || character >= '0' && character <= '9' || character == '_' || character == '-' {
			builder.WriteRune(character)
		} else {
			builder.WriteByte('_')
		}
	}
	if builder.Len() == 0 {
		return "resource"
	}
	return fmt.Sprintf("%.128s", builder.String())
}
