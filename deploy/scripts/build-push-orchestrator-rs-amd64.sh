#!/usr/bin/env bash
#
# Build + push the Rust orchestrator as a PLAIN single-arch image.
#
# Compilation is a native host cargo-zigbuild cross-compile (via deploy.sh's
# binary path — no QEMU/Rosetta), then orchestrator-rs-binary.Dockerfile just
# COPYs the prebuilt binary. This script adds the two things deploy.sh's buildx
# push can't do against the internal registry:
#   * --provenance=false so the tag is one image manifest, not an OCI index
#     ("folder") wrapping an unknown/unknown attestation.
#   * push via the host docker daemon, which (unlike the isolated buildx
#     builder) can reach the registry.
#
# USAGE:   deploy/scripts/build-push-orchestrator-rs-amd64.sh
# ENV:
#   REPO               image repo (default aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs)
#   PLATFORM           linux/amd64 (default) or linux/arm64
#   RUNTIME_IMAGE      base runtime image (default debian:bookworm-slim)
#   DEPLOY_EXTRA_ARGS  extra args forwarded to deploy.sh (e.g. "--no-cache")
#   SKIP_PUSH=1        build locally only, do not push
#
set -euo pipefail

REPO="${REPO:-aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs}"
PLATFORM="${PLATFORM:-linux/amd64}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-public.ecr.aws/docker/library/debian:bookworm-slim}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_SH="$REPO_ROOT/deploy/deploy.sh"
DOCKERFILE="$REPO_ROOT/deploy/docker/orchestrator-rs-amd64.Dockerfile"
REGISTRY_HOST="${REPO%%/*}"            # aisec-repo.jd.com
REGISTRY_PREFIX="${REPO%/*}"           # aisec-repo.jd.com/joysafeter
IMAGE_NAME="${REPO##*/}"               # joysafeter-orchestrator-rs

case "$PLATFORM" in
  linux/amd64) ARCH=amd64; TARGET=x86_64-unknown-linux-gnu ;;
  linux/arm64) ARCH=arm64; TARGET=aarch64-unknown-linux-gnu ;;
  *) echo "unsupported PLATFORM=$PLATFORM" >&2; exit 1 ;;
esac

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- preflight ------------------------------------------------------------- #
command -v docker >/dev/null || die "docker not found on PATH"
docker info >/dev/null 2>&1 || die "docker daemon not responding"
[ -x "$DEPLOY_SH" ] || die "deploy.sh not found or not executable: $DEPLOY_SH"
[ -f "$DOCKERFILE" ] || die "missing $DOCKERFILE"
grep -q "\"$REGISTRY_HOST\"" "$HOME/.docker/config.json" 2>/dev/null \
  || die "no stored auth for $REGISTRY_HOST — run: docker login $REGISTRY_HOST"

# --- 1) cross-compile the binary (cargo zigbuild, via deploy.sh) ----------- #
log "compiling $PLATFORM binary (cargo zigbuild)"
# shellcheck disable=SC2086
ORCHESTRATOR_RS_IMAGE="$IMAGE_NAME" \
  "$DEPLOY_SH" build --orchestrator-only --arch "$ARCH" \
    --registry "$REGISTRY_PREFIX" --tag latest ${DEPLOY_EXTRA_ARGS:-}

BINARY="$REPO_ROOT/target/$TARGET/release/joysafeter-orchestrator"
[ -x "$BINARY" ] || die "expected compiled binary missing: $BINARY"

# --- 2) package a PLAIN single-arch image ---------------------------------- #
log "packaging plain $PLATFORM image: $REPO:latest"
docker build --provenance=false --platform "$PLATFORM" \
  -f "$DOCKERFILE" \
  --build-arg "TARGET=$TARGET" \
  --build-arg "RUNTIME_IMAGE=$RUNTIME_IMAGE" \
  -t "$REPO:latest" \
  "$REPO_ROOT"

img_media="$(docker image inspect "$REPO:latest" --format '{{.Descriptor.MediaType}}' 2>/dev/null || true)"
case "$img_media" in
  *image.index*|*manifest.list*) die "local $REPO:latest is an index ($img_media) — expected a plain image" ;;
  "") die "could not read local $REPO:latest media type" ;;
esac

if [ "${SKIP_PUSH:-0}" = "1" ]; then
  log "SKIP_PUSH=1 — built locally only, not pushing"
  exit 0
fi

# --- 3) push via the host daemon ------------------------------------------- #
log "pushing $REPO:latest"
push_out="$(docker push "$REPO:latest" 2>&1)"; printf '%s\n' "$push_out"
DIGEST="$(printf '%s\n' "$push_out" | sed -nE 's/.*digest: (sha256:[0-9a-f]{64}).*/\1/p' | tail -1)"
[ -n "$DIGEST" ] || die "could not parse pushed digest from push output"

log "DONE — $REPO:latest @ $DIGEST ($PLATFORM, plain single-arch image)"
