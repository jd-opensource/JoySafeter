package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	XDSAddress        string
	HTTPAddress       string
	SourceMode        string
	SnapshotFile      string
	ReconcileInterval time.Duration
	ShutdownTimeout   time.Duration
	MaxSnapshotBytes  int64
	LogLevel          string
	StateDatabaseURL  string
	ControllerID      string
	StatusQueueSize   int64
	NodeLeaseTTL      time.Duration
	NodeHeartbeat     time.Duration
	RecomputeInterval time.Duration
	CredentialAddress string
	CredentialPort    uint32
	ForwardAddress    string
	ForwardPort       uint32
	AuthzHost         string
	AuthzPort         uint32
	AuthzTLS          bool
	AuthzServerName   string
	AuthzClientCert   string
	AuthzClientKey    string
	AuthzCA           string
	DownstreamTLS     bool
	DownstreamCert    string
	DownstreamKey     string
	PublicCA          string
	SocketRoot        string
	TLS               TLSConfig
}

type TLSConfig struct {
	Enabled      bool
	CertFile     string
	KeyFile      string
	CAFile       string
	ClientDNSSAN string
	MinTLS13     bool
}

func Load() (Config, error) {
	cfg := Config{
		XDSAddress:        env("JOYSAFETER_EGRESS_CONTROLLER_XDS_ADDR", ":18000"),
		HTTPAddress:       env("JOYSAFETER_EGRESS_CONTROLLER_HTTP_ADDR", ":18080"),
		SourceMode:        strings.ToLower(env("JOYSAFETER_EGRESS_CONTROLLER_SOURCE", "")),
		SnapshotFile:      env("JOYSAFETER_EGRESS_CONTROLLER_SNAPSHOT_FILE", "/etc/joysafeter-egress-controller/snapshots.json"),
		ReconcileInterval: 30 * time.Second,
		ShutdownTimeout:   15 * time.Second,
		MaxSnapshotBytes:  16 << 20,
		LogLevel:          strings.ToLower(env("JOYSAFETER_EGRESS_CONTROLLER_LOG_LEVEL", "info")),
		StateDatabaseURL:  env("JOYSAFETER_EGRESS_CONTROLLER_DATABASE_URL", ""),
		ControllerID:      env("JOYSAFETER_EGRESS_CONTROLLER_INSTANCE_ID", defaultControllerID()),
		StatusQueueSize:   4096,
		NodeLeaseTTL:      30 * time.Second,
		NodeHeartbeat:     10 * time.Second,
		RecomputeInterval: 15 * time.Second,
		CredentialAddress: env("JOYSAFETER_EGRESS_CREDENTIAL_LISTENER_ADDR", "0.0.0.0"),
		CredentialPort:    8443,
		ForwardAddress:    env("JOYSAFETER_EGRESS_FORWARD_LISTENER_ADDR", "0.0.0.0"),
		ForwardPort:       8080,
		AuthzHost:         env("JOYSAFETER_EGRESS_AUTHZ_HOST", "joysafeter-egress-authz.joysafeter-control.svc.cluster.local"),
		AuthzPort:         18090,
		AuthzTLS:          envBool("JOYSAFETER_EGRESS_AUTHZ_MTLS", true),
		AuthzServerName:   env("JOYSAFETER_EGRESS_AUTHZ_SERVER_NAME", "joysafeter-egress-authz.joysafeter-control.svc.cluster.local"),
		AuthzClientCert:   env("JOYSAFETER_EGRESS_AUTHZ_CLIENT_CERT", "/var/run/joysafeter-egress/authz-tls/tls.crt"),
		AuthzClientKey:    env("JOYSAFETER_EGRESS_AUTHZ_CLIENT_KEY", "/var/run/joysafeter-egress/authz-tls/tls.key"),
		AuthzCA:           env("JOYSAFETER_EGRESS_AUTHZ_CA", "/var/run/joysafeter-egress/authz-tls/ca.crt"),
		DownstreamTLS:     envBool("JOYSAFETER_EGRESS_DOWNSTREAM_TLS", true),
		DownstreamCert:    env("JOYSAFETER_EGRESS_DOWNSTREAM_CERT", "/var/run/joysafeter-egress/downstream-tls/tls.crt"),
		DownstreamKey:     env("JOYSAFETER_EGRESS_DOWNSTREAM_KEY", "/var/run/joysafeter-egress/downstream-tls/tls.key"),
		PublicCA:          env("JOYSAFETER_EGRESS_PUBLIC_CA", "/etc/ssl/certs/ca-certificates.crt"),
		SocketRoot:        env("JOYSAFETER_EGRESS_SOCKET_ROOT", "/sockets"),
		TLS: TLSConfig{
			Enabled:      envBool("JOYSAFETER_EGRESS_XDS_MTLS", true),
			CertFile:     env("JOYSAFETER_EGRESS_XDS_CERT_FILE", "/var/run/joysafeter/tls/tls.crt"),
			KeyFile:      env("JOYSAFETER_EGRESS_XDS_KEY_FILE", "/var/run/joysafeter/tls/tls.key"),
			CAFile:       env("JOYSAFETER_EGRESS_XDS_CLIENT_CA_FILE", "/var/run/joysafeter/tls/ca.crt"),
			ClientDNSSAN: env("JOYSAFETER_EGRESS_XDS_CLIENT_DNS_SAN", "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"),
			MinTLS13:     envBool("JOYSAFETER_EGRESS_XDS_TLS13", true),
		},
	}

	var err error
	if cfg.ReconcileInterval, err = envDuration("JOYSAFETER_EGRESS_CONTROLLER_RECONCILE_INTERVAL", cfg.ReconcileInterval); err != nil {
		return Config{}, err
	}
	if cfg.ShutdownTimeout, err = envDuration("JOYSAFETER_EGRESS_CONTROLLER_SHUTDOWN_TIMEOUT", cfg.ShutdownTimeout); err != nil {
		return Config{}, err
	}
	if cfg.MaxSnapshotBytes, err = envInt64("JOYSAFETER_EGRESS_CONTROLLER_MAX_SNAPSHOT_BYTES", cfg.MaxSnapshotBytes); err != nil {
		return Config{}, err
	}
	if cfg.StatusQueueSize, err = envInt64("JOYSAFETER_EGRESS_CONTROLLER_STATUS_QUEUE_SIZE", cfg.StatusQueueSize); err != nil {
		return Config{}, err
	}
	if cfg.NodeLeaseTTL, err = envDuration("JOYSAFETER_EGRESS_CONTROLLER_NODE_LEASE_TTL", cfg.NodeLeaseTTL); err != nil {
		return Config{}, err
	}
	if cfg.NodeHeartbeat, err = envDuration("JOYSAFETER_EGRESS_CONTROLLER_NODE_HEARTBEAT", cfg.NodeHeartbeat); err != nil {
		return Config{}, err
	}
	if cfg.RecomputeInterval, err = envDuration("JOYSAFETER_EGRESS_CONTROLLER_RECOMPUTE_INTERVAL", cfg.RecomputeInterval); err != nil {
		return Config{}, err
	}
	if cfg.CredentialPort, err = envUint32("JOYSAFETER_EGRESS_CREDENTIAL_LISTENER_PORT", cfg.CredentialPort); err != nil {
		return Config{}, err
	}
	if cfg.ForwardPort, err = envUint32("JOYSAFETER_EGRESS_FORWARD_LISTENER_PORT", cfg.ForwardPort); err != nil {
		return Config{}, err
	}
	if cfg.AuthzPort, err = envUint32("JOYSAFETER_EGRESS_AUTHZ_PORT", cfg.AuthzPort); err != nil {
		return Config{}, err
	}
	if cfg.SourceMode == "" {
		if cfg.StateDatabaseURL == "" {
			cfg.SourceMode = "file"
		} else {
			cfg.SourceMode = "postgres"
		}
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.XDSAddress) == "" || strings.TrimSpace(c.HTTPAddress) == "" {
		return errors.New("xDS and HTTP listen addresses are required")
	}
	if c.XDSAddress == c.HTTPAddress {
		return errors.New("xDS and HTTP listen addresses must differ")
	}
	if c.SourceMode != "file" && c.SourceMode != "postgres" {
		return fmt.Errorf("unsupported desired-state source %q", c.SourceMode)
	}
	if c.SourceMode == "file" && strings.TrimSpace(c.SnapshotFile) == "" {
		return errors.New("snapshot file is required")
	}
	if c.SourceMode == "postgres" && strings.TrimSpace(c.StateDatabaseURL) == "" {
		return errors.New("PostgreSQL desired-state source requires a database URL")
	}
	if c.ReconcileInterval < time.Second {
		return errors.New("reconcile interval must be at least 1s")
	}
	if c.ShutdownTimeout < time.Second {
		return errors.New("shutdown timeout must be at least 1s")
	}
	if c.MaxSnapshotBytes < 1024 || c.MaxSnapshotBytes > 64<<20 {
		return errors.New("max snapshot bytes must be between 1 KiB and 64 MiB")
	}
	if c.ControllerID == "" || len(c.ControllerID) > 128 {
		return errors.New("controller instance ID must contain 1 to 128 characters")
	}
	if c.StatusQueueSize < 128 || c.StatusQueueSize > 1<<20 {
		return errors.New("status queue size must be between 128 and 1048576")
	}
	if c.NodeLeaseTTL < 10*time.Second || c.NodeLeaseTTL > 5*time.Minute {
		return errors.New("node lease TTL must be between 10s and 5m")
	}
	if c.NodeHeartbeat < time.Second || c.NodeHeartbeat*2 >= c.NodeLeaseTTL {
		return errors.New("node heartbeat must be at least 1s and less than half the lease TTL")
	}
	if c.RecomputeInterval < time.Second || c.RecomputeInterval > 10*time.Minute {
		return errors.New("recompute interval must be between 1s and 10m")
	}
	switch c.LogLevel {
	case "debug", "info", "warn", "error":
	default:
		return fmt.Errorf("unsupported log level %q", c.LogLevel)
	}
	if c.TLS.Enabled && (c.TLS.CertFile == "" || c.TLS.KeyFile == "" || c.TLS.CAFile == "" || strings.TrimSpace(c.TLS.ClientDNSSAN) == "") {
		return errors.New("mTLS requires certificate, key, client CA, and expected client DNS SAN")
	}
	return nil
}

