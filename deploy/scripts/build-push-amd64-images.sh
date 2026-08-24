#!/usr/bin/env bash
#
# Build + push JoySafeter linux/amd64 images as PLAIN image manifests from an
# Apple-Silicon Mac / Colima daemon.
#
# This script started as the Rust orchestrator amd64 workaround. It now supports
# the same plain-image, host-daemon push path for:
#   - orchestrator  -> joysafeter-orchestrator-rs
#   - native        -> joysafeter-native
#   - pi            -> joysafeter-pi
#
# WHAT THIS DOES
#   1) For images that need a local Rust binary first, reuse deploy.sh's daemon
#      compile path (`docker run --platform ... rust:1-bookworm cargo build`).
#   2) Re-package/build each selected image as a PLAIN linux/amd64 image with
#      `docker build --provenance=false`.
#   3) `docker push` via the host docker daemon, avoiding buildx-container
#      network isolation and the registry "folder"/index problem.
#
# WHY --provenance=false (the "带文件夹"/index problem)
#   colima's BuildKit (containerd image store) attaches a provenance ATTESTATION
#   by default, which turns the pushed tag into a manifest LIST (OCI index)
#   wrapping the real image + an `unknown/unknown` attestation. In the registry
#   that shows up as a nested index ("folder") instead of a plain image.
#   `--provenance=false` with a single --platform emits ONE image manifest.
#
# WHY PUSH VIA THE DAEMON (not `deploy.sh push` / buildx --push)
#   `deploy.sh push` pushes from inside the buildx docker-container builder,
#   whose isolated network may not reach the internal registry. The host docker
#   daemon has registry access, so this script builds locally and pushes from it.
#
# WHY ROSETTA STILL MATTERS
#   amd64 Rust compiles on arm64 Macs are fragile under QEMU for crypto crates
#   (aws-lc-sys x86 asm, ring's cc1). Colima Apple-Virtualization + Rosetta
#   emulates x86 well enough to compile the real asm crypto.
#
# USAGE
#   # Default: build/push orchestrator + native + pi for linux/amd64
#   deploy/scripts/build-push-amd64-images.sh
#
#   # Select explicit targets
#   deploy/scripts/build-push-amd64-images.sh orchestrator native
#   TARGETS=native,pi deploy/scripts/build-push-amd64-images.sh
#   TARGETS=orchestrator deploy/scripts/build-push-amd64-images.sh
#
# ENV OVERRIDES
#   TARGETS / IMAGES       target list: orchestrator,native,pi,all
#   REPO                   backward-compatible orchestrator repo override
#   REGISTRY_PREFIX        default image prefix (default derived from REPO)
#   ORCHESTRATOR_REPO      full repo for orchestrator image
#   NATIVE_REPO            full repo for native image
#   PI_REPO                full repo for pi image
#   PLATFORM               fixed/default linux/amd64; other values fail
#   TAG / IMAGE_TAG        default latest
#   PROFILE                colima profile (default: default)
#   BASE_IMAGE_REGISTRY    default public.ecr.aws/docker/library/
#   RUNTIME_IMAGE          orchestrator runtime base image
#   RUST_IMAGE             rust compile image for deploy.sh paths
#   PIP_INDEX_URL          pi pip mirror build arg
#   NPM_REGISTRY           pi npm registry build arg
#   DEPLOY_EXTRA_ARGS      extra args forwarded to deploy.sh compile paths
#                          (e.g. "--mirror huawei --no-cache")
#   ALLOW_COLIMA_RESTART=1 permit enabling Rosetta if off (RESTARTS colima)
#   NO_CACHE=1             disable docker build cache for plain packaging
#   SKIP_PUSH=1            build only, do not push
#   SKIP_VERIFY=1          skip pull-by-digest verification after push
#
if [ -z "${BASH_VERSION:-}" ]; then
  printf '\033[1;31m[error]\033[0m this script requires bash; run: bash %s %s\n' "$0" "${*:-}" >&2
  exit 1
fi

set -euo pipefail

DEFAULT_ORCHESTRATOR_REPO="${REPO:-aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs}"
REGISTRY_PREFIX="${REGISTRY_PREFIX:-${DEFAULT_ORCHESTRATOR_REPO%/*}}"

