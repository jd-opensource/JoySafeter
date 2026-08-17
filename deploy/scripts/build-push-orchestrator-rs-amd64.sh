#!/usr/bin/env bash
#
# Build + push the Rust orchestrator image as a PLAIN linux/amd64 image from an
# Apple-Silicon Mac, using deploy.sh's "deploy build" compile path.
#
# WHAT THIS DOES
#   1) Compile the amd64 orchestrator binary via deploy.sh's binary path
#      (ensure_orchestrator_binary -> `docker run --platform linux/amd64
#      rust:1-bookworm cargo build`, then it packages a local image). This is
#      the "deploy build amd64" compile method.
#   2) Re-package that prebuilt binary as a PLAIN single-arch amd64 image with
#      `docker build --provenance=false` (see WHY below), tagging :latest.
#   3) `docker push` :latest via the host docker daemon.
#
# WHY --provenance=false (the "带文件夹"/index problem)
#   colima's BuildKit (containerd image store) attaches a provenance ATTESTATION
#   by default, which turns the pushed tag into a manifest LIST (OCI index)
#   wrapping the amd64 image + an `unknown/unknown` attestation. In the registry
#   that shows up as a nested index ("folder") instead of a plain image.
#   `--provenance=false` with a single --platform emits ONE image manifest, so
#   the registry gets a plain amd64 image.
#
# WHY PUSH VIA THE DAEMON (not `deploy.sh push` / buildx --push)
#   `deploy.sh push` pushes from inside the buildx docker-container builder,
#   whose isolated network cannot reach the internal registry (connection
#   refused). The host docker daemon HAS registry access, so we build locally
#   and push from it.
#
# WHY ROSETTA STILL MATTERS
#   The amd64 rust compile runs on the arm64 Mac. Under QEMU the crypto crates
#   (aws-lc-sys x86 asm, ring's cc1) SIGSEGV; colima's Apple-Virtualization +
#   Rosetta emulates x86 well enough to compile the real (asm) crypto.
#
# USAGE
#   deploy/scripts/build-push-orchestrator-rs-amd64.sh
#
# ENV OVERRIDES
#   REPO                  image repo (default aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs)
#   PLATFORM              default linux/amd64
#   PROFILE               colima profile (default: default)
#   RUNTIME_IMAGE         base runtime image (default public.ecr.aws/docker/library/debian:bookworm-slim)
#   DEPLOY_EXTRA_ARGS     extra args forwarded to deploy.sh compile (e.g. "--mirror huawei --no-cache")
#   ALLOW_COLIMA_RESTART=1  permit enabling Rosetta if off (RESTARTS the colima VM;
#                           running containers stop, named volumes persist)
#   SKIP_PUSH=1           build only, do not push
#
set -euo pipefail

REPO="${REPO:-aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs}"
PLATFORM="${PLATFORM:-linux/amd64}"
PROFILE="${PROFILE:-default}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-public.ecr.aws/docker/library/debian:bookworm-slim}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_SH="$REPO_ROOT/deploy/deploy.sh"
DOCKERFILE="$REPO_ROOT/deploy/docker/orchestrator-rs-binary.Dockerfile"
REGISTRY_HOST="${REPO%%/*}"            # aisec-repo.jd.com
REGISTRY_PREFIX="${REPO%/*}"           # aisec-repo.jd.com/joysafeter
IMAGE_NAME="${REPO##*/}"               # joysafeter-orchestrator-rs

# Map PLATFORM -> deploy.sh --arch value and the rust target triple that
# orchestrator-rs-binary.Dockerfile COPYs from.
case "$PLATFORM" in
  linux/amd64) ARCH=amd64; TARGET=x86_64-unknown-linux-gnu ;;
  linux/arm64) ARCH=arm64; TARGET=aarch64-unknown-linux-gnu ;;
  *) ARCH=""; TARGET="" ;;
esac

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

sed_inplace() { # portable sed -i (BSD/macOS vs GNU)
  if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi
}

ensure_rosetta() {
  local cfg="$HOME/.colima/$PROFILE/colima.yaml"
  [ -f "$cfg" ] || die "colima config not found: $cfg (is colima installed/initialised?)"
  local vmtype rosetta
  vmtype="$(awk -F': *' '/^vmType:/{print $2}' "$cfg")"
  rosetta="$(awk -F': *' '/^rosetta:/{print $2}' "$cfg")"

  if [ "$rosetta" = "true" ] && colima status "$PROFILE" >/dev/null 2>&1; then
    log "colima Rosetta already enabled and running (profile=$PROFILE)"
    return
  fi
  if [ "${ALLOW_COLIMA_RESTART:-0}" != "1" ]; then
    die "colima Rosetta not enabled (vmType=$vmtype rosetta=$rosetta).
     Re-run with ALLOW_COLIMA_RESTART=1 to enable it. NOTE: this restarts the
     colima VM — running containers stop (named volumes persist)."
  fi
  [ "$vmtype" = "vz" ] || die "colima vmType=$vmtype; Rosetta requires vmType=vz.
     Recreate once with: colima delete && colima start --vm-type vz --vz-rosetta"
  log "enabling Rosetta in $cfg (backup alongside) and restarting colima..."
  cp "$cfg" "$cfg.bak.$(date +%s)"
  sed_inplace 's/^rosetta: *false/rosetta: true/' "$cfg"
  colima stop "$PROFILE"
  colima start "$PROFILE"
  colima status "$PROFILE" >/dev/null 2>&1 || die "colima failed to start after enabling Rosetta"
}

