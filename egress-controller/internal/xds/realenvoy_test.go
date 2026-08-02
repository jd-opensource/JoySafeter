//go:build realenvoy

// Package xds_test's real-Envoy acceptance test (build tag `realenvoy`).
//
// It proves the controller's compiled Docker xDS snapshot is ACCEPTED and ACKed
// by a REAL Envoy: it starts the xDS gRPC server (plaintext) serving a compiled
// docker snapshot, boots a real Envoy via func-e pointed at it, and asserts via
// the Envoy admin interface that CDS/LDS updates succeeded and the per-sandbox
// _http (ext_authz) + _grpc (no ext_authz) listeners are present — closing the
// "compiled config never fed to a real Envoy" gap. Not run by default `go test`
// (needs network to download Envoy); run with `-tags=realenvoy`.
package xds_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"log/slog"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	logv3 "github.com/envoyproxy/go-control-plane/pkg/log"
	funcE "github.com/tetratelabs/func-e"
	"github.com/tetratelabs/func-e/api"

	"github.com/joysafeter/joysafeter/egress-controller/internal/compiler"
	"github.com/joysafeter/joysafeter/egress-controller/internal/config"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/joysafeter/joysafeter/egress-controller/internal/xds"
	"github.com/prometheus/client_golang/prometheus"
)

const envoyTestVersion = "1.39.0"

