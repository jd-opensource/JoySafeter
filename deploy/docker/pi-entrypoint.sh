#!/bin/bash
set -euo pipefail

# Provider name declared in models.json. MUST stay in sync with
# sandbox-runner/crates/joysafeter-runtime/src/pi.rs (PI_PROVIDER_NAME).
PI_PROVIDER_NAME="joysafeter"

# Emit ~/.pi/agent/models.json content on stdout from the (already egress-
# repointed) container env. Mirrors deploy/docker/codex-entrypoint.sh: the real
# API key never enters the file — models.json references the placeholder env var
# ("$OPENAI_API_KEY"/"$ANTHROPIC_API_KEY") which pi interpolates at request time
# and Envoy swaps for the real key at the egress boundary.
#
# Responses vs Chat Completions cannot be inferred from env keys (both use
# OPENAI_*), so the wire protocol is read from JOYSAFETER_MODEL_PROTOCOL, which
# the orchestrator sets from the operator's secret `protocol` field.
generate_pi_models_json() {
    local protocol="${JOYSAFETER_MODEL_PROTOCOL:-}"
    local api base_url api_key_var model

    case "$protocol" in
        openai_responses)   api="openai-responses"   ;;
        chat_completions)   api="openai-completions"  ;;
        anthropic_messages) api="anthropic-messages"  ;;
        *)
            # Unset/custom: infer from whichever model var is present.
            if [ -n "${OPENAI_MODEL:-}" ]; then
                api="openai-completions"; protocol="chat_completions"
            elif [ -n "${ANTHROPIC_MODEL:-}" ]; then
                api="anthropic-messages"; protocol="anthropic_messages"
            else
                return 0  # nothing to declare; let pi surface the misconfig
            fi
            ;;
    esac

    if [ "$api" = "anthropic-messages" ]; then
        model="${ANTHROPIC_MODEL:-}"
        base_url="${ANTHROPIC_BASE_URL:-}"
        api_key_var='$ANTHROPIC_API_KEY'
    else
        model="${OPENAI_MODEL:-}"
        base_url="${OPENAI_BASE_URL:-}"
        api_key_var='$OPENAI_API_KEY'
    fi

    [ -n "$model" ] || return 0

    # Strip trailing slash(es) from baseUrl. pi appends "/chat/completions" (etc.),
    # so a base like "http://host/v1/" would yield "http://host/v1//chat/completions"
    # — the JD Cloud gateway rejects the double slash with 400 "参数解析失败", which
    # surfaces as an empty pi turn. The egress-repointed OPENAI_BASE_URL carries the
    # operator's trailing slash, so normalize it here.
    while [ "${base_url%/}" != "$base_url" ]; do base_url="${base_url%/}"; done

    # Render JSON. Uses python3 for correct escaping (present in the pi image).
    JS_API="$api" JS_BASE="$base_url" JS_KEY="$api_key_var" \
    JS_MODEL="$model" JS_PROVIDER="$PI_PROVIDER_NAME" python3 - <<'PY'
import json, os
provider = os.environ["JS_PROVIDER"]
print(json.dumps({
    "providers": {
        provider: {
            "baseUrl": os.environ["JS_BASE"],
            "api": os.environ["JS_API"],
            "apiKey": os.environ["JS_KEY"],
            "models": [
                {"id": os.environ["JS_MODEL"], "name": os.environ["JS_MODEL"]}
            ],
        }
    }
}, indent=2))
PY
}

# Allow the regression test to source only the function above.
if [ -n "${PI_ENTRYPOINT_TEST_SOURCE:-}" ]; then
    return 0 2>/dev/null || true
fi

# --- Runtime: write models.json, then scrub the runner token and exec. ---
models_json="$(generate_pi_models_json)"
if [ -n "$models_json" ]; then
    mkdir -p /home/agent/.pi/agent
    printf '%s\n' "$models_json" > /home/agent/.pi/agent/models.json
fi

. /usr/local/lib/joysafeter/runtime-credentials.sh
prepare_runtime_credentials

exec joysafeter-runner "$@"