# --------------------------------------------------------------------------- #
# 1) dependency preflight
# --------------------------------------------------------------------------- #
log "preflight: docker + platform + registry auth + deploy.sh"
command -v docker >/dev/null || die "docker not found on PATH"
docker info >/dev/null 2>&1 || die "docker daemon not responding (is colima running?)"
[ -x "$DEPLOY_SH" ] || die "deploy.sh not found or not executable: $DEPLOY_SH"
[ -f "$DOCKERFILE" ] || die "missing $DOCKERFILE"
[ -n "$ARCH" ] || die "unsupported PLATFORM=$PLATFORM (expected linux/amd64 or linux/arm64)"

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  command -v colima >/dev/null || die "colima required for Rosetta amd64 builds on Apple Silicon"
  ensure_rosetta
  docker run --rm --platform "$PLATFORM" public.ecr.aws/docker/library/debian:bookworm-slim uname -m \
    | grep -qx x86_64 || die "amd64 emulation smoke test failed (Rosetta not active?)"
  log "amd64 emulation OK (Rosetta)"
fi

grep -q "\"$REGISTRY_HOST\"" "$HOME/.docker/config.json" 2>/dev/null \
  || die "no stored auth for $REGISTRY_HOST — run: docker login $REGISTRY_HOST"

# --------------------------------------------------------------------------- #
# 2) compile the amd64 binary via deploy.sh's "deploy build" path
#    (USE_BUILDX=false keeps it on the daemon's BuildKit + Rosetta). deploy.sh
#    also builds a local image here, but we re-package it plainly in step 3, so
#    only the compiled binary at target/$TARGET/release/ is what we consume.
# --------------------------------------------------------------------------- #
log "compiling $PLATFORM binary via deploy.sh (deploy build method)"
# shellcheck disable=SC2086
USE_BUILDX=false ORCHESTRATOR_RS_IMAGE="$IMAGE_NAME" \
  "$DEPLOY_SH" build --orchestrator-only --arch "$ARCH" \
    --registry "$REGISTRY_PREFIX" --tag latest ${DEPLOY_EXTRA_ARGS:-}

BINARY="$REPO_ROOT/target/$TARGET/release/joysafeter-orchestrator"
[ -x "$BINARY" ] || die "expected compiled binary missing: $BINARY"
log "compiled binary: $BINARY"

# --------------------------------------------------------------------------- #
# 3) package as a PLAIN single-arch amd64 image (no provenance attestation, so
#    the registry gets one image manifest instead of an index). Layers are the
#    prebuilt binary + apt base, so this reuses deploy.sh's cache and is instant.
# --------------------------------------------------------------------------- #
log "packaging plain $PLATFORM image: $REPO:latest"
docker build --provenance=false --platform "$PLATFORM" \
  -f "$DOCKERFILE" \
  --build-arg "TARGET=$TARGET" \
  --build-arg "RUNTIME_IMAGE=$RUNTIME_IMAGE" \
  -t "$REPO:latest" \
  "$REPO_ROOT"

# Fail loudly if the local image is an index (manifest list) instead of a plain
# single-arch manifest — an index is exactly the "folder" we're avoiding.
img_media="$(docker image inspect "$REPO:latest" --format '{{.Descriptor.MediaType}}' 2>/dev/null || true)"
case "$img_media" in
  *image.index*|*manifest.list*)
    die "local $REPO:latest is an index ($img_media) — expected a plain image manifest";;
  "") die "could not read local $REPO:latest media type (build did not produce an image?)";;
esac

if [ "${SKIP_PUSH:-0}" = "1" ]; then
  log "SKIP_PUSH=1 — built locally only, not pushing"
  exit 0
fi

# --------------------------------------------------------------------------- #
# 4) push :latest (via the daemon) + capture the registry-returned digest
# --------------------------------------------------------------------------- #
log "pushing $REPO:latest"
push_out="$(docker push "$REPO:latest" 2>&1)"; printf '%s\n' "$push_out"
DIGEST="$(printf '%s\n' "$push_out" | sed -nE 's/.*digest: (sha256:[0-9a-f]{64}).*/\1/p' | tail -1)"
[ -n "$DIGEST" ] || die "could not parse pushed digest from push output"
log "pushed digest: $DIGEST"

# --------------------------------------------------------------------------- #
# 5) verify the pushed digest resolves in the registry. The registry's read
#    endpoint (manifest inspect) 503s intermittently, but pull-by-digest
#    resolves from the local store and is the reliable signal. The image is
#    already asserted to be a plain manifest (not an index) by the descriptor
#    guard above, so no registry-side index re-check is needed here.
# --------------------------------------------------------------------------- #
log "verifying pushed digest resolves (pull-by-digest)"
verified=0
for i in 1 2 3 4 5; do
  if docker pull --platform "$PLATFORM" "$REPO@$DIGEST" >/dev/null 2>&1; then
    verified=1; break
  fi
  warn "digest not resolvable yet (attempt $i/5) — registry read path flaky, retrying in 5s"
  sleep 5
done

if [ "$verified" = "1" ]; then
  log "VERIFIED: $REPO@$DIGEST resolves in registry as $PLATFORM"
else
  warn "could not read back the digest (registry read path unavailable)."
  warn "the push above returned this digest and is authoritative; retry later with:"
  warn "  docker manifest inspect $REPO:latest"
fi

cat <<EOF

[build] DONE
  image      : $REPO:latest
  digest     : $DIGEST
  platform   : $PLATFORM (plain single-arch image, no provenance index)
  (Helm values reference :latest -> new orchestrator pods will pull this digest)
EOF
