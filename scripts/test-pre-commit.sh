#!/bin/bash
# 测试 pre-commit hooks 的脚本

set -e

echo "🔍 测试 Pre-commit Hooks 配置..."
echo ""

# 检查 pre-commit 是否安装
if ! command -v pre-commit &> /dev/null; then
    echo "❌ pre-commit 未安装"
    echo "请运行: pip install pre-commit 或 uv pip install pre-commit"
    exit 1
fi

echo "✅ pre-commit 已安装"
echo ""

# 验证配置文件
echo "📋 验证配置文件..."
if pre-commit validate-config 2>&1; then
    echo "✅ 配置文件有效"
else
    echo "❌ 配置文件无效"
    exit 1
fi

echo ""
echo "🧪 测试后端 Ruff Check..."
if cd backend && uv run ruff check . > /dev/null 2>&1; then
    echo "✅ 后端 Ruff Check 通过"
else
    echo "⚠️  后端 Ruff Check 有错误（这是正常的，如果有未修复的问题）"
fi
cd ..

echo ""
echo "🧪 测试前端 ESLint..."
if cd frontend && pnpm run lint > /dev/null 2>&1; then
    echo "✅ 前端 ESLint 通过"
else
    echo "⚠️  前端 ESLint 有错误（这是正常的，如果有未修复的问题）"
fi
cd ..

echo ""
echo "📝 安装 Pre-commit Hooks..."
if pre-commit install; then
    echo "✅ Pre-commit hooks 已安装"
else
    echo "❌ 安装失败"
    exit 1
fi

echo ""
echo "✨ 完成！"
echo ""
echo "现在当你执行 git commit 时，会自动运行代码检查。"
echo "手动运行所有检查: pre-commit run --all-files"
