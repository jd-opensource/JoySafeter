#!/usr/bin/env sh
# 本地复现 GitHub Actions Frontend CI 全流程
# 用法: ./scripts/run-frontend-ci.sh  或  sh scripts/run-frontend-ci.sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRONTEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../frontend" && pwd)
NODE_BIN_DIR="$FRONTEND_DIR/node_modules/.bin"
FORCE_INSTALL=${RUN_FRONTEND_CI_INSTALL:-0}

CI=${CI:-true}
export CI

cd "$FRONTEND_DIR"

echo "=============================================="
echo "  Frontend CI（与 .github/workflows/ci.yml 一致）"
echo "  工作目录: $FRONTEND_DIR"
echo "  CI 环境变量: $CI"
echo "  强制重新安装依赖: $FORCE_INSTALL"
echo "=============================================="
echo ""

# 1. 安装依赖（优先复用现有 node_modules；需要时再安装）
if [ "$FORCE_INSTALL" = "1" ] || [ ! -x "$NODE_BIN_DIR/eslint" ] || [ ! -x "$NODE_BIN_DIR/tsc" ] || [ ! -x "$NODE_BIN_DIR/vitest" ] || [ ! -x "$NODE_BIN_DIR/next" ]; then
    echo ">>> 1. Install dependencies (bun install --frozen-lockfile)"
    bun install --frozen-lockfile
else
    echo ">>> 1. Reuse existing frontend dependencies ($FRONTEND_DIR/node_modules)"
    echo "    跳过 bun install；如需严格重装，请使用: RUN_FRONTEND_CI_INSTALL=1 sh scripts/run-frontend-ci.sh"
fi

if [ ! -x "$NODE_BIN_DIR/eslint" ] || [ ! -x "$NODE_BIN_DIR/tsc" ] || [ ! -x "$NODE_BIN_DIR/vitest" ] || [ ! -x "$NODE_BIN_DIR/next" ]; then
    echo "❌ frontend/node_modules 缺少 CI 所需命令"
    echo "请执行: cd frontend && bun install --frozen-lockfile"
    exit 1
fi

echo ""

# 2. ESLint
echo ">>> 2. Run ESLint (bun run lint)"
bun run lint
echo ""

# 3. TypeScript 类型检查
echo ">>> 3. Refresh Next.js generated types (bun x next typegen)"
bun x next typegen
echo ""

echo ">>> 4. Run TypeScript type check (bun run type-check)"
bun run type-check
echo ""

# 5. 单元测试
echo ">>> 5. Run tests (bun run test)"
bun run test
echo ""

# 6. 构建（与 CI 相同环境变量）
echo ">>> 6. Build (NEXT_PUBLIC_API_URL=http://localhost:8000 bun run build)"
export NEXT_PUBLIC_API_URL=http://localhost:8000
bun run build
echo ""

echo "=============================================="
echo "  ✅ Frontend CI 全部通过"
echo "=============================================="
