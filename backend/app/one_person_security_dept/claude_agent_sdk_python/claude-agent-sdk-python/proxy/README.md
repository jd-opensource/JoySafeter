# OpenAI -> Anthropic Compatibility Proxy

This proxy exposes Anthropic-compatible endpoints and forwards requests to an OpenAI-compatible upstream.

## Endpoints

- `POST /v1/messages`
- `GET /v1/models`
- `GET /healthz`

## Environment Variables

- `OPENAI_BASE_URL` (required)
- `MODEL_MAP_JSON` (optional) - JSON map, e.g. `{"claude-sonnet-4-6":"Kimi-K2.5"}`
- `FALLBACK_MODELS_JSON` (optional) - static Anthropic-style model list fallback used when upstream `/v1/models` fails
- `DEFAULT_MAX_TOKENS` (optional, default `4096`)
- `UPSTREAM_TIMEOUT_SECONDS` (optional, default `90`)
- `UPSTREAM_EXTRA_HEADERS_JSON` (optional) - JSON headers to add upstream
- `LOG_LEVEL` (optional, default `INFO`)

## Install

```bash
cd /Users/wuxiaohan10/Downloads/claude-agent-sdk-python
python3 -m venv .venv
. .venv/bin/activate
pip install -r proxy/requirements.txt
```

## Run

```bash
export OPENAI_BASE_URL="http://ai-api.jdcloud.com"
export MODEL_MAP_JSON='{"claude-sonnet-4-6":"Kimi-K2.5"}'
export FALLBACK_MODELS_JSON='["Kimi-K2.5","Kimi-Vision"]'
uvicorn proxy.app:create_app --factory --host 0.0.0.0 --port 8080
```

## Claude SDK Integration

Point Claude SDK to this proxy instead of direct Anthropic API:

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    env={
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
        "ANTHROPIC_AUTH_TOKEN": "<your-upstream-token>",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    }
)
```

## Notes

- Inbound auth supports both `x-api-key` and `Authorization: Bearer <token>`.
- Inbound token is forwarded as upstream `Authorization: Bearer <token>`.
- Upstream endpoint is fixed to OpenAI `POST /v1/chat/completions` and `GET /v1/models`.
- Streaming responses are converted from OpenAI SSE chunks into Anthropic SSE event format.

## Troubleshooting

- If you see upstream auth errors, verify token and `OPENAI_BASE_URL`.
- If model not found, add mapping in `MODEL_MAP_JSON`.
- If upstream does not support `/v1/models`, configure `FALLBACK_MODELS_JSON`.
- If stream hangs, inspect upstream raw SSE response and proxy logs.