func defaultControllerID() string {
	hostname, err := os.Hostname()
	if err != nil || strings.TrimSpace(hostname) == "" {
		return "joysafeter-egress-controller"
	}
	return strings.TrimSpace(hostname)
}

func env(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return strings.TrimSpace(value)
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	value, ok := os.LookupEnv(key)
	if !ok {
		return fallback
	}
	parsed, err := strconv.ParseBool(strings.TrimSpace(value))
	if err != nil {
		return fallback
	}
	return parsed
}

func envDuration(key string, fallback time.Duration) (time.Duration, error) {
	value, ok := os.LookupEnv(key)
	if !ok || strings.TrimSpace(value) == "" {
		return fallback, nil
	}
	parsed, err := time.ParseDuration(strings.TrimSpace(value))
	if err != nil {
		return 0, fmt.Errorf("parse %s: %w", key, err)
	}
	return parsed, nil
}

func envInt64(key string, fallback int64) (int64, error) {
	value, ok := os.LookupEnv(key)
	if !ok || strings.TrimSpace(value) == "" {
		return fallback, nil
	}
	parsed, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("parse %s: %w", key, err)
	}
	return parsed, nil
}

func envUint32(key string, fallback uint32) (uint32, error) {
	value, ok := os.LookupEnv(key)
	if !ok || strings.TrimSpace(value) == "" {
		return fallback, nil
	}
	parsed, err := strconv.ParseUint(strings.TrimSpace(value), 10, 16)
	if err != nil || parsed == 0 {
		return 0, fmt.Errorf("parse %s: must be a port between 1 and 65535", key)
	}
	return uint32(parsed), nil
}
