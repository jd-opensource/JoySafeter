package xds

import (
	"crypto/tls"
	"crypto/x509"
	"testing"
)

func TestVerifyClientIdentityAcceptsExactDNSSAN(t *testing.T) {
	state := tls.ConnectionState{PeerCertificates: []*x509.Certificate{{
		DNSNames: []string{"joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"},
	}}}
	if err := verifyClientIdentity(state, "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"); err != nil {
		t.Fatalf("verify client identity: %v", err)
	}
}

func TestVerifyClientIdentityRejectsOtherCertificateFromTrustedCA(t *testing.T) {
	state := tls.ConnectionState{PeerCertificates: []*x509.Certificate{{
		DNSNames: []string{"other-client.joysafeter-control.svc.cluster.local"},
	}}}
	if err := verifyClientIdentity(state, "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"); err == nil {
		t.Fatal("expected mismatched client identity to be rejected")
	}
}

func TestVerifyClientIdentityRejectsMissingCertificate(t *testing.T) {
	if err := verifyClientIdentity(tls.ConnectionState{}, "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"); err == nil {
		t.Fatal("expected missing client certificate to be rejected")
	}
}