ORCHESTRATOR_REPO="${ORCHESTRATOR_REPO:-$DEFAULT_ORCHESTRATOR_REPO}"
NATIVE_REPO="${NATIVE_REPO:-$REGISTRY_PREFIX/joysafeter-native}"
PI_REPO="${PI_REPO:-$REGISTRY_PREFIX/joysafeter-pi}"

PLATFORM="${PLATFORM:-linux/amd64}"
TAG="${TAG:-${IMAGE_TAG:-latest}}"
PROFILE="${PROFILE:-default}"

BASE_IMAGE_REGISTRY="${BASE_IMAGE_REGISTRY:-public.ecr.aws/docker/library/}"
RUST_IMAGE="${RUST_IMAGE:-${BASE_IMAGE_REGISTRY}rust:1-bookworm}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-${BASE_IMAGE_REGISTRY}debian:bookworm-slim}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
UV_INDEX_URL="${UV_INDEX_URL:-$PIP_INDEX_URL}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_SH="$REPO_ROOT/deploy/deploy.sh"
ORCHESTRATOR_DOCKERFILE="$REPO_ROOT/deploy/docker/orchestrator-rs-amd64.Dockerfile"
PI_DOCKERFILE="$REPO_ROOT/deploy/docker/pi-amd64.Dockerfile"

case "$PLATFORM" in
  linux/amd64) ARCH=amd64; TARGET_TRIPLE=x86_64-unknown-linux-gnu; EXPECTED_UNAME=x86_64; EXPECTED_DOCKER_ARCH=amd64 ;;
  *) ARCH=""; TARGET_TRIPLE=""; EXPECTED_UNAME=""; EXPECTED_DOCKER_ARCH="" ;;
esac

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

show_usage() {
  cat <<EOF
Usage: $0 [orchestrator|native|pi|all ...]

Defaults:
  TARGETS=${TARGETS:-${IMAGES:-orchestrator,native,pi}}
  PLATFORM=$PLATFORM
  TAG=$TAG

Examples:
  $0
  $0 orchestrator native
  TARGETS=native,pi $0
  TARGETS=orchestrator SKIP_PUSH=1 $0
EOF
}

sed_inplace() { # portable sed -i (BSD/macOS vs GNU)
  if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi
}

compute_git_commit_sha() {
  if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    local sha
    sha="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then
      sha="${sha}-dirty"
    fi
    printf '%s' "$sha"
  else
    printf 'unknown'
  fi
}

GIT_COMMIT_SHA="${GIT_COMMIT_SHA:-$(compute_git_commit_sha)}"

normalize_targets() {
  local raw="$*"
  raw="${raw//,/ }"
  local expanded="" token

  for token in $raw; do
    case "$token" in
      all) expanded="$expanded orchestrator native pi" ;;
      orchestrator|orchestrator-rs|orchestrator_rs) expanded="$expanded orchestrator" ;;
      native|pi) expanded="$expanded $token" ;;
      "") ;;
      -h|--help) show_usage; exit 0 ;;
      *) die "unknown target: $token (expected orchestrator/native/pi/all)" ;;
    esac
  done

  local deduped="" target
  for target in $expanded; do
    case " $deduped " in
      *" $target "*) ;;
      *) deduped="$deduped $target" ;;
    esac
  done

  printf '%s' "${deduped# }"
}

native_dockerfile() {
  case "$PLATFORM" in
    linux/amd64) echo "$REPO_ROOT/deploy/docker/native-amd64.Dockerfile" ;;
    *) die "this amd64 script only supports PLATFORM=linux/amd64, got $PLATFORM" ;;
  esac
}

repo_image_name() {
  local repo=$1
  echo "${repo##*/}"
}

repo_prefix() {
  local repo=$1
  if [ "${repo%/*}" = "$repo" ]; then
    echo ""
  else
    echo "${repo%/*}"
  fi
}

