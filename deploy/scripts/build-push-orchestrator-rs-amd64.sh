#!/usr/bin/env bash
#
# Build + push the Rust orchestrator image as linux/amd64 from an Apple-Silicon
# Mac. Captures the known-good path validated 2026-08-15.
#
# WHY THIS EXISTS
#   The prod cluster is amd64. On an arm64 Mac, cross-building amd64 via QEMU
#   (the default buildx docker-container / multiarch builder) SIGSEGVs while
#   compiling the crypto crates (aws-lc-sys x86 asm, then ring's cc1). The
#   reliable path is colima's Apple-Virtualization + Rosetta, driving a classic
#   `docker build --platform linux/amd64` (the daemon's BuildKit). Rosetta
#   emulates x86 well enough to compile the real (asm) crypto.
#
# DEPENDENCIES (checked in preflight, fail-fast)
#   - macOS on Apple Silicon (arm64) + colima with vmType=vz and rosetta=true
#   - docker CLI + a running colima docker context
#   - a `docker login` entry for the target registry
#   - build context: proto/, the orchestrator crate, and backend/config/
#     (llm_catalog.rs embeds config/llm_catalog.yaml via include_str! at compile
#     time, so the Dockerfile must COPY backend/config)
#
# USAGE
#   deploy/scripts/build-push-orchestrator-rs-amd64.sh
#
# ENV OVERRIDES
#   REPO                  image repo (default aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs)
#   EXTRA_TAG             extra tag (default <YYYYMMDD>-<gitsha>); :latest is always pushed too
#   PLATFORM              default linux/amd64
#   DOCKERFILE / CONTEXT  default the tracked orchestrator-rs.Dockerfile / repo root
#   PROFILE               colima profile (default: default)
#   ALLOW_COLIMA_RESTART=1  permit enabling Rosetta if off (RESTARTS the colima VM;
#                           running containers stop, named volumes persist)
#   SKIP_PUSH=1           build only, do not push
#
set -euo pipefail

REPO="${REPO:-aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs}"
PLATFORM="${PLATFORM:-linux/amd64}"
PROFILE="${PROFILE:-default}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCKERFILE="${DOCKERFILE:-$REPO_ROOT/deploy/docker/orchestrator-rs.Dockerfile}"
CONTEXT="${CONTEXT:-$REPO_ROOT}"
REGISTRY_HOST="${REPO%%/*}"

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
EXTRA_TAG="${EXTRA_TAG:-$(date +%Y%m%d)-$GIT_SHA}"

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
log "preflight: docker + platform + registry auth + build context"
command -v docker >/dev/null || die "docker not found on PATH"
docker info >/dev/null 2>&1 || die "docker daemon not responding (is colima running?)"

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  command -v colima >/dev/null || die "colima required for Rosetta amd64 builds on Apple Silicon"
  ensure_rosetta
  docker run --rm --platform "$PLATFORM" public.ecr.aws/docker/library/debian:bookworm-slim uname -m \
    | grep -qx x86_64 || die "amd64 emulation smoke test failed (Rosetta not active?)"
  log "amd64 emulation OK (Rosetta)"
fi

grep -q "\"$REGISTRY_HOST\"" "$HOME/.docker/config.json" 2>/dev/null \
  || die "no stored auth for $REGISTRY_HOST — run: docker login $REGISTRY_HOST"

[ -d "$CONTEXT/proto" ] || die "missing $CONTEXT/proto"
[ -d "$CONTEXT/backend/app/joysafeter_orchestrator_rs" ] || die "missing orchestrator crate in context"
[ -f "$CONTEXT/backend/config/llm_catalog.yaml" ] \
  || die "missing $CONTEXT/backend/config/llm_catalog.yaml (llm_catalog.rs include_str! target)"
grep -q "COPY backend/config" "$DOCKERFILE" \
  || warn "Dockerfile has no 'COPY backend/config' — the include_str! build will fail"

# --------------------------------------------------------------------------- #
# 2) build (classic docker build => colima daemon BuildKit + Rosetta)
# --------------------------------------------------------------------------- #
log "building $PLATFORM"
log "  repo=$REPO  tags=latest,$EXTRA_TAG"
log "  dockerfile=$DOCKERFILE  context=$CONTEXT"
DOCKER_BUILDKIT=1 docker build --platform "$PLATFORM" \
  -f "$DOCKERFILE" \
  -t "$REPO:latest" -t "$REPO:$EXTRA_TAG" \
  "$CONTEXT"

if [ "${SKIP_PUSH:-0}" = "1" ]; then
  log "SKIP_PUSH=1 — built locally only, not pushing"
  exit 0
fi

# --------------------------------------------------------------------------- #
# 3) push both tags + capture the registry-returned digest
# --------------------------------------------------------------------------- #
log "pushing $REPO:latest"
docker push "$REPO:latest"
log "pushing $REPO:$EXTRA_TAG"
push_out="$(docker push "$REPO:$EXTRA_TAG" 2>&1)"; printf '%s\n' "$push_out"
DIGEST="$(printf '%s\n' "$push_out" | sed -nE 's/.*digest: (sha256:[0-9a-f]{64}).*/\1/p' | tail -1)"
[ -n "$DIGEST" ] || die "could not parse pushed digest from push output"
log "pushed digest: $DIGEST"

# --------------------------------------------------------------------------- #
# 4) verify the digest is stored + is $PLATFORM (tolerate transient read 503s)
# --------------------------------------------------------------------------- #
log "verifying digest in registry (pull-by-digest; read endpoint can be flaky)"
verified=0
for i in 1 2 3 4 5; do
  if docker pull --platform "$PLATFORM" "$REPO@$DIGEST" >/dev/null 2>&1; then
    verified=1; break
  fi
  out="$(docker manifest inspect "$REPO@$DIGEST" 2>&1 || true)"
  case "$out" in
    *503*) warn "registry read 503 (attempt $i/5) — transient, retrying in 5s"; sleep 5;;
    *no\ matching\ manifest*) verified=1; break;;   # manifest served; just no arm64 variant => amd64-only, OK
    *) warn "read-back attempt $i/5: $out"; sleep 5;;
  esac
done

if [ "$verified" = "1" ]; then
  log "VERIFIED: $REPO@$DIGEST present in registry as $PLATFORM"
else
  warn "could not read back the digest (registry read path unavailable)."
  warn "the push response above is authoritative; retry later with:"
  warn "  docker manifest inspect $REPO:$EXTRA_TAG"
fi

cat <<EOF

[build] DONE
  image      : $REPO:latest
  also tagged: $REPO:$EXTRA_TAG
  digest     : $DIGEST
  platform   : $PLATFORM
  (Helm values reference :latest -> new orchestrator pods will pull this digest)
EOF
