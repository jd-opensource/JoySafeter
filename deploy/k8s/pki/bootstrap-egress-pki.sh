#!/usr/bin/env bash
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"
OPENSSL="${OPENSSL:-openssl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
EGRESS_NS="${JOYSAFETER_EGRESS_NAMESPACE:-joysafeter-egress}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
CA_VALID_DAYS="${CA_VALID_DAYS:-30}"
CERT_VALID_DAYS="${CERT_VALID_DAYS:-7}"
KEEP_PKI_DIR="${KEEP_PKI_DIR:-false}"
INCLUDE_GO_XDS_ROLLBACK_PKI="${INCLUDE_GO_XDS_ROLLBACK_PKI:-false}"

ENVOY_IDENTITY="joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local"
XDS_SERVER_IDENTITY="joysafeter-egress-controller.joysafeter-control.svc.cluster.local"
RUST_XDS_SERVER_IDENTITY="joysafeter-orchestrator.joysafeter-control.svc.cluster.local"
AUTHZ_SERVER_IDENTITY="joysafeter-egress-authz.joysafeter-control.svc.cluster.local"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/joysafeter-egress-pki.XXXXXX")"
umask 077

cleanup() {
  if [[ "$KEEP_PKI_DIR" == "true" ]]; then
    printf 'Ephemeral PKI retained at %s\n' "$WORK_DIR" >&2
  else
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '%s is required\n' "$1" >&2
    exit 1
  fi
}

create_ca() {
  local name="$1"
  local common_name="$2"
  local directory="$WORK_DIR/$name"
  mkdir -p "$directory"
  cat >"$directory/ca.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no

[dn]
CN = ${common_name}

[v3_ca]
basicConstraints = critical,CA:true,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF
  "$OPENSSL" req -x509 -new -nodes -newkey rsa:3072 -sha256 \
    -days "$CA_VALID_DAYS" \
    -config "$directory/ca.cnf" \
    -keyout "$directory/ca.key" \
    -out "$directory/ca.crt" >/dev/null 2>&1
}

create_leaf() {
  local ca_name="$1"
  local leaf_name="$2"
  local dns_name="$3"
  local eku="$4"
  local directory="$WORK_DIR/$ca_name"
  cat >"$directory/$leaf_name.ext" <<EOF
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = ${eku}
  subjectAltName = DNS:${dns_name}
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
EOF
  "$OPENSSL" req -new -newkey rsa:2048 -nodes -sha256 \
    -subj "/CN=JoySafeter ${leaf_name}" \
    -keyout "$directory/$leaf_name.key" \
    -out "$directory/$leaf_name.csr" >/dev/null 2>&1
  "$OPENSSL" x509 -req -sha256 \
    -in "$directory/$leaf_name.csr" \
    -CA "$directory/ca.crt" \
    -CAkey "$directory/ca.key" \
    -CAcreateserial \
    -days "$CERT_VALID_DAYS" \
    -extfile "$directory/$leaf_name.ext" \
    -out "$directory/$leaf_name.crt" >/dev/null 2>&1
  "$OPENSSL" verify -CAfile "$directory/ca.crt" "$directory/$leaf_name.crt" >/dev/null
}

apply_tls_secret() {
  local namespace="$1"
  local secret_name="$2"
  local ca_name="$3"
  local leaf_name="$4"
  local directory="$WORK_DIR/$ca_name"
  "$KUBECTL" -n "$namespace" create secret generic "$secret_name" \
    --from-file=tls.crt="$directory/$leaf_name.crt" \
    --from-file=tls.key="$directory/$leaf_name.key" \
    --from-file=ca.crt="$directory/ca.crt" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f - >/dev/null
  "$KUBECTL" -n "$namespace" label secret "$secret_name" \
    app.kubernetes.io/part-of=joysafeter \
    app.kubernetes.io/managed-by=joysafeter-egress-pki-bootstrap \
    --overwrite >/dev/null
}

require_cmd "$KUBECTL"
require_cmd "$OPENSSL"

for namespace in "$CONTROL_NS" "$EGRESS_NS" "$SANDBOX_NS"; do
  "$KUBECTL" get namespace "$namespace" >/dev/null
done

create_ca xds "JoySafeter ephemeral xDS CA"
create_leaf xds rust-server "$RUST_XDS_SERVER_IDENTITY" serverAuth
create_leaf xds envoy-client "$ENVOY_IDENTITY" clientAuth
if [[ "$INCLUDE_GO_XDS_ROLLBACK_PKI" == "true" ]]; then
  create_leaf xds controller-server "$XDS_SERVER_IDENTITY" serverAuth
fi

create_ca authz "JoySafeter ephemeral authz CA"
create_leaf authz authz-server "$AUTHZ_SERVER_IDENTITY" serverAuth
create_leaf authz envoy-client "$ENVOY_IDENTITY" clientAuth

create_ca downstream "JoySafeter ephemeral downstream CA"
create_leaf downstream envoy-server "$ENVOY_IDENTITY" serverAuth

apply_tls_secret "$CONTROL_NS" joysafeter-rust-xds-server-tls xds rust-server
apply_tls_secret "$EGRESS_NS" joysafeter-egress-envoy-xds-client-tls xds envoy-client
if [[ "$INCLUDE_GO_XDS_ROLLBACK_PKI" == "true" ]]; then
  apply_tls_secret "$CONTROL_NS" joysafeter-egress-controller-tls xds controller-server
fi
apply_tls_secret "$CONTROL_NS" joysafeter-egress-authz-server-tls authz authz-server
apply_tls_secret "$EGRESS_NS" joysafeter-egress-authz-client-tls authz envoy-client
apply_tls_secret "$EGRESS_NS" joysafeter-egress-downstream-server-tls downstream envoy-server

"$KUBECTL" -n "$SANDBOX_NS" create configmap joysafeter-egress-downstream-ca \
  --from-file=ca.crt="$WORK_DIR/downstream/ca.crt" \
  --dry-run=client -o yaml | "$KUBECTL" apply -f - >/dev/null
"$KUBECTL" -n "$SANDBOX_NS" label configmap joysafeter-egress-downstream-ca \
  app.kubernetes.io/part-of=joysafeter \
  app.kubernetes.io/managed-by=joysafeter-egress-pki-bootstrap \
  --overwrite >/dev/null

printf 'Installed ephemeral JoySafeter egress PKI (%s-day leaves)\n' "$CERT_VALID_DAYS"
printf 'Client identity: %s\n' "$ENVOY_IDENTITY"
printf 'Private keys were created under a temporary directory and will be deleted.\n'
