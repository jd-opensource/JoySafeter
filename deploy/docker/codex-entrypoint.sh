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
# already docker-isolated + capability-dropped, so layering Codex's own
# Landlock/seccomp sandbox on top causes endless fork retries inside the
# container (cap-drop blocks the syscalls Codex needs to create its sandbox),
# exhausts the per-UID nproc cap, and makes every later fork — including
# ``bash`` / ``ls`` — fail with EAGAIN. Default to ``danger-full-access``
# (safe in this context because Docker is already isolating us). Tighten via
# JOYSAFETER_CODEX_SANDBOX_MODE only if you know Codex's Landlock can coexist
# with the host cap-drop policy.
CODEX_SANDBOX_MODE_VALUE="${JOYSAFETER_CODEX_SANDBOX_MODE:-danger-full-access}"
# Codex multi-agent v2 (spawn_agent / send_message / followup_task).
# Codex disables multi-agent for fresh threads by default. Honour that default
# here — set JOYSAFETER_CODEX_MULTI_AGENT=true to opt in to multi-agent support.
# The runner already maps collabAgentToolCall / subAgentActivity events to the
# same bg_task surface as Claude Code, so no other changes are needed when enabled.
CODEX_MULTI_AGENT_VALUE="${JOYSAFETER_CODEX_MULTI_AGENT:-false}"

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
    if [ "$CODEX_MULTI_AGENT_VALUE" = "true" ]; then
        echo ''
        echo '[features]'
        echo 'multi_agent_v2 = true'
    fi
} > /home/agent/.codex/config.toml

. /usr/local/lib/joysafeter/runtime-credentials.sh
prepare_runtime_credentials

exec joysafeter-runner "$@"
