#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT_DIR="$ROOT_DIR/target/universal-apple-darwin/release"
BIN_NAME="joysafeterctl"

cargo build \
  --manifest-path "$ROOT_DIR/Cargo.toml" \
  -p joysafeter-ctl \
  --release \
  --target aarch64-apple-darwin \
  --no-default-features \
  --features tls-native

cargo build \
  --manifest-path "$ROOT_DIR/Cargo.toml" \
  -p joysafeter-ctl \
  --release \
  --target x86_64-apple-darwin \
  --no-default-features \
  --features tls-native

mkdir -p "$OUT_DIR"
lipo -create \
  "$ROOT_DIR/target/aarch64-apple-darwin/release/$BIN_NAME" \
  "$ROOT_DIR/target/x86_64-apple-darwin/release/$BIN_NAME" \
  -output "$OUT_DIR/$BIN_NAME"

lipo -info "$OUT_DIR/$BIN_NAME"
ls -lh "$OUT_DIR/$BIN_NAME"