func TestRealEnvoyAcceptsCompiledDockerSnapshot(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	const sandboxID = "018ff000-0000-7000-8000-000000000001"
	tmp := t.TempDir()

	// A real (self-signed) CA PEM so Envoy can load the upstream TLS
	// validation_context the compiled credential cluster references. We never
	// make a real TLS connection here; the file only needs to parse.
	caPath := filepath.Join(tmp, "ca.pem")
	writeSelfSignedCA(t, caPath)

	// Compiler config pointed at writable/real paths so a strict Envoy accepts
	// every resource: pipe sockets under a temp dir, a real CA, authz plaintext.
	cfg := compiler.DefaultConfig()
	cfg.SocketRoot = tmp
	cfg.PublicCA = caPath
	cfg.AuthzTLS = false
	cfg.DownstreamTLS = false

	desired := dockerDesiredGeneration(t, sandboxID)
	comp, err := compiler.New(cfg)
	if err != nil {
		t.Fatalf("compiler.New: %v", err)
	}
	compiled, err := comp.Compile(ctx, desired)
	if err != nil {
		t.Fatalf("compile: %v", err)
	}

	// xDS server (plaintext) on an ephemeral port, serving the compiled snapshot.
	cache := cachev3.NewSnapshotCache(true, group.Hasher{}, logv3.LoggerFuncs{})
	metrics := telemetry.New(prometheus.NewRegistry())
	manager := xds.NewManager(cache, slog.Default(), metrics)
	if err := manager.Publish(ctx, compiled); err != nil {
		t.Fatalf("publish: %v", err)
	}
	callbacks := xds.NewCallbacks(manager, slog.Default(), metrics)
	grpcServer, err := xds.NewGRPCServer(ctx, cache, callbacks, config.TLSConfig{Enabled: false})
	if err != nil {
		t.Fatalf("NewGRPCServer: %v", err)
	}
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	go func() { _ = grpcServer.Serve(lis) }()
	defer grpcServer.Stop()
	xdsPort := lis.Addr().(*net.TCPAddr).Port

	adminPort := freeTCPPort(t)
	bootstrapPath := filepath.Join(tmp, "bootstrap.yaml")
	if err := os.WriteFile(bootstrapPath, []byte(renderBootstrap(xdsPort, adminPort)), 0o600); err != nil {
		t.Fatalf("write bootstrap: %v", err)
	}

	// Boot a real Envoy via func-e against our xDS server. Use a persistent
	// func-e cache dir (NOT t.TempDir) so the ~40MB Envoy binary is downloaded
	// once and reused across runs; the first cold run absorbs the download.
	funcEHome := filepath.Join(os.TempDir(), "joysafeter-funce-cache")
	envoyOut := &lockedBuffer{}
	runCtx, runCancel := context.WithCancel(ctx)
	defer runCancel()
	runErr := make(chan error, 1)
	go func() {
		runErr <- funcE.Run(runCtx, []string{"run", "-c", bootstrapPath},
			api.EnvoyVersion(envoyTestVersion),
			api.HomeDir(funcEHome),
			api.Out(envoyOut),
			api.EnvoyOut(envoyOut), api.EnvoyErr(envoyOut),
		)
	}()

	adminBase := fmt.Sprintf("http://127.0.0.1:%d", adminPort)

	// Generous cold-start deadline: cold run must cover Envoy download+extract
	// (tens of seconds) plus boot plus ACK.
	deadline := time.Now().Add(240 * time.Second)
	var lastStats string
	for time.Now().Before(deadline) {
		select {
		case err := <-runErr:
			t.Fatalf("func-e exited early: %v\nenvoy output:\n%s", err, envoyOut.String())
		default:
		}
		stats, err := httpGet(adminBase + "/stats?filter=(cds|lds)\\.update_success")
		if err == nil {
			lastStats = stats
			if statValue(stats, "cluster_manager.cds.update_success") >= 1 &&
				statValue(stats, "listener_manager.lds.update_success") >= 1 {
				break
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	if statValue(lastStats, "cluster_manager.cds.update_success") < 1 ||
		statValue(lastStats, "listener_manager.lds.update_success") < 1 {
		t.Fatalf("Envoy did not ACK CDS+LDS in time.\nstats:\n%s\nenvoy output:\n%s", lastStats, envoyOut.String())
	}

	// config_dump must contain both per-sandbox listeners with the expected
	// ext_authz split, and no secret material.
	dump, err := httpGet(adminBase + "/config_dump")
	if err != nil {
		t.Fatalf("config_dump: %v", err)
	}
	httpName := "joysafeter_" + strings.ReplaceAll(sandboxID, "-", "_") + "_http"
	grpcName := "joysafeter_" + strings.ReplaceAll(sandboxID, "-", "_") + "_grpc"
	if !strings.Contains(dump, httpName) {
		t.Fatalf("config_dump missing %s", httpName)
	}
	if !strings.Contains(dump, grpcName) {
		t.Fatalf("config_dump missing %s", grpcName)
	}
	if !strings.Contains(dump, "envoy.filters.http.ext_authz") {
		t.Fatalf("config_dump missing ext_authz filter on credential path")
	}
	// The provider secret name/key must never appear in Envoy's applied config.
	for _, forbidden := range []string{"provider-secret", "API_KEY"} {
		if strings.Contains(dump, forbidden) {
			t.Fatalf("config_dump leaked secret material %q", forbidden)
		}
	}
	t.Logf("real Envoy accepted + ACKed the compiled docker snapshot (%s, %s present)", httpName, grpcName)
}

// dockerDesiredGeneration builds a docker desired generation equivalent to the
// compiler package's fixture (kept in sync with internal/compiler test data).
func dockerDesiredGeneration(t *testing.T, sandboxID string) source.DesiredGeneration {
	t.Helper()
	metadata := group.Metadata{
		DeploymentID: "test", Environment: "test", Region: "local", Provider: "docker",
		ShardID: "0", HostID: "host-1", EnvoyVersion: envoyTestVersion, ConfigSchemaVersion: "1",
	}
	groupKey, err := metadata.Key()
	if err != nil {
		t.Fatalf("group key: %v", err)
	}
	projectID := "018ff000-0000-7000-8000-000000000002"
	policies := []map[string]any{{
		"sandbox_id": sandboxID, "project_id": projectID, "mode": "limited",
		"credential_routes": []map[string]any{{
			"route_id": "llm:primary", "kind": "llm", "match_authority": "llm-egress.internal",
			"match_path": map[string]any{"kind": "prefix", "value": "/v1"}, "methods": []string{"POST"},
			"upstream":       map[string]any{"scheme": "https", "host": "api.example.com", "port": 443, "base_path": "/v1", "protocol": "http2"},
			"credential_ref": map[string]any{"kind": "llm", "secret_name": "provider-secret", "secret_key": "API_KEY", "project_id": projectID},
			"inject_header":  "authorization", "inject_scheme": map[string]any{"kind": "bearer"},
			"remove_headers": []string{"x-api-key"}, "timeout_profile": "streaming", "websocket": false,
		}},
		"allowed_public_hosts": []string{"downloads.example.com"}, "denied_cidrs": []string{"10.0.0.0/8"},
	}}
	raw, err := json.Marshal(policies)
	if err != nil {
		t.Fatalf("marshal policies: %v", err)
	}
	return source.DesiredGeneration{
		GroupKey: groupKey, Generation: 1, NodeSelector: metadata, PolicySchemaVersion: 1,
		DesiredPolicies: raw, ContentSHA256: strings.Repeat("0", 64),
	}
}

func renderBootstrap(xdsPort, adminPort int) string {
	return fmt.Sprintf(`
node:
  id: envoy-realenvoy-test
  cluster: joysafeter-egress
  metadata:
    deployment_id: test
    environment: test
    region: local
    provider: docker
    shard_id: "0"
    host_id: host-1
    envoy_version: "%s"
    config_schema_version: "1"
admin:
  address:
    socket_address: { address: 127.0.0.1, port_value: %d }
dynamic_resources:
  ads_config:
    api_type: DELTA_GRPC
    transport_api_version: V3
    grpc_services:
      - envoy_grpc: { cluster_name: xds_cluster }
  cds_config: { ads: {}, resource_api_version: V3 }
  lds_config: { ads: {}, resource_api_version: V3 }
static_resources:
  clusters:
    - name: xds_cluster
      type: STRICT_DNS
      connect_timeout: 1s
      typed_extension_protocol_options:
        envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
          "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
          explicit_http_config: { http2_protocol_options: {} }
      load_assignment:
        cluster_name: xds_cluster
        endpoints:
          - lb_endpoints:
              - endpoint: { address: { socket_address: { address: 127.0.0.1, port_value: %d } } }
`, envoyTestVersion, adminPort, xdsPort)
}

func writeSelfSignedCA(t *testing.T, path string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("gen key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "realenvoy-test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		t.Fatalf("write ca: %v", err)
	}
}

func freeTCPPort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("free port: %v", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func httpGet(url string) (string, error) {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	return string(body), err
}

// statValue parses an Envoy prometheus/plain stats line "name: value".
func statValue(stats, name string) int {
	for _, line := range strings.Split(stats, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, name+":") {
			var v int
			_, err := fmt.Sscanf(strings.TrimSpace(strings.TrimPrefix(line, name+":")), "%d", &v)
			if err == nil {
				return v
			}
		}
	}
	return 0
}

type lockedBuffer struct {
	mu  chan struct{}
	buf strings.Builder
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	if b.mu == nil {
		b.mu = make(chan struct{}, 1)
	}
	b.mu <- struct{}{}
	defer func() { <-b.mu }()
	return b.buf.Write(p)
}

func (b *lockedBuffer) String() string { return b.buf.String() }
