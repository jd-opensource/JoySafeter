#!/usr/bin/env sh
# 本地复现 GitHub Actions Backend CI 全流程
# 用法: ./scripts/run-backend-ci.sh  或  sh scripts/run-backend-ci.sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../backend" && pwd)

if ! command -v uv >/dev/null 2>&1; then
    echo "❌ 未检测到 uv"
    echo "请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

cd "$BACKEND_DIR"

echo "=============================================="
echo "  Backend CI（与 .github/workflows/ci.yml 一致）"
echo "  工作目录: $BACKEND_DIR"
echo "=============================================="
echo ""

# 1. 安装依赖（CI 使用 uv venv + uv sync --dev）
echo ">>> 1. Install dependencies (uv venv, uv sync --dev)"
uv venv
uv sync --dev
echo ""

# 2. Ruff 检查
echo ">>> 2. Run Ruff linting (uv run ruff check --output-format=github .)"
uv run ruff check --output-format=github .
echo ""

# 3. Ruff 格式检查
echo ">>> 3. Run Ruff formatting check (uv run ruff format --check .)"
uv run ruff format --check .
echo ""

# 4. 类型检查
echo ">>> 4. Run type checking with mypy (uv run mypy app --ignore-missing-imports)"
uv run mypy app --ignore-missing-imports
echo ""

echo "=============================================="
echo "  ✅ Backend CI 全部通过"
echo "=============================================="
