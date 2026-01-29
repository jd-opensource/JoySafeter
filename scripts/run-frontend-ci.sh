#!/usr/bin/env bash
# 本地复现 GitHub Actions Frontend CI 全流程
# 用法: ./scripts/run-frontend-ci.sh  或  bash scripts/run-frontend-ci.sh

set -e

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"
cd "$FRONTEND_DIR"

echo "=============================================="
echo "  Frontend CI（与 .github/workflows/ci.yml 一致）"
echo "  工作目录: $FRONTEND_DIR"
echo "=============================================="
echo ""

# 1. 安装依赖（CI 使用 frozen-lockfile）
echo ">>> 1. Install dependencies (pnpm install --frozen-lockfile)"
pnpm install --frozen-lockfile
echo ""

# 2. ESLint
echo ">>> 2. Run ESLint (pnpm run lint)"
pnpm run lint
echo ""

# 3. TypeScript 类型检查
echo ">>> 3. Run TypeScript type check (pnpm run type-check)"
pnpm run type-check
echo ""

# 4. 单元测试
echo ">>> 4. Run tests (pnpm run test)"
pnpm run test
echo ""

# 5. 构建（与 CI 相同环境变量）
echo ">>> 5. Build (NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm run build)"
export NEXT_PUBLIC_API_URL=http://localhost:8000
pnpm run build
echo ""

echo "=============================================="
echo "  ✅ Frontend CI 全部通过"
echo "=============================================="
