#!/bin/bash
# 安装并配置 pre-commit hooks（与后端 UV 环境绑定）
# 在仓库根目录执行：./scripts/setup-pre-commit.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "🔍 配置 Pre-commit Hooks（使用后端 UV 环境）..."
echo ""

# 前置条件：必须已安装 uv
if ! command -v uv &> /dev/null; then
    echo "❌ 未检测到 uv"
    echo "请先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "✅ uv 已安装"
echo ""

# 使用 backend 的 UV 环境安装依赖（含 pre-commit）
echo "📦 安装后端开发依赖（含 pre-commit）..."
if ! (cd backend && uv sync --dev); then
    echo "❌ 后端依赖安装失败"
    exit 1
fi
echo "✅ 后端依赖已安装"
echo ""

# 验证 pre-commit 配置
echo "📋 验证 pre-commit 配置..."
if ! (cd backend && uv run python -m pre_commit validate-config 2>&1); then
    echo "❌ 配置文件无效"
    exit 1
fi
echo "✅ 配置文件有效"
echo ""

# 安装 Git hooks（hook 将使用 backend 的 venv 中的 pre-commit）
echo "📝 安装 Pre-commit Hooks..."
if ! (cd backend && uv run python -m pre_commit install --install-hooks); then
    echo "❌ 安装 Git hooks 失败"
    exit 1
fi
echo "✅ Pre-commit hooks 已安装"
echo ""

echo "✨ 完成！"
echo ""
echo "pre-commit 已与后端 UV 环境绑定，每次 git commit 将自动运行代码校验。"
echo "手动全量检查: cd backend && uv run python -m pre_commit run --all-files"
echo ""
