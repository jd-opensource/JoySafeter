#!/usr/bin/env sh
# 本地复现 GitHub Actions Backend CI 全流程
# 用法: ./scripts/run-backend-ci.sh  或  sh scripts/run-backend-ci.sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../backend" && pwd)
VENV_BIN="$BACKEND_DIR/.venv/bin"
FORCE_SYNC=${RUN_BACKEND_CI_SYNC:-0}

# 避免受限环境下访问 ~/.cache/uv 失败；允许外部显式覆盖。
UV_CACHE_DIR=${UV_CACHE_DIR:-"$BACKEND_DIR/.uv-cache"}
export UV_CACHE_DIR

mkdir -p "$UV_CACHE_DIR"

cd "$BACKEND_DIR"

echo "=============================================="
echo "  Backend CI（与 .github/workflows/ci.yml 一致）"
echo "  工作目录: $BACKEND_DIR"
echo "  UV 缓存目录: $UV_CACHE_DIR"
echo "  强制重新同步依赖: $FORCE_SYNC"
echo "=============================================="
echo ""

# 1. 安装依赖（优先复用现有 .venv；需要时再执行 uv sync）
if [ "$FORCE_SYNC" = "1" ] || [ ! -x "$VENV_BIN/python" ] || [ ! -x "$VENV_BIN/ruff" ] || [ ! -x "$VENV_BIN/mypy" ]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "❌ 未检测到 uv"
        echo "请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    echo ">>> 1. Install dependencies (uv venv, uv sync --dev)"
    uv venv
    uv sync --dev
else
    echo ">>> 1. Reuse existing backend virtualenv ($BACKEND_DIR/.venv)"
    echo "    跳过 uv sync --dev；如需严格重跑，请使用: RUN_BACKEND_CI_SYNC=1 sh scripts/run-backend-ci.sh"
fi

if [ ! -x "$VENV_BIN/ruff" ] || [ ! -x "$VENV_BIN/mypy" ]; then
    echo "❌ backend/.venv 缺少 ruff 或 mypy"
    echo "请执行: cd backend && uv sync --dev"
    exit 1
fi

echo ""

# 2. Ruff 检查
echo ">>> 2. Run Ruff linting (.venv/bin/ruff check --output-format=github .)"
"$VENV_BIN/ruff" check --output-format=github .
echo ""

# 3. Ruff 格式检查
echo ">>> 3. Run Ruff formatting check (.venv/bin/ruff format --check .)"
"$VENV_BIN/ruff" format --check .
echo ""

# 4. 类型检查
echo ">>> 4. Run type checking with mypy (.venv/bin/mypy app --ignore-missing-imports)"
"$VENV_BIN/mypy" app --ignore-missing-imports
echo ""

echo "=============================================="
echo "  ✅ Backend CI 全部通过"
echo "=============================================="
