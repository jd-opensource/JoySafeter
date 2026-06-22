#!/bin/bash
set -euo pipefail

OPENAI_MODEL_VALUE="${OPENAI_MODEL:-}"
OPENAI_BASE_URL_VALUE="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
OPENAI_REASONING_EFFORT_VALUE="${OPENAI_REASONING_EFFORT:-high}"
# Codex's own approval-policy gate (separate from JoySafeter's permission model).
# Honor JOYSAFETER_CODEX_APPROVAL_POLICY when set so callers can run end-to-end
# tests / trusted environments without the on-request prompt. Defaults to the
# original safe-by-default value.
CODEX_APPROVAL_POLICY_VALUE="${JOYSAFETER_CODEX_APPROVAL_POLICY:-on-request}"
# Codex's filesystem sandbox tier (separate from JoySafeter's docker isolation).
# Codex only auto-approves MCP tool calls when ``approval_policy = "never"`` AND
# ``sandbox_mode ∈ {danger-full-access, external}``. JoySafeter sandboxes are
# already docker-isolated, so "danger-full-access" is safe in this context.
# Override via JOYSAFETER_CODEX_SANDBOX_MODE when a stricter tier is required.
CODEX_SANDBOX_MODE_VALUE="${JOYSAFETER_CODEX_SANDBOX_MODE:-workspace-write}"

mkdir -p /home/agent/.codex

{
    echo 'model_provider = "codex"'
    if [ -n "$OPENAI_MODEL_VALUE" ]; then
        printf 'model = "%s"\n' "$OPENAI_MODEL_VALUE"
    fi
    printf 'model_reasoning_effort = "%s"\n' "$OPENAI_REASONING_EFFORT_VALUE"
    echo 'disable_response_storage = true'
    printf 'approval_policy = "%s"\n' "$CODEX_APPROVAL_POLICY_VALUE"
    printf 'sandbox_mode = "%s"\n' "$CODEX_SANDBOX_MODE_VALUE"
    echo ''
    echo '[model_providers.codex]'
    echo 'name = "codex"'
    printf 'base_url = "%s"\n' "$OPENAI_BASE_URL_VALUE"
    echo 'wire_api = "responses"'
    echo 'env_key = "OPENAI_API_KEY"'
} > /home/agent/.codex/config.toml

exec joysafeter-runner "$@"
