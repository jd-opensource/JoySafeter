package xds

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"
	"time"

	clusterservicev3 "github.com/envoyproxy/go-control-plane/envoy/service/cluster/v3"
	discoveryservicev3 "github.com/envoyproxy/go-control-plane/envoy/service/discovery/v3"
	listenerservicev3 "github.com/envoyproxy/go-control-plane/envoy/service/listener/v3"
	routeservicev3 "github.com/envoyproxy/go-control-plane/envoy/service/route/v3"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	serverv3 "github.com/envoyproxy/go-control-plane/pkg/server/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/config"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/keepalive"
)

func NewGRPCServer(ctx context.Context, cache cachev3.SnapshotCache, callbacks *Callbacks, tlsConfig config.TLSConfig) (*grpc.Server, error) {
	options := []grpc.ServerOption{
		grpc.MaxConcurrentStreams(100000),
		grpc.MaxRecvMsgSize(16 << 20),
		grpc.MaxSendMsgSize(16 << 20),
		grpc.KeepaliveParams(keepalive.ServerParameters{Time: 30 * time.Second, Timeout: 5 * time.Second, MaxConnectionAgeGrace: 30 * time.Second}),
		grpc.KeepaliveEnforcementPolicy(keepalive.EnforcementPolicy{MinTime: 15 * time.Second, PermitWithoutStream: true}),
	}
	if tlsConfig.Enabled {
		value, err := loadTLSConfig(tlsConfig)
		if err != nil {
			return nil, err
		}
		options = append(options, grpc.Creds(credentials.NewTLS(value)))
	}
	grpcServer := grpc.NewServer(options...)
	xdsServer := serverv3.NewServer(ctx, cache, callbacks)
	discoveryservicev3.RegisterAggregatedDiscoveryServiceServer(grpcServer, xdsServer)
	clusterservicev3.RegisterClusterDiscoveryServiceServer(grpcServer, xdsServer)
	routeservicev3.RegisterRouteDiscoveryServiceServer(grpcServer, xdsServer)
	listenerservicev3.RegisterListenerDiscoveryServiceServer(grpcServer, xdsServer)
	return grpcServer, nil
}

func loadTLSConfig(value config.TLSConfig) (*tls.Config, error) {
	certificate, err := tls.LoadX509KeyPair(value.CertFile, value.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load xDS server certificate: %w", err)
	}
	caPEM, err := os.ReadFile(value.CAFile)
	if err != nil {
		return nil, fmt.Errorf("read xDS client CA: %w", err)
	}
	clientCAs := x509.NewCertPool()
	if !clientCAs.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("xDS client CA contains no valid certificates")
	}
	minimumVersion := uint16(tls.VersionTLS12)
	if value.MinTLS13 {
		minimumVersion = tls.VersionTLS13
	}
	return &tls.Config{
		MinVersion: minimumVersion, Certificates: []tls.Certificate{certificate},
		ClientCAs: clientCAs, ClientAuth: tls.RequireAndVerifyClientCert,
		VerifyConnection: func(state tls.ConnectionState) error {
			return verifyClientIdentity(state, value.ClientDNSSAN)
		},
	}, nil
}

func verifyClientIdentity(state tls.ConnectionState, expectedDNSSAN string) error {
	if len(state.PeerCertificates) == 0 {
		return fmt.Errorf("xDS client presented no certificate")
	}
	for _, dnsName := range state.PeerCertificates[0].DNSNames {
		if dnsName == expectedDNSSAN {
			return nil
		}
	}
	return fmt.Errorf("xDS client certificate DNS SAN does not match %q", expectedDNSSAN)
}
