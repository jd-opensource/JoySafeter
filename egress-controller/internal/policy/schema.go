package policy

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"net/url"
	"regexp"
	"sort"
	"strings"

	"github.com/google/uuid"
	"golang.org/x/net/idna"
)

const (
	SchemaVersion       = 1
	maxPoliciesPerGroup = 10_000
	maxRoutesPerPolicy  = 128
	maxHostsPerPolicy   = 256
	maxDeniedCIDRs      = 128
)

var (
	routeIDPattern       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)
	headerPattern        = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,126}$`)
	allowedInjectHeaders = map[string]struct{}{
		"authorization": {}, "x-api-key": {}, "api-key": {}, "x-goog-api-key": {}, "cookie": {},
	}
	forbiddenHeaders = map[string]struct{}{
		"connection": {}, "content-length": {}, "forwarded": {}, "host": {}, "keep-alive": {},
		"proxy-authenticate": {}, "proxy-authorization": {}, "te": {}, "trailer": {},
		"transfer-encoding": {}, "upgrade": {}, "via": {}, "x-forwarded-for": {},
		"x-forwarded-host": {}, "x-forwarded-proto": {}, "x-joysafeter-sandbox-id": {},
		"x-joysafeter-route-id": {},
	}
)

type SandboxPolicy struct {
	SandboxID          string            `json:"sandbox_id"`
	ProjectID          *string           `json:"project_id,omitempty"`
	Mode               string            `json:"mode"`
	CredentialRoutes   []CredentialRoute `json:"credential_routes"`
	AllowedPublicHosts []string          `json:"allowed_public_hosts"`
	DeniedCIDRs        []string          `json:"denied_cidrs"`
}

type CredentialRoute struct {
	RouteID         string        `json:"route_id"`
	ConsumerRouteID string        `json:"consumer_route_id,omitempty"`
	Kind            string        `json:"kind"`
	MatchAuthority  string        `json:"match_authority"`
	MatchPath       PathMatch     `json:"match_path"`
	Methods         []string      `json:"methods"`
	Upstream        Upstream      `json:"upstream"`
	CredentialRef   CredentialRef `json:"credential_ref"`
	InjectHeader    string        `json:"inject_header"`
	InjectScheme    InjectScheme  `json:"inject_scheme"`
	RemoveHeaders   []string      `json:"remove_headers"`
	TimeoutProfile  string        `json:"timeout_profile"`
	Websocket       bool          `json:"websocket"`
}

type PathMatch struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}

type Upstream struct {
	Scheme   string `json:"scheme"`
	Host     string `json:"host"`
	Port     uint16 `json:"port"`
	BasePath string `json:"base_path"`
	Protocol string `json:"protocol"`
}

type CredentialRef struct {
	Kind         string  `json:"kind"`
	SecretName   *string `json:"secret_name,omitempty"`
	SecretKey    *string `json:"secret_key,omitempty"`
	ProjectID    *string `json:"project_id,omitempty"`
	VaultID      *string `json:"vault_id,omitempty"`
	MCPServerURL *string `json:"mcp_server_url,omitempty"`
	SessionID    *string `json:"session_id,omitempty"`
	MountName    *string `json:"mount_name,omitempty"`
}

type InjectScheme struct {
	Kind     string  `json:"kind"`
	Username *string `json:"username,omitempty"`
}

func Decode(schemaVersion int, raw []byte) ([]SandboxPolicy, error) {
	if schemaVersion != SchemaVersion {
		return nil, fmt.Errorf("unsupported egress policy schema version %d", schemaVersion)
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var policies []SandboxPolicy
	if err := decoder.Decode(&policies); err != nil {
		return nil, fmt.Errorf("decode egress policies: %w", err)
	}
	if err := ensureEOF(decoder); err != nil {
		return nil, err
	}
	if len(policies) > maxPoliciesPerGroup {
		return nil, fmt.Errorf("egress policy group exceeds %d sandboxes", maxPoliciesPerGroup)
	}
	seenSandboxes := make(map[string]struct{}, len(policies))
	for index := range policies {
		if err := policies[index].normalizeAndValidate(); err != nil {
			return nil, fmt.Errorf("policy %d: %w", index, err)
		}
		if _, exists := seenSandboxes[policies[index].SandboxID]; exists {
			return nil, fmt.Errorf("duplicate sandbox_id %q", policies[index].SandboxID)
		}
		seenSandboxes[policies[index].SandboxID] = struct{}{}
	}
	sort.Slice(policies, func(i, j int) bool { return policies[i].SandboxID < policies[j].SandboxID })
	return policies, nil
}

func (p *SandboxPolicy) normalizeAndValidate() error {
	sandboxID, err := normalizeUUID(p.SandboxID)
	if err != nil {
		return fmt.Errorf("sandbox_id: %w", err)
	}
	p.SandboxID = sandboxID
	if p.ProjectID != nil {
		projectID, err := normalizeUUID(*p.ProjectID)
		if err != nil {
			return fmt.Errorf("project_id: %w", err)
		}
		p.ProjectID = &projectID
	}
	p.Mode = strings.ToLower(strings.TrimSpace(p.Mode))
	if p.Mode != "limited" && p.Mode != "unrestricted" {
		return errors.New("mode must be limited or unrestricted")
	}
	if len(p.CredentialRoutes) > maxRoutesPerPolicy {
		return fmt.Errorf("credential routes exceed %d", maxRoutesPerPolicy)
	}
	if len(p.AllowedPublicHosts) > maxHostsPerPolicy {
		return fmt.Errorf("allowed public hosts exceed %d", maxHostsPerPolicy)
	}
	if len(p.DeniedCIDRs) > maxDeniedCIDRs {
		return fmt.Errorf("denied CIDRs exceed %d", maxDeniedCIDRs)
	}
	seenRoutes := make(map[string]struct{}, len(p.CredentialRoutes))
	seenConsumerMatches := make(map[string]string)
	for index := range p.CredentialRoutes {
		route := &p.CredentialRoutes[index]
		if err := route.normalizeAndValidate(); err != nil {
			return fmt.Errorf("credential route %d: %w", index, err)
		}
		if _, exists := seenRoutes[route.RouteID]; exists {
			return fmt.Errorf("duplicate route_id %q", route.RouteID)
		}
		seenRoutes[route.RouteID] = struct{}{}
		for _, method := range route.Methods {
			key := strings.Join([]string{route.ConsumerRouteID, route.MatchPath.Value, method}, "\x00")
			if existing, exists := seenConsumerMatches[key]; exists {
				return fmt.Errorf(
					"consumer_route_id %q has duplicate path/method match in routes %q and %q",
					route.ConsumerRouteID, existing, route.RouteID,
				)
			}
			seenConsumerMatches[key] = route.RouteID
		}
	}
	sort.Slice(p.CredentialRoutes, func(i, j int) bool { return p.CredentialRoutes[i].RouteID < p.CredentialRoutes[j].RouteID })

	hosts := make(map[string]struct{}, len(p.AllowedPublicHosts))
	for _, host := range p.AllowedPublicHosts {
		normalized, err := normalizeHostPattern(host)
		if err != nil {
			return fmt.Errorf("allowed host %q: %w", host, err)
		}
		hosts[normalized] = struct{}{}
	}
	p.AllowedPublicHosts = sortedKeys(hosts)

	prefixes := make(map[string]struct{}, len(p.DeniedCIDRs))
	for _, rawPrefix := range p.DeniedCIDRs {
		prefix, err := netip.ParsePrefix(strings.TrimSpace(rawPrefix))
		if err != nil {
			return fmt.Errorf("denied CIDR %q: %w", rawPrefix, err)
		}
		prefixes[prefix.Masked().String()] = struct{}{}
	}
	p.DeniedCIDRs = sortedKeys(prefixes)
	return nil
}

func (r *CredentialRoute) normalizeAndValidate() error {
	r.RouteID = strings.TrimSpace(r.RouteID)
	if !routeIDPattern.MatchString(r.RouteID) {
		return errors.New("route_id has invalid format")
	}
	r.ConsumerRouteID = strings.TrimSpace(r.ConsumerRouteID)
	if r.ConsumerRouteID == "" {
		r.ConsumerRouteID = r.RouteID
	}
	if !routeIDPattern.MatchString(r.ConsumerRouteID) {
		return errors.New("consumer_route_id has invalid format")
	}
	r.Kind = strings.ToLower(strings.TrimSpace(r.Kind))
	switch r.Kind {
	case "llm", "mcp", "git", "external":
	default:
		return fmt.Errorf("unsupported route kind %q", r.Kind)
	}
	if r.ConsumerRouteID != r.RouteID && r.Kind != "external" {
		return errors.New("shared consumer_route_id is supported only for external routes")
	}
	matchAuthority, err := normalizeDNSHost(r.MatchAuthority)
	if err != nil {
		return fmt.Errorf("match_authority: %w", err)
	}
	r.MatchAuthority = matchAuthority
	r.MatchPath.Kind = strings.ToLower(strings.TrimSpace(r.MatchPath.Kind))
	if r.MatchPath.Kind != "prefix" && r.MatchPath.Kind != "exact" {
		return errors.New("match_path.kind must be prefix or exact")
	}
	r.MatchPath.Value, err = normalizePath(r.MatchPath.Value)
	if err != nil {
		return fmt.Errorf("match_path.value: %w", err)
	}
	if len(r.Methods) == 0 || len(r.Methods) > 8 {
		return errors.New("methods must contain 1 to 8 entries")
	}
	methodSet := make(map[string]struct{}, len(r.Methods))
	for _, method := range r.Methods {
		method = strings.ToUpper(strings.TrimSpace(method))
		switch method {
		case "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS":
			methodSet[method] = struct{}{}
		default:
			return fmt.Errorf("unsupported HTTP method %q", method)
		}
	}
	r.Methods = sortedKeys(methodSet)
	if err := r.Upstream.normalizeAndValidate(); err != nil {
		return err
	}
	if err := r.CredentialRef.normalizeAndValidate(); err != nil {
		return err
	}
	if r.CredentialRef.Kind != r.Kind {
		return fmt.Errorf("credential_ref.kind %q does not match route kind %q", r.CredentialRef.Kind, r.Kind)
	}
	r.InjectHeader = strings.ToLower(strings.TrimSpace(r.InjectHeader))
	if _, ok := allowedInjectHeaders[r.InjectHeader]; !ok {
		return fmt.Errorf("inject_header %q is not allowed", r.InjectHeader)
	}
	if err := r.InjectScheme.normalizeAndValidate(); err != nil {
		return err
	}
	removeHeaders := make(map[string]struct{}, len(r.RemoveHeaders)+1)
	removeHeaders[r.InjectHeader] = struct{}{}
	for _, header := range r.RemoveHeaders {
		header = strings.ToLower(strings.TrimSpace(header))
		if !headerPattern.MatchString(header) {
			return fmt.Errorf("invalid remove header %q", header)
		}
		if _, forbidden := forbiddenHeaders[header]; forbidden {
			return fmt.Errorf("remove header %q is reserved", header)
		}
		removeHeaders[header] = struct{}{}
	}
	r.RemoveHeaders = sortedKeys(removeHeaders)
	r.TimeoutProfile = strings.ToLower(strings.TrimSpace(r.TimeoutProfile))
	switch r.TimeoutProfile {
	case "default", "streaming", "long_running":
	default:
		return fmt.Errorf("unsupported timeout_profile %q", r.TimeoutProfile)
	}
	return nil
}

func (u *Upstream) normalizeAndValidate() error {
	u.Scheme = strings.ToLower(strings.TrimSpace(u.Scheme))
	if u.Scheme != "http" && u.Scheme != "https" {
		return errors.New("upstream.scheme must be http or https")
	}
	host, err := normalizeDNSHost(u.Host)
	if err != nil {
		return fmt.Errorf("upstream.host: %w", err)
	}
	u.Host = host
	if u.Port == 0 {
		if u.Scheme == "https" {
			u.Port = 443
		} else {
			u.Port = 80
		}
	}
	u.BasePath, err = normalizePath(u.BasePath)
	if err != nil {
		return fmt.Errorf("upstream.base_path: %w", err)
	}
	u.Protocol = strings.ToLower(strings.TrimSpace(u.Protocol))
	if u.Protocol == "" {
		u.Protocol = "auto"
	}
	if u.Protocol != "auto" && u.Protocol != "http1" && u.Protocol != "http2" {
		return fmt.Errorf("unsupported upstream.protocol %q", u.Protocol)
	}
	return nil
}

func (r *CredentialRef) normalizeAndValidate() error {
	r.Kind = strings.ToLower(strings.TrimSpace(r.Kind))
	if r.ProjectID != nil {
		projectID, err := normalizeUUID(*r.ProjectID)
		if err != nil {
			return fmt.Errorf("credential_ref.project_id: %w", err)
		}
		r.ProjectID = &projectID
	}
	switch r.Kind {
	case "llm", "external":
		if !present(r.SecretName) || !present(r.SecretKey) || present(r.VaultID) || present(r.MCPServerURL) || present(r.SessionID) || present(r.MountName) {
			return fmt.Errorf("credential_ref %s requires only secret_name, secret_key, and optional project_id", r.Kind)
		}
		if err := validateCoordinate("secret_name", *r.SecretName); err != nil {
			return err
		}
		if err := validateCoordinate("secret_key", *r.SecretKey); err != nil {
			return err
		}
	case "mcp":
		if !present(r.VaultID) || !present(r.MCPServerURL) || present(r.SecretName) || present(r.SecretKey) || present(r.ProjectID) || present(r.SessionID) || present(r.MountName) {
			return errors.New("credential_ref mcp requires only vault_id and mcp_server_url")
		}
		vaultID, err := normalizeUUID(*r.VaultID)
		if err != nil {
			return fmt.Errorf("credential_ref.vault_id: %w", err)
		}
		r.VaultID = &vaultID
		if err := validateHTTPURL(*r.MCPServerURL); err != nil {
			return fmt.Errorf("credential_ref.mcp_server_url: %w", err)
		}
	case "git":
		if !present(r.SessionID) || !present(r.MountName) || present(r.SecretName) || present(r.SecretKey) || present(r.ProjectID) || present(r.VaultID) || present(r.MCPServerURL) {
			return errors.New("credential_ref git requires only session_id and mount_name")
		}
		sessionID, err := normalizeUUID(*r.SessionID)
		if err != nil {
			return fmt.Errorf("credential_ref.session_id: %w", err)
		}
		r.SessionID = &sessionID
		if err := validateCoordinate("mount_name", *r.MountName); err != nil {
			return err
		}
	default:
		return fmt.Errorf("unsupported credential_ref.kind %q", r.Kind)
	}
	return nil
}

func (s *InjectScheme) normalizeAndValidate() error {
	s.Kind = strings.ToLower(strings.TrimSpace(s.Kind))
	switch s.Kind {
	case "bearer", "raw":
		if present(s.Username) {
			return fmt.Errorf("inject_scheme %s cannot set username", s.Kind)
		}
	case "basic":
		if !present(s.Username) || strings.ContainsAny(*s.Username, "\r\n:") || len(*s.Username) > 128 {
			return errors.New("inject_scheme basic requires a safe username")
		}
	default:
		return fmt.Errorf("unsupported inject_scheme.kind %q", s.Kind)
	}
	return nil
}

func normalizeUUID(raw string) (string, error) {
	value, err := uuid.Parse(strings.TrimSpace(raw))
	if err != nil {
		return "", errors.New("must be a UUID")
	}
	return value.String(), nil
}

func normalizeDNSHost(raw string) (string, error) {
	raw = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(raw)), ".")
	if raw == "" || strings.ContainsAny(raw, "/\\\x00\r\n") {
		return "", errors.New("must be a DNS hostname")
	}
	if net.ParseIP(strings.Trim(raw, "[]")) != nil {
		return "", errors.New("IP literals are not allowed")
	}
	host, err := idna.Lookup.ToASCII(raw)
	if err != nil || len(host) > 253 || strings.Contains(host, "..") {
		return "", errors.New("must be a valid IDNA hostname")
	}
	for _, label := range strings.Split(host, ".") {
		if label == "" || len(label) > 63 || strings.HasPrefix(label, "-") || strings.HasSuffix(label, "-") {
			return "", errors.New("must be a valid DNS hostname")
		}
	}
	return host, nil
}

func normalizeHostPattern(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if strings.HasPrefix(raw, "*.") {
		host, err := normalizeDNSHost(strings.TrimPrefix(raw, "*."))
		if err != nil || !strings.Contains(host, ".") {
			return "", errors.New("wildcard must target a multi-label DNS suffix")
		}
		return "*." + host, nil
	}
	if strings.Contains(raw, "*") {
		return "", errors.New("wildcard is only allowed as the complete left-most label")
	}
	return normalizeDNSHost(raw)
}

func normalizePath(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		raw = "/"
	}
	if !strings.HasPrefix(raw, "/") || strings.ContainsAny(raw, "\x00\r\n?#") || len(raw) > 2048 {
		return "", errors.New("must be an absolute path without query or fragment")
	}
	return raw, nil
}

func validateHTTPURL(raw string) error {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Hostname() == "" || parsed.User != nil {
		return errors.New("must be an HTTP(S) URL without userinfo")
	}
	_, err = normalizeDNSHost(parsed.Hostname())
	return err
}

func present(value *string) bool {
	return value != nil && strings.TrimSpace(*value) != ""
}

func validateCoordinate(name, value string) error {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > 255 || strings.ContainsAny(value, "\x00\r\n") {
		return fmt.Errorf("credential_ref.%s is invalid", name)
	}
	return nil
}

func sortedKeys[T ~string](values map[T]struct{}) []T {
	result := make([]T, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Slice(result, func(i, j int) bool { return result[i] < result[j] })
	return result
}

func ensureEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); errors.Is(err, io.EOF) {
		return nil
	} else if err != nil {
		return fmt.Errorf("decode trailing policy data: %w", err)
	}
	return errors.New("policy payload contains multiple JSON documents")
}
