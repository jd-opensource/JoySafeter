#!/bin/bash
set -euo pipefail

CODEX_MODEL_VALUE="${CODEX_MODEL:-${OPENAI_MODEL:-}}"
CODEX_BASE_URL_VALUE="${CODEX_BASE_URL:-${OPENAI_BASE_URL:-https://api.openai.com/v1}}"
CODEX_REASONING_EFFORT_VALUE="${CODEX_REASONING_EFFORT:-high}"

mkdir -p /home/agent/.codex

{
    echo 'model_provider = "codex"'
    if [ -n "$CODEX_MODEL_VALUE" ]; then
        printf 'model = "%s"\n' "$CODEX_MODEL_VALUE"
    fi
    printf 'model_reasoning_effort = "%s"\n' "$CODEX_REASONING_EFFORT_VALUE"
    echo 'disable_response_storage = true'
    echo 'approval_policy = "on-request"'
    echo 'sandbox_mode = "workspace-write"'
    echo ''
    echo '[model_providers.codex]'
    echo 'name = "codex"'
    printf 'base_url = "%s"\n' "$CODEX_BASE_URL_VALUE"
    echo 'wire_api = "responses"'
    echo 'env_key = "OPENAI_API_KEY"'
} > /home/agent/.codex/config.toml

exec joysafeter-runner "$@"