registry_host_for_repo() {
  local repo=$1 first
  first="${repo%%/*}"
  if [ "$first" != "$repo" ] && { [[ "$first" == *.* ]] || [[ "$first" == *:* ]] || [ "$first" = "localhost" ]; }; then
    echo "$first"
  fi
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

ensure_registry_auth() {
  local host=$1
  [ -n "$host" ] || return 0
  grep -q "\"$host\"" "$HOME/.docker/config.json" 2>/dev/null \
    || die "no stored auth for $host — run: docker login $host"
}

preflight() {
  log "preflight: docker + platform + registry auth + deploy.sh"
  command -v docker >/dev/null || die "docker not found on PATH"
  docker info >/dev/null 2>&1 || die "docker daemon not responding (is colima running?)"
  [ -x "$DEPLOY_SH" ] || die "deploy.sh not found or not executable: $DEPLOY_SH"
  [ -n "$ARCH" ] || die "unsupported PLATFORM=$PLATFORM (this script is amd64-only; expected linux/amd64)"

  local target dockerfile repo host seen_hosts=""
  for target in $SELECTED_TARGETS; do
    case "$target" in
      orchestrator) dockerfile="$ORCHESTRATOR_DOCKERFILE"; repo="$ORCHESTRATOR_REPO" ;;
      native) dockerfile="$(native_dockerfile)"; repo="$NATIVE_REPO" ;;
      pi) dockerfile="$PI_DOCKERFILE"; repo="$PI_REPO" ;;
      *) die "internal error: unhandled target $target" ;;
    esac
    [ -f "$dockerfile" ] || die "missing Dockerfile for $target: $dockerfile"
    host="$(registry_host_for_repo "$repo")"
    if [ -n "$host" ]; then
      case " $seen_hosts " in
        *" $host "*) ;;
        *) ensure_registry_auth "$host"; seen_hosts="$seen_hosts $host" ;;
      esac
    fi
  done

  if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] && [ "$PLATFORM" = "linux/amd64" ]; then
    command -v colima >/dev/null || die "colima required for Rosetta amd64 builds on Apple Silicon"
    ensure_rosetta
    docker run --rm --platform "$PLATFORM" "$RUNTIME_IMAGE" uname -m \
      | grep -qx "$EXPECTED_UNAME" || die "amd64 emulation smoke test failed (Rosetta not active?)"
    log "amd64 emulation OK (Rosetta)"
  fi
}

elf_binary_arch() {
  local file=$1 byte
  [ -f "$file" ] || { echo "missing"; return; }
  byte="$(od -An -tx1 -j 18 -N 1 "$file" 2>/dev/null | tr -d '[:space:]')"
  case "$byte" in
    3e) echo "x86_64" ;;
    b7) echo "aarch64" ;;
    *) echo "unknown" ;;
  esac
}

compile_orchestrator_binary() {
  local repo=$1 image_name deploy_registry
  image_name="$(repo_image_name "$repo")"
  deploy_registry="$(repo_prefix "$repo")"

  local registry_args=()
  if [ -n "$deploy_registry" ]; then
    registry_args=(--registry "$deploy_registry")
  fi

  log "compiling $PLATFORM orchestrator binary via deploy.sh"
  # shellcheck disable=SC2086
  USE_BUILDX=false \
  BASE_IMAGE_REGISTRY="$BASE_IMAGE_REGISTRY" \
  RUST_IMAGE="$RUST_IMAGE" \
  RUNTIME_IMAGE="$RUNTIME_IMAGE" \
  PIP_INDEX_URL="$PIP_INDEX_URL" \
  UV_INDEX_URL="$UV_INDEX_URL" \
  ORCHESTRATOR_RS_IMAGE="$image_name" \
    "$DEPLOY_SH" build --orchestrator-only --arch "$ARCH" \
      "${registry_args[@]}" --tag "$TAG" ${DEPLOY_EXTRA_ARGS:-}
  [ -x "$REPO_ROOT/target/$TARGET_TRIPLE/release/joysafeter-orchestrator" ] \
    || die "expected compiled binary missing: $REPO_ROOT/target/$TARGET_TRIPLE/release/joysafeter-orchestrator"
}

