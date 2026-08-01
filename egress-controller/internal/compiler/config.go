package compiler

import (
	"errors"
	"fmt"
	"strings"
)

type Config struct {
	CredentialAddress string
	CredentialPort    uint32
	ForwardAddress    string
	ForwardPort       uint32
	AuthzCluster      string
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
	DeniedCIDRs       []string
	// OrchestratorGrpcCluster is the static bootstrap cluster the Docker
	// control-channel (grpc.sock) listener routes to. Must match the Rust
	// bootstrap's "orchestrator_grpc" cluster name.
	OrchestratorGrpcCluster string
}

func DefaultConfig() Config {
	return Config{
		CredentialAddress:       "0.0.0.0",
		CredentialPort:          8443,
		ForwardAddress:          "0.0.0.0",
		ForwardPort:             8080,
		AuthzCluster:            "joysafeter_egress_authz",
		AuthzHost:               "joysafeter-egress-authz.joysafeter-control.svc.cluster.local",
		AuthzPort:               18090,
		AuthzTLS:                true,
		AuthzServerName:         "joysafeter-egress-authz.joysafeter-control.svc.cluster.local",
		AuthzClientCert:         "/var/run/joysafeter-egress/authz-tls/tls.crt",
		AuthzClientKey:          "/var/run/joysafeter-egress/authz-tls/tls.key",
		AuthzCA:                 "/var/run/joysafeter-egress/authz-tls/ca.crt",
		DownstreamTLS:           true,
		DownstreamCert:          "/var/run/joysafeter-egress/downstream-tls/tls.crt",
		DownstreamKey:           "/var/run/joysafeter-egress/downstream-tls/tls.key",
		PublicCA:                "/etc/ssl/certs/ca-certificates.crt",
		SocketRoot:              "/sockets",
		OrchestratorGrpcCluster: "orchestrator_grpc",
		DeniedCIDRs: []string{
			"0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
			"172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16",
			"198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
			"::/128", "::1/128", "2001:db8::/32", "fc00::/7", "fe80::/10", "ff00::/8",
		},
	}
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.CredentialAddress) == "" || c.CredentialPort == 0 {
		return errors.New("credential listener address and port are required")
	}
	if strings.TrimSpace(c.ForwardAddress) == "" || c.ForwardPort == 0 {
		return errors.New("forward listener address and port are required")
	}
	if c.CredentialAddress == c.ForwardAddress && c.CredentialPort == c.ForwardPort {
		return errors.New("credential and forward listeners must use different addresses or ports")
	}
	if strings.TrimSpace(c.AuthzCluster) == "" || strings.TrimSpace(c.AuthzHost) == "" || c.AuthzPort == 0 {
		return errors.New("ext_authz cluster, host, and port are required")
	}
	if c.AuthzTLS && (c.AuthzServerName == "" || c.AuthzClientCert == "" || c.AuthzClientKey == "" || c.AuthzCA == "") {
		return errors.New("ext_authz mTLS requires server name, client certificate, key, and CA paths")
	}
	if c.DownstreamTLS && (c.DownstreamCert == "" || c.DownstreamKey == "") {
		return errors.New("downstream TLS requires certificate and key paths")
	}
	if strings.TrimSpace(c.PublicCA) == "" || strings.TrimSpace(c.SocketRoot) == "" {
		return errors.New("public CA and Docker socket root are required")
	}
	if !strings.HasPrefix(c.SocketRoot, "/") {
		return fmt.Errorf("Docker socket root must be absolute: %q", c.SocketRoot)
	}
	return nil
}
