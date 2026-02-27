#!/bin/bash
# Simplified OpenClaw startup script for JoySafeter per-user containers.
# Based on moltworker's start-openclaw.sh with R2/rclone parts removed.

set -e

if pgrep -f "openclaw gateway" > /dev/null 2>&1; then
    echo "OpenClaw gateway is already running, exiting."
    exit 0
fi

if [ -z "$AI_GATEWAY_BASE_URL" ] || [ -z "$AI_GATEWAY_API_KEY" ] || [ -z "$AI_GATEWAY_MODEL" ]; then
    echo "ERROR: Missing required environment variable(s)."
    echo "Required: AI_GATEWAY_BASE_URL, AI_GATEWAY_API_KEY, AI_GATEWAY_MODEL"
    exit 1
fi

CONFIG_DIR="/root/.openclaw"
CONFIG_FILE="$CONFIG_DIR/openclaw.json"

mkdir -p "$CONFIG_DIR"

# ============================================================
# ONBOARD (only if no config exists yet)
# ============================================================
if [ ! -f "$CONFIG_FILE" ]; then
    echo "No existing config found, running openclaw onboard..."

    AUTH_ARGS=""
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        AUTH_ARGS="--auth-choice apiKey --anthropic-api-key $ANTHROPIC_API_KEY"
    elif [ -n "$OPENAI_API_KEY" ]; then
        AUTH_ARGS="--auth-choice openai-api-key --openai-api-key $OPENAI_API_KEY"
    fi

    openclaw onboard --non-interactive --accept-risk \
        --mode local \
        $AUTH_ARGS \
        --gateway-port 18789 \
        --gateway-bind lan \
        --skip-channels \
        --skip-skills \
        --skip-health

    echo "Onboard completed"
else
    echo "Using existing config"
fi

# ============================================================
# PATCH CONFIG (gateway auth, openai api, trusted proxies)
# ============================================================
node << 'EOFPATCH'
const fs = require('fs');

const configPath = '/root/.openclaw/openclaw.json';
let config = {};

try {
    config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
} catch (e) {
    console.log('Starting with empty config');
}

config.gateway = config.gateway || {};

config.gateway.port = 18789;
config.gateway.mode = 'local';
config.gateway.trustedProxies = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'];

if (process.env.OPENCLAW_GATEWAY_TOKEN) {
    config.gateway.auth = config.gateway.auth || {};
    config.gateway.auth.token = process.env.OPENCLAW_GATEWAY_TOKEN;
}

config.gateway.controlUi = config.gateway.controlUi || {};

if (process.env.OPENCLAW_DEV_MODE === 'true') {
    config.gateway.controlUi.allowInsecureAuth = true;
}

config.gateway.controlUi.allowedOrigins = ["http://localhost:18789", "http://127.0.0.1:18789", "http://192.168.1.100:18789"]

// Enable OpenAI-compatible HTTP API

let baseUrl = process.env.AI_GATEWAY_BASE_URL;
let apiKey = process.env.AI_GATEWAY_API_KEY;
let gwProvider = process.env.AI_GATEWAY_PROVIDER;
let modelId = process.env.AI_GATEWAY_MODEL;

if (baseUrl && apiKey) {
    const api = gwProvider === 'anthropic' ? 'anthropic-messages' : 'openai-completions';
    const providerName = 'ai-gw-' + gwProvider;

    config.models = config.models || {};
    config.models.providers = config.models.providers || {};
    config.models.providers[providerName] = {
        baseUrl: baseUrl,
        apiKey: apiKey,
        api: api,
        models: [{ id: modelId, name: modelId, contextWindow: 131072, maxTokens: 8192 }],
    };
    config.agents = config.agents || {};
    config.agents.defaults = config.agents.defaults || {};
    config.agents.defaults.model = { primary: providerName + '/' + modelId };
    console.log('AI Gateway model override: provider=' + providerName + ' model=' + modelId + ' via ' + baseUrl);
} else {
    console.warn('CF_AI_GATEWAY_MODEL set but missing required config (account ID, gateway ID, or API key)');
}

fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
console.log('Configuration patched successfully');
EOFPATCH

# ============================================================
# START GATEWAY
# ============================================================
echo "Starting OpenClaw Gateway on port 18789..."

rm -f /tmp/openclaw-gateway.lock 2>/dev/null || true
rm -f "$CONFIG_DIR/gateway.lock" 2>/dev/null || true

if [ -n "$OPENCLAW_GATEWAY_TOKEN" ]; then
    echo "using token...$OPENCLAW_GATEWAY_TOKEN"
    exec openclaw gateway --port 18789 --verbose --allow-unconfigured --bind lan --token "$OPENCLAW_GATEWAY_TOKEN"
else
    exec openclaw gateway --port 18789 --verbose --allow-unconfigured --bind lan
fi