ensure_runtime_runner_binary() {
  local output="$REPO_ROOT/target/$TARGET_TRIPLE/release/joysafeter-runner"

  if [ -x "$output" ] && [ "${FORCE_RUNNER_REBUILD:-0}" != "1" ]; then
    local disk_arch expected_arch newer_src
    disk_arch="$(elf_binary_arch "$output")"
    expected_arch="${TARGET_TRIPLE%%-*}"
    if [ "$disk_arch" != "$expected_arch" ]; then
      warn "existing runner binary arch is $disk_arch, expected $expected_arch ($TARGET_TRIPLE); rebuilding"
    else
      newer_src="$(find "$REPO_ROOT/sandbox-runner" -type f \
        \( -name '*.rs' -o -name 'Cargo.toml' -o -name 'Cargo.lock' \) \
        -newer "$output" -print -quit 2>/dev/null)"
      if [ -z "$newer_src" ]; then
        log "runtime runner binary already current: $output"
        return
      fi
      log "sandbox-runner sources changed; rebuilding runtime runner"
    fi
  fi

  log "compiling $PLATFORM runtime runner directly (native target; no orchestrator)"
  docker run --rm \
    --platform "$PLATFORM" \
    -v "$REPO_ROOT:/workspace" \
    -v joysafeter-cargo-registry:/usr/local/cargo/registry \
    -v joysafeter-cargo-git:/usr/local/cargo/git \
    -w /workspace/sandbox-runner \
    "$RUST_IMAGE" \
    bash -lc "export PATH=/usr/local/cargo/bin:\$PATH CARGO_HTTP_TIMEOUT=600 CARGO_HTTP_MULTIPLEXING=false CARGO_NET_RETRY=10 CARGO_BUILD_JOBS=1 && apt-get update && apt-get install -y --no-install-recommends protobuf-compiler pkg-config && if command -v rustup >/dev/null 2>&1; then rustup target add $TARGET_TRIPLE; fi && cargo build --release --target $TARGET_TRIPLE -p joysafeter-runner && mkdir -p /workspace/target/$TARGET_TRIPLE/release && cp target/$TARGET_TRIPLE/release/joysafeter-runner /workspace/target/$TARGET_TRIPLE/release/joysafeter-runner"
  chmod +x "$output"
  log "runtime runner binary compiled: $output"
}

plain_build() {
  local label=$1 repo=$2 dockerfile=$3 context=$4
  shift 4

  local image="$repo:$TAG"
  local build_flags=(--provenance=false --platform "$PLATFORM" -f "$dockerfile")
  if [ "${NO_CACHE:-0}" = "1" ] || [ "${NO_CACHE:-false}" = "true" ]; then
    build_flags+=(--no-cache)
  fi

  log "packaging plain $PLATFORM $label image: $image"
  docker build "${build_flags[@]}" "$@" -t "$image" "$context"

  assert_plain_image "$image"
}

assert_plain_image() {
  local image=$1 img_media actual_arch
  img_media="$(docker image inspect "$image" --format '{{.Descriptor.MediaType}}' 2>/dev/null || true)"
  case "$img_media" in
    *image.index*|*manifest.list*)
      die "local $image is an index ($img_media) — expected a plain image manifest" ;;
    ""|"<no value>")
      warn "could not read local $image descriptor media type; checking architecture only" ;;
  esac

  actual_arch="$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)"
  [ "$actual_arch" = "$EXPECTED_DOCKER_ARCH" ] \
    || die "local $image architecture is $actual_arch — expected $EXPECTED_DOCKER_ARCH"
}

push_and_verify() {
  local repo=$1 image="$repo:$TAG" push_out digest verified i
  PUSH_DIGEST=""

  if [ "${SKIP_PUSH:-0}" = "1" ]; then
    log "SKIP_PUSH=1 — built locally only, not pushing $image"
    PUSH_DIGEST="local-only"
    return
  fi

  log "pushing $image"
  push_out="$(docker push "$image" 2>&1)"; printf '%s\n' "$push_out"
  digest="$(printf '%s\n' "$push_out" | sed -nE 's/.*digest: (sha256:[0-9a-f]{64}).*/\1/p' | tail -1)"
  [ -n "$digest" ] || die "could not parse pushed digest from push output for $image"
  log "pushed digest for $image: $digest"

  if [ "${SKIP_VERIFY:-0}" = "1" ]; then
    PUSH_DIGEST="$digest"
    return
  fi

  log "verifying pushed digest resolves (pull-by-digest): $repo@$digest"
  verified=0
  for i in 1 2 3 4 5; do
    if docker pull --platform "$PLATFORM" "$repo@$digest" >/dev/null 2>&1; then
      verified=1; break
    fi
    warn "digest not resolvable yet for $repo (attempt $i/5) — retrying in 5s"
    sleep 5
  done

  if [ "$verified" = "1" ]; then
    log "VERIFIED: $repo@$digest resolves in registry as $PLATFORM"
  else
    warn "could not read back $repo@$digest (registry read path unavailable)."
    warn "the push returned this digest and is authoritative; retry later with:"
    warn "  docker manifest inspect $image"
  fi

  PUSH_DIGEST="$digest"
}

