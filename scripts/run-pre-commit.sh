#!/usr/bin/env bash
# 在仓库根目录运行 pre-commit 全量检查（使用 backend .venv，避免 uv cache 权限问题）
# 用法: ./scripts/run-pre-commit.sh  或  bash scripts/run-pre-commit.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x backend/.venv/bin/python ]]; then
    echo "❌ backend/.venv 不存在或未安装依赖"
    echo "请先执行: cd backend && uv sync --dev"
    exit 1
fi

backend/.venv/bin/python -m pre_commit run --all-files