build_orchestrator() {
  compile_orchestrator_binary "$ORCHESTRATOR_REPO"
  plain_build "orchestrator" "$ORCHESTRATOR_REPO" "$ORCHESTRATOR_DOCKERFILE" "$REPO_ROOT" \
    --build-arg "TARGET=$TARGET_TRIPLE" \
    --build-arg "RUNTIME_IMAGE=$RUNTIME_IMAGE"
}

build_native() {
  ensure_runtime_runner_binary
  plain_build "native" "$NATIVE_REPO" "$(native_dockerfile)" "$REPO_ROOT" \
    --build-arg "BASE_IMAGE_REGISTRY=$BASE_IMAGE_REGISTRY"
}

build_pi() {
  ensure_runtime_runner_binary
  local build_args=(
    --build-arg "BASE_IMAGE_REGISTRY=$BASE_IMAGE_REGISTRY"
    --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL"
    --build-arg "NPM_REGISTRY=$NPM_REGISTRY"
    --build-arg "GIT_COMMIT_SHA=$GIT_COMMIT_SHA"
  )

  [ -n "${PI_VERSION:-}" ] && build_args+=(--build-arg "PI_VERSION=$PI_VERSION")
  [ -n "${RUST_VERSION:-}" ] && build_args+=(--build-arg "RUST_VERSION=$RUST_VERSION")
  [ -n "${NODE_VERSION:-}" ] && build_args+=(--build-arg "NODE_VERSION=$NODE_VERSION")
  [ -n "${PYTHON_VERSION:-}" ] && build_args+=(--build-arg "PYTHON_VERSION=$PYTHON_VERSION")
  [ -n "${UV_VERSION:-}" ] && build_args+=(--build-arg "UV_VERSION=$UV_VERSION")
  [ -n "${YARN_VERSION:-}" ] && build_args+=(--build-arg "YARN_VERSION=$YARN_VERSION")
  [ -n "${PNPM_VERSION:-}" ] && build_args+=(--build-arg "PNPM_VERSION=$PNPM_VERSION")

  plain_build "pi" "$PI_REPO" "$PI_DOCKERFILE" "$REPO_ROOT" "${build_args[@]}"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  show_usage
  exit 0
fi

if [ $# -gt 0 ]; then
  SELECTED_TARGETS="$(normalize_targets "$@")"
else
  SELECTED_TARGETS="$(normalize_targets "${TARGETS:-${IMAGES:-orchestrator,native,pi}}")"
fi

[ -n "$SELECTED_TARGETS" ] || die "no targets selected"

log "selected targets: $SELECTED_TARGETS"
preflight

SUMMARY_TARGETS=()
SUMMARY_IMAGES=()
SUMMARY_DIGESTS=()

for target in $SELECTED_TARGETS; do
  case "$target" in
    orchestrator) repo="$ORCHESTRATOR_REPO"; build_orchestrator ;;
    native) repo="$NATIVE_REPO"; build_native ;;
    pi) repo="$PI_REPO"; build_pi ;;
    *) die "internal error: unhandled target $target" ;;
  esac

  push_and_verify "$repo"
  digest="$PUSH_DIGEST"
  SUMMARY_TARGETS+=("$target")
  SUMMARY_IMAGES+=("$repo:$TAG")
  SUMMARY_DIGESTS+=("$digest")
done

cat <<EOF

[build] DONE
  platform : $PLATFORM (plain linux/amd64 images, no provenance index)
  tag      : $TAG
  targets  : $SELECTED_TARGETS
  images:
EOF

for i in "${!SUMMARY_IMAGES[@]}"; do
  printf '    - %-12s %s (%s)\n' "${SUMMARY_TARGETS[$i]}:" "${SUMMARY_IMAGES[$i]}" "${SUMMARY_DIGESTS[$i]}"
done
