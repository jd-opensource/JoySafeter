# pi models.json (codex-mirrored) + fail-loud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make managed `pi`-engine sessions reliably use the operator-configured model against a custom OpenAI/Anthropic-compatible endpoint through Envoy key interception — by generating `~/.pi/agent/models.json` from container env (mirroring codex's entrypoint) and making pi fail loudly instead of returning a silent empty turn.

**Architecture:** Four independent seams. (A) The orchestrator's engine registry is corrected so pi resolves its model from `OPENAI_MODEL`/`ANTHROPIC_MODEL`. (B) The resolver plumbs the operator's secret `protocol` into the container env as `JOYSAFETER_MODEL_PROTOCOL` (Responses vs Chat Completions cannot be inferred from keys). (C) `deploy/docker/pi-entrypoint.sh` renders `~/.pi/agent/models.json` from the already-repointed container env, exactly as `codex-entrypoint.sh` renders `config.toml`; the placeholder `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` is interpolated by pi and swapped to the real key by Envoy at the egress boundary. (D) `pi.rs` passes `--model joysafeter/<id>` (declared provider) and gains fail-loud behavior: stderr draining, broadened error mapping, and a no-silent-empty rule.

**Tech Stack:** Rust (orchestrator crate `joysafeter-orchestrator`; runtime crate `joysafeter-runtime`), Bash (Docker entrypoints + `deploy/tests` regression scripts), pi 0.83.0 (`@earendil-works/pi-coding-agent`).

## Global Constraints

- Backend Rust orchestrator tests: run from `backend/app/joysafeter_orchestrator_rs/` with `cargo test`. Package name: `joysafeter-orchestrator`. Postgres-backed builder tests self-skip when `DATABASE_URL`/`JOYSAFETER_TEST_DATABASE_URL` is unset; pure-function tests always run.
- Runtime (sandbox-runner) tests: run from `sandbox-runner/` with `cargo test -p joysafeter-runtime`.
- Deploy/entrypoint tests: plain Bash under `deploy/tests/`, sourced-function + `assert_contains`/`fail` style (see `deploy/tests/deploy-sh-test.sh`). Run with `bash deploy/tests/<name>.sh`.
- Do NOT touch `.deps/SkillSpector` (vendored third-party).
- Egress/Envoy mechanism is unchanged (it already works; the real key never enters the sandbox). No proto changes, no orchestrator→runner file-shipping changes: generation is entrypoint-side to match codex and avoid the two-env-path drift hazard.
- Shared coupling constant: the pi provider name declared in `models.json` and the prefix passed to `pi --model` MUST both be the literal string `joysafeter`. Any change must be made in both `deploy/docker/pi-entrypoint.sh` and `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`.
- Placeholder values (must match `llm_providers.rs`): OpenAI `joysafeter-placeholder-openai-api-key`, Anthropic `joysafeter-placeholder-anthropic-api-key`.
- Protocol values (from `frontend/lib/managed/secret-keys.ts` / DB `protocol` column): `openai_responses`, `chat_completions`, `anthropic_messages`, `custom`.
- Reasoning-effort / thinkingLevelMap mapping for pi is OUT OF SCOPE this pass (YAGNI).

---

### Task 1: Correct pi's model-resolution keys in the engine registry

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs:39-45` (pi `EngineSpec` entry) and its test module `:57-63`
- Test: same file, inline `#[cfg(test)] mod tests`

**Interfaces:**
- Consumes: `EngineSpec.model_secret_keys: &'static [&'static str]` (existing field, `engine_adapter.rs:18`).
- Produces: pi `EngineSpec` with `model_secret_keys = &["OPENAI_MODEL", "ANTHROPIC_MODEL", "MODEL"]`, consumed by `resolve_model_from_secrets` (Task 2).

- [ ] **Step 1: Write the failing test**

Add to the `tests` module in `engine_adapter.rs`:

```rust
    #[test]
    fn pi_resolves_openai_and_anthropic_model_keys() {
        let spec = super::engine_spec("pi").expect("pi registered");
        // pi is multi-protocol: OpenAI-compatible operators store OPENAI_MODEL,
        // Anthropic-protocol operators store ANTHROPIC_MODEL. PI_MODEL is never
        // populated by the frontend secret groups, so it must not be relied on.
        assert_eq!(
            spec.model_secret_keys,
            &["OPENAI_MODEL", "ANTHROPIC_MODEL", "MODEL"]
        );
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test pi_resolves_openai_and_anthropic_model_keys`
Expected: FAIL — left is `["PI_MODEL", "MODEL"]`, right is `["OPENAI_MODEL", "ANTHROPIC_MODEL", "MODEL"]`.

- [ ] **Step 3: Update the pi registry entry**

Replace `engine_adapter.rs:39-45` with:

```rust
        EngineSpec {
            engine_kind: "pi",
            injects_conversation_history: true,
            // pi is multi-provider. The frontend pi secret groups store the model
            // under OPENAI_MODEL (openai_responses / chat_completions protocols) or
            // ANTHROPIC_MODEL (anthropic_messages protocol); MODEL is a generic
            // fallback. PI_MODEL is never populated anywhere, so it is not read.
            model_secret_keys: &["OPENAI_MODEL", "ANTHROPIC_MODEL", "MODEL"],
        },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test pi_ engine_ -- --nocapture`
Expected: PASS — `pi_engine_is_registered` and `pi_resolves_openai_and_anthropic_model_keys` both pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs
git commit -m "fix(orchestrator): pi resolves model from OPENAI_MODEL/ANTHROPIC_MODEL"
```

---

### Task 2: Unit-test model resolution end-to-end for pi

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs` — the `resolve_model_from_secrets` fn is at `:2111`; add a focused unit test. This fn is currently untested.

**Interfaces:**
- Consumes: `resolve_model_from_secrets(input: &mut HarnessInput)` (`harness_input_builder.rs:2111`), pi registry from Task 1.
- Produces: nothing new; locks the resolution behavior against regression.

Note: `resolve_model_from_secrets` is a free function in the module (not behind the Postgres-gated tests). Construct a `HarnessInput` via `..Default::default()` (the struct derives `Default`, `harness_input_builder.rs:66`).

- [ ] **Step 1: Write the failing test**

Add to the `tests` module in `harness_input_builder.rs` (import the fn: add `resolve_model_from_secrets` to the `use super::{...}` list at `:1247`):

```rust
    #[test]
    fn resolve_model_prefers_openai_model_for_pi() {
        let mut input = super::HarnessInput {
            provider: "pi".to_string(),
            secrets: std::collections::HashMap::from([
                ("OPENAI_MODEL".to_string(), "GPT-4.1".to_string()),
            ]),
            ..Default::default()
        };
        super::resolve_model_from_secrets(&mut input);
        assert_eq!(input.model.as_deref(), Some("GPT-4.1"));
    }

    #[test]
    fn resolve_model_falls_back_to_anthropic_model_for_pi() {
        let mut input = super::HarnessInput {
            provider: "pi".to_string(),
            secrets: std::collections::HashMap::from([
                ("ANTHROPIC_MODEL".to_string(), "Claude-Opus-4.6".to_string()),
            ]),
            ..Default::default()
        };
        super::resolve_model_from_secrets(&mut input);
        assert_eq!(input.model.as_deref(), Some("Claude-Opus-4.6"));
    }

    #[test]
    fn resolve_model_noop_when_already_set() {
        let mut input = super::HarnessInput {
            provider: "pi".to_string(),
            model: Some("preset".to_string()),
            secrets: std::collections::HashMap::from([
                ("OPENAI_MODEL".to_string(), "GPT-4.1".to_string()),
            ]),
            ..Default::default()
        };
        super::resolve_model_from_secrets(&mut input);
        assert_eq!(input.model.as_deref(), Some("preset"));
    }
```

- [ ] **Step 2: Run tests to verify they fail/compile-fail then pass expectation**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test resolve_model_`
Expected: PASS (Task 1 already fixed the keys). If `resolve_model_from_secrets` or `HarnessInput` is not importable, add it to the `use super::{...}` block. These tests must PASS — they lock in the Task 1 behavior at the resolution layer. If any FAIL, the registry change in Task 1 is wrong; fix Task 1.

- [ ] **Step 3: (no impl change — behavior already provided by Task 1)**

No production code changes in this task. If `resolve_model_prefers_openai_model_for_pi` fails, re-open Task 1.

- [ ] **Step 4: Run the module test suite**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test --lib kernel::harness_input_builder`
Expected: PASS (Postgres-gated tests self-skip with a stderr notice; the three new tests run and pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs
git commit -m "test(orchestrator): lock pi model resolution from OPENAI/ANTHROPIC_MODEL"
```

---

### Task 3: Plumb the secret `protocol` into container env as `JOYSAFETER_MODEL_PROTOCOL`

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs` — `merge_secret_ref_into_env` at `:1690-1729` (add `protocol` to the SELECT and set the env var for the agent's primary secret).
- Test: inline `#[cfg(test)]` unit test for a new pure helper `model_protocol_env_value`.

**Interfaces:**
- Consumes: DB column `joysafeter_secrets.protocol` (String, values `openai_responses`|`chat_completions`|`anthropic_messages`|`custom`); `merge_secret_ref_into_env(pool, env, secret_ref, project_id, override_existing)` at `:1690`.
- Produces: container `env["JOYSAFETER_MODEL_PROTOCOL"] = <protocol>` when the agent's primary secret (`override_existing == true`, called at `:1140-1149`) has a non-empty, non-`custom` protocol. Consumed by `pi-entrypoint.sh` (Task 5). Must be set BEFORE `extract_llm_egress` runs (`:814`) — it already is, because `resolve_agent_env_from` (`:790`) precedes egress extraction (`:814`).

Design note: only the agent's *primary* secret (`override_existing == true`) sets the protocol, so environment-level secret_refs (merged with `override_existing == false`, `:1128-1135`) do not overwrite it. `JOYSAFETER_MODEL_PROTOCOL` is not an LLM detection key, so `extract_llm_egress` ignores it and it rides into the container env unchanged.

- [ ] **Step 1: Write the failing test (pure helper)**

Add near the other free-function tests in `sandbox_resolver.rs` (find the existing `#[cfg(test)] mod tests` block; if the module lacks one for free fns, add a `#[cfg(test)] mod protocol_tests`):

```rust
#[cfg(test)]
mod protocol_env_tests {
    use super::model_protocol_env_value;

    #[test]
    fn maps_known_protocols() {
        assert_eq!(model_protocol_env_value("openai_responses"), Some("openai_responses".to_string()));
        assert_eq!(model_protocol_env_value("chat_completions"), Some("chat_completions".to_string()));
        assert_eq!(model_protocol_env_value("anthropic_messages"), Some("anthropic_messages".to_string()));
    }

    #[test]
    fn ignores_custom_and_blank() {
        assert_eq!(model_protocol_env_value("custom"), None);
        assert_eq!(model_protocol_env_value(""), None);
        assert_eq!(model_protocol_env_value("   "), None);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test model_protocol_env_value`
Expected: FAIL — `model_protocol_env_value` is not defined.

- [ ] **Step 3: Add the pure helper**

Add as a free function in `sandbox_resolver.rs` (top-level, near other helpers):

```rust
/// Normalizes a stored secret `protocol` into the container-env signal read by
/// pi-entrypoint.sh. Returns `None` for `custom`/blank so we never emit a
/// meaningless `JOYSAFETER_MODEL_PROTOCOL`.
fn model_protocol_env_value(protocol: &str) -> Option<String> {
    match protocol.trim() {
        "" | "custom" => None,
        other => Some(other.to_string()),
    }
}
```

- [ ] **Step 4: Wire it into `merge_secret_ref_into_env`**

In `sandbox_resolver.rs`, change the SELECT at `:1697-1709` to also fetch `protocol`, and set the env var when this is the primary secret. Replace the query + destructure:

```rust
        let secret: Option<(serde_json::Value, String)> = sqlx::query_as(
            r#"
            SELECT data, protocol FROM joysafeter_secrets
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(secret_ref)
        .bind(project_id)
        .fetch_optional(pool)
        .await?;

        let Some((data, protocol)) = secret else {
            return Ok(());
        };

        // The agent's primary secret (override_existing) defines the model wire
        // protocol for the sandbox. Environment-level secret_refs must not clobber
        // it. pi-entrypoint.sh maps this to the models.json `api` field.
        if override_existing {
            if let Some(value) = model_protocol_env_value(&protocol) {
                env.insert("JOYSAFETER_MODEL_PROTOCOL".to_string(), value);
            }
        }
```

(Leave the existing `cipher`/`data.as_object()` decrypt loop at `:1715-1726` unchanged.)

- [ ] **Step 5: Run tests + typecheck**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test model_protocol_env_value && cargo build`
Expected: PASS + clean build. (The `query_as` tuple type changed from `(Value,)` to `(Value, String)`; the build confirms the sqlx mapping compiles.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs
git commit -m "feat(orchestrator): plumb secret protocol into container env for pi"
```

---

### Task 4: pi.rs launches with the declared provider (`--model joysafeter/<id>`)

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs` — `ensure_session` args at `:440-443`; add a module constant + pure formatter.
- Test: inline `#[cfg(test)] mod tests` in `pi.rs`.

**Interfaces:**
- Consumes: `HarnessInput.model: Option<String>` (the resolved model id, e.g. `GPT-4.1`), `cwd`.
- Produces: pi launched as `pi --mode rpc --model joysafeter/<id>` when a model is set. Provider name `joysafeter` MUST equal the provider declared in `models.json` (Task 5). New pub(crate) fn `pi_model_arg(model: &str) -> String`.

Rationale: pi's `--model` accepts `provider/id` (`pi --help`: "supports \"provider/id\""). Prefixing with our declared provider prevents pi from matching a built-in catalog model (e.g. `gpt-5.5`) and forces it onto the JoySafeter-declared provider whose `baseUrl`/`apiKey` route through Envoy.

- [ ] **Step 1: Write the failing test**

Add to the `tests` module in `pi.rs`:

```rust
    #[test]
    fn pi_model_arg_prefixes_declared_provider() {
        assert_eq!(super::pi_model_arg("GPT-4.1"), "joysafeter/GPT-4.1");
        assert_eq!(super::pi_model_arg("Claude-Opus-4.6"), "joysafeter/Claude-Opus-4.6");
    }

    #[test]
    fn pi_model_arg_does_not_double_prefix() {
        // If a caller ever passes an already-qualified id, keep it as-is.
        assert_eq!(super::pi_model_arg("joysafeter/GPT-4.1"), "joysafeter/GPT-4.1");
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi_model_arg`
Expected: FAIL — `pi_model_arg` not defined.

- [ ] **Step 3: Add the constant + formatter and use it in `ensure_session`**

Near the top of `pi.rs` (after imports):

```rust
/// Provider name declared in ~/.pi/agent/models.json by pi-entrypoint.sh.
/// MUST stay in sync with deploy/docker/pi-entrypoint.sh (PI_PROVIDER_NAME).
pub(crate) const PI_PROVIDER_NAME: &str = "joysafeter";

/// Qualifies a bare model id with the declared provider so pi selects the
/// JoySafeter-declared provider (whose baseUrl/apiKey route through Envoy)
/// instead of a built-in catalog model.
pub(crate) fn pi_model_arg(model: &str) -> String {
    if model.contains('/') {
        model.to_string()
    } else {
        format!("{PI_PROVIDER_NAME}/{model}")
    }
}
```

Replace the arg-building block at `pi.rs:440-443` with:

```rust
        let mut args = vec!["--mode".to_string(), "rpc".to_string()];
        if let Some(model) = &input.model {
            args.extend(["--model".to_string(), pi_model_arg(model)]);
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi_model_arg`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): pi launches with declared provider prefix on --model"
```

---

### Task 5: pi-entrypoint.sh generates `~/.pi/agent/models.json` from container env

**Files:**
- Modify: `deploy/docker/pi-entrypoint.sh` (currently only scrubs the runner token; convert to `#!/bin/bash`, add a sourceable `generate_pi_models_json` function, call it before the token scrub + `exec`).
- Create: `deploy/tests/pi-entrypoint-test.sh` (regression test mirroring `deploy/tests/deploy-sh-test.sh`).

**Interfaces:**
- Consumes (container env, produced by Tasks 1–3 + existing egress): `OPENAI_MODEL` / `ANTHROPIC_MODEL`, `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` (already repointed to the Envoy plaintext host by `extract_llm_egress`), placeholder `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, and `JOYSAFETER_MODEL_PROTOCOL` (Task 3).
- Produces: `/home/agent/.pi/agent/models.json` declaring provider `joysafeter` with the correct `api` for the protocol, `baseUrl` = the repointed base URL (raw, matching codex), `apiKey` = `"$OPENAI_API_KEY"` / `"$ANTHROPIC_API_KEY"` (pi interpolates the placeholder; Envoy swaps the real key), and one model whose `id` = the resolved model. The model `id` MUST equal the value pi.rs passes after the `joysafeter/` prefix (Task 4).

Protocol → pi `api` mapping (the reason Task 3 exists — Responses vs Chat Completions share `OPENAI_*`):
- `openai_responses`   → `api: "openai-responses"`,  base var `OPENAI_BASE_URL`,  key `OPENAI_API_KEY`,  model `OPENAI_MODEL`
- `chat_completions`   → `api: "openai-completions"`, base var `OPENAI_BASE_URL`,  key `OPENAI_API_KEY`,  model `OPENAI_MODEL`
- `anthropic_messages` → `api: "anthropic-messages"`, base var `ANTHROPIC_BASE_URL`, key `ANTHROPIC_API_KEY`, model `ANTHROPIC_MODEL`
- unset/`custom`: default to OpenAI Chat Completions if `OPENAI_MODEL` present, else Anthropic if `ANTHROPIC_MODEL` present, else write NO file (let pi error visibly rather than mis-declaring).

- [ ] **Step 1: Write the failing test**

Create `deploy/tests/pi-entrypoint-test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail "expected to contain: $2"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "expected NOT to contain: $2"; }
assert_valid_json() { printf '%s' "$1" | python3 -c 'import json,sys; json.load(sys.stdin)' || fail "invalid JSON: $1"; }

# Source the entrypoint's pure function without running the exec tail.
PI_ENTRYPOINT_TEST_SOURCE=1 source "$DEPLOY_DIR/docker/pi-entrypoint.sh"

# --- openai_responses ---
out="$(JOYSAFETER_MODEL_PROTOCOL=openai_responses \
      OPENAI_MODEL=GPT-4.1 \
      OPENAI_BASE_URL=http://egress.local:3128/v1 \
      OPENAI_API_KEY=joysafeter-placeholder-openai-api-key \
      generate_pi_models_json)"
assert_valid_json "$out"
assert_contains "$out" '"openai-responses"'
assert_contains "$out" '"joysafeter"'
assert_contains "$out" '"GPT-4.1"'
assert_contains "$out" 'http://egress.local:3128/v1'
assert_contains "$out" '"$OPENAI_API_KEY"'
# The real key must never be baked in; only the placeholder ref is used.
assert_not_contains "$out" 'sk-'

# --- chat_completions ---
out="$(JOYSAFETER_MODEL_PROTOCOL=chat_completions \
      OPENAI_MODEL=GPT-4.1 OPENAI_BASE_URL=http://egress.local:3128/v1 \
      OPENAI_API_KEY=placeholder generate_pi_models_json)"
assert_contains "$out" '"openai-completions"'

# --- anthropic_messages ---
out="$(JOYSAFETER_MODEL_PROTOCOL=anthropic_messages \
      ANTHROPIC_MODEL=Claude-Opus-4.6 ANTHROPIC_BASE_URL=http://egress.local:3128 \
      ANTHROPIC_API_KEY=placeholder generate_pi_models_json)"
assert_valid_json "$out"
assert_contains "$out" '"anthropic-messages"'
assert_contains "$out" '"Claude-Opus-4.6"'
assert_contains "$out" '"$ANTHROPIC_API_KEY"'

# --- no model at all -> empty output, no file ---
out="$(JOYSAFETER_MODEL_PROTOCOL=custom generate_pi_models_json || true)"
[[ -z "$out" ]] || fail "expected empty output when no model configured"

printf 'pi-entrypoint regression tests passed\n'
```

Make it executable: `chmod +x deploy/tests/pi-entrypoint-test.sh`.

- [ ] **Step 2: Run test to verify it fails**

Run: `bash deploy/tests/pi-entrypoint-test.sh`
Expected: FAIL — `generate_pi_models_json: command not found` (function doesn't exist yet; sourcing guard absent).

- [ ] **Step 3: Rewrite `pi-entrypoint.sh` with the generator**

Replace the entire contents of `deploy/docker/pi-entrypoint.sh` with:

```bash
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

TOKEN_FILE="/tmp/.runner-token"
if [ -n "${JOYSAFETER_RUNNER_TOKEN:-}" ]; then
    printf '%s' "$JOYSAFETER_RUNNER_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    export JOYSAFETER_RUNNER_TOKEN_FILE="$TOKEN_FILE"
    unset JOYSAFETER_RUNNER_TOKEN
fi

exec joysafeter-runner "$@"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash deploy/tests/pi-entrypoint-test.sh`
Expected: PASS — `pi-entrypoint regression tests passed`.

- [ ] **Step 5: Verify the pi Dockerfile has `python3` and `bash`**

Run: `grep -nE "python3|bash|pi-entrypoint" deploy/docker/pi.Dockerfile`
Expected: entrypoint is wired (`COPY`/`ENTRYPOINT`). If `python3` is not installed in the image, add it to the apt/apk install layer in `deploy/docker/pi.Dockerfile` (the base already runs Node for pi; add `python3` minimal). If `bash` is missing (alpine), either install `bash` or downgrade the script to POSIX `sh` (replace `local`/`[[ ]]` accordingly). Document whichever you did in the commit message.

- [ ] **Step 6: Commit**

```bash
git add deploy/docker/pi-entrypoint.sh deploy/tests/pi-entrypoint-test.sh deploy/docker/pi.Dockerfile
git commit -m "feat(deploy): pi-entrypoint generates ~/.pi/agent/models.json from env"
```

---

### Task 6: pi.rs drains stderr (bounded) and exposes the tail

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs` — `PersistentPi` struct (`:22-28`), `ensure_session` spawn (`:445-483`), add a bounded stderr collector.
- Test: inline test for the bounded ring-buffer helper.

**Interfaces:**
- Consumes: `child.stderr` (currently piped at `:450` but never read).
- Produces: `PersistentPi.stderr_tail: Arc<std::sync::Mutex<String>>` holding the last ≤ N KB of pi stderr; new pure helper `push_bounded(buf: &mut String, chunk: &str, max: usize)`. Consumed by Task 8 (no-silent-empty error surfacing).

- [ ] **Step 1: Write the failing test**

Add to the `tests` module in `pi.rs`:

```rust
    #[test]
    fn push_bounded_keeps_last_bytes() {
        let mut buf = String::new();
        super::push_bounded(&mut buf, "hello ", 8);
        super::push_bounded(&mut buf, "world!!", 8);
        // Only the last <=8 bytes are retained.
        assert!(buf.len() <= 8, "buf too long: {:?}", buf);
        assert!(buf.ends_with("d!!"), "should keep newest tail: {:?}", buf);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime push_bounded`
Expected: FAIL — `push_bounded` not defined.

- [ ] **Step 3: Add the bounded helper**

Add to `pi.rs`:

```rust
/// Appends `chunk` to `buf`, retaining only the last `max` bytes (on a char
/// boundary). Keeps the stderr tail bounded so a chatty pi can't grow memory.
pub(crate) fn push_bounded(buf: &mut String, chunk: &str, max: usize) {
    buf.push_str(chunk);
    if buf.len() > max {
        let cut = buf.len() - max;
        // Advance to a char boundary at or after `cut`.
        let mut idx = cut;
        while idx < buf.len() && !buf.is_char_boundary(idx) {
            idx += 1;
        }
        *buf = buf.split_off(idx);
    }
}
```

- [ ] **Step 4: Add `stderr_tail` to `PersistentPi` and drain stderr in `ensure_session`**

In the `PersistentPi` struct (`pi.rs:22-28`) add:

```rust
    stderr_tail: Arc<std::sync::Mutex<String>>,
```

In `ensure_session`, after `let stdout = child.stdout.take()...` (`:465-468`) and before building `current_turn`, add:

```rust
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stderr".into()))?;
        let stderr_tail: Arc<std::sync::Mutex<String>> =
            Arc::new(std::sync::Mutex::new(String::new()));
        {
            let tail = stderr_tail.clone();
            tokio::spawn(async move {
                const MAX_STDERR_TAIL: usize = 16 * 1024;
                let mut reader = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = reader.next_line().await {
                    if let Ok(mut g) = tail.lock() {
                        push_bounded(&mut g, &format!("{line}\n"), MAX_STDERR_TAIL);
                    }
                    info!(target: "pi_stderr", "{line}");
                }
            });
        }
```

Then include `stderr_tail` when constructing `PersistentPi` (`:477-482`):

```rust
        *guard = Some(PersistentPi {
            stdin: Arc::new(Mutex::new(Some(stdin))),
            reader_handle,
            current_turn,
            child,
            stderr_tail,
        });
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime push_bounded && cargo build -p joysafeter-runtime`
Expected: PASS + clean build.

- [ ] **Step 6: Commit**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): drain pi stderr into a bounded tail buffer"
```

---

### Task 7: pi.rs broadens error-event mapping

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs` — `map_pi_event` error handling at `:271-275`.
- Test: inline tests in `pi.rs`.

**Interfaces:**
- Consumes: pi rpc JSON `serde_json::Value`.
- Produces: `HarnessEvent::Error { message }` for the existing top-level `{"type":"error"}` AND nested error shapes: a top-level object carrying `error.message` (or string `error`), and `message_end` whose message role indicates an error with an `error`/`errorMessage` field. Unknown shapes still fall through to `_ => {}`.

Guard against false positives: only emit for explicit error signals, never for normal `message_end`.

- [ ] **Step 1: Write the failing tests**

Add to the `tests` module in `pi.rs`:

```rust
    #[test]
    fn maps_nested_error_object() {
        let m = map(serde_json::json!({
            "type": "error",
            "error": { "message": "model not found: gpt-x" }
        }));
        assert!(m.events.iter().any(|e|
            matches!(e, HarnessEvent::Error { message } if message.contains("model not found"))));
    }

    #[test]
    fn maps_top_level_error_string_field() {
        let m = map(serde_json::json!({ "type": "error", "error": "boom" }));
        assert!(m.events.iter().any(|e|
            matches!(e, HarnessEvent::Error { message } if message == "boom")));
    }

    #[test]
    fn normal_message_end_is_not_an_error() {
        let m = map(serde_json::json!({
            "type": "message_end",
            "message": { "model": "m", "usage": { "input": 1, "output": 1 } }
        }));
        assert!(!m.events.iter().any(|e| matches!(e, HarnessEvent::Error { .. })));
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime maps_nested_error maps_top_level_error normal_message_end`
Expected: FAIL — `maps_nested_error_object` and `maps_top_level_error_string_field` fail (only the flat `message` string is currently read at `:272`).

- [ ] **Step 3: Broaden the `"error"` arm**

Replace the `"error"` match arm at `pi.rs:271-274` with:

```rust
        "error" => {
            let msg = event
                .get("message")
                .and_then(|m| m.as_str())
                .map(|s| s.to_string())
                .or_else(|| {
                    event.get("error").and_then(|e| match e {
                        serde_json::Value::String(s) => Some(s.clone()),
                        serde_json::Value::Object(_) => e
                            .get("message")
                            .and_then(|m| m.as_str())
                            .map(|s| s.to_string()),
                        _ => None,
                    })
                })
                .unwrap_or_else(|| "pi error".to_string());
            events.push(HarnessEvent::Error { message: msg });
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime`
Expected: PASS — new error tests pass; the existing `replays_real_pi_rpc_stream_fixture` and all prior mapping tests still pass (no regression).

- [ ] **Step 5: Commit**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): broaden pi error-event mapping to nested shapes"
```

---

### Task 8: pi.rs no-silent-empty rule (populate HarnessResult.error)

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs` — completion task at `:97-118` (currently sets `error: None`, `Completed` on `!aborted`); add a pure decision helper.
- Test: inline tests for the decision helper.

**Interfaces:**
- Consumes: turn outcome — `aborted: bool`, `output: &str`, `usage: &TokenUsage`, `stderr_tail: &str`.
- Produces: pure fn `finalize_pi_turn(aborted, output_is_empty, usage_is_zero, stderr_tail) -> (HarnessResultStatus, Option<String>)`; the completion task uses it so a settle with no text AND zero usage becomes `Failed` with an actionable error (including the stderr tail) instead of a silent `Completed`.

Rule (design §B.3, gated to avoid false positives): failure only when `!aborted && output_is_empty && usage_is_zero`. A normal turn (any text or any usage) stays `Completed`. Aborted stays `Aborted`.

- [ ] **Step 1: Write the failing tests**

Add to the `tests` module in `pi.rs`:

```rust
    use joysafeter_types::harness::HarnessResultStatus;

    #[test]
    fn finalize_flags_empty_zero_usage_turn_as_failed() {
        let (status, err) = super::finalize_pi_turn(false, true, true, "boom: model not found");
        assert_eq!(status, HarnessResultStatus::Failed);
        let err = err.expect("error populated");
        assert!(err.contains("no output"), "msg: {err}");
        assert!(err.contains("boom: model not found"), "should include stderr tail: {err}");
    }

    #[test]
    fn finalize_keeps_normal_turn_completed() {
        let (status, err) = super::finalize_pi_turn(false, false, false, "");
        assert_eq!(status, HarnessResultStatus::Completed);
        assert!(err.is_none());
    }

    #[test]
    fn finalize_partial_usage_is_not_failure() {
        // Text present but zero usage, or usage present with empty text: not a failure.
        assert_eq!(super::finalize_pi_turn(false, false, true, "").0, HarnessResultStatus::Completed);
        assert_eq!(super::finalize_pi_turn(false, true, false, "").0, HarnessResultStatus::Completed);
    }

    #[test]
    fn finalize_aborted_stays_aborted() {
        assert_eq!(super::finalize_pi_turn(true, true, true, "x").0, HarnessResultStatus::Aborted);
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime finalize_`
Expected: FAIL — `finalize_pi_turn` not defined.

- [ ] **Step 3: Add the decision helper**

Add to `pi.rs`:

```rust
use joysafeter_types::harness::HarnessResultStatus;

/// Decides the terminal status + error for a settled pi turn. A turn that
/// settles with NO assistant text AND zero model usage is treated as a failure
/// (the "发起会话无响应" case) rather than a silent Completed. Gated on both
/// conditions to avoid flagging a legitimately terse turn.
pub(crate) fn finalize_pi_turn(
    aborted: bool,
    output_is_empty: bool,
    usage_is_zero: bool,
    stderr_tail: &str,
) -> (HarnessResultStatus, Option<String>) {
    if aborted {
        return (HarnessResultStatus::Aborted, None);
    }
    if output_is_empty && usage_is_zero {
        let mut msg =
            "pi produced no output and no model usage (likely a failed or empty model call)"
                .to_string();
        let tail = stderr_tail.trim();
        if !tail.is_empty() {
            msg.push_str("; stderr: ");
            msg.push_str(tail);
        }
        return (HarnessResultStatus::Failed, Some(msg));
    }
    (HarnessResultStatus::Completed, None)
}
```

- [ ] **Step 4: Use it in the completion task**

The completion task lives in `start` (`pi.rs:97-118`). It needs the `stderr_tail`. Capture a clone from the session before `drop(guard)` (near `:92-95`):

```rust
        let stderr_tail_for_result = session.stderr_tail.clone();
```

Then replace the status/result block (`pi.rs:105-117`) with:

```rust
            let usage_is_zero = final_usage.input_tokens == 0
                && final_usage.output_tokens == 0
                && final_usage.cache_read_tokens == 0
                && final_usage.cache_write_tokens == 0;
            let tail = stderr_tail_for_result
                .lock()
                .map(|g| g.clone())
                .unwrap_or_default();
            let (status, error) =
                finalize_pi_turn(aborted, final_output.trim().is_empty(), usage_is_zero, &tail);
            let _ = result_tx.send(joysafeter_types::harness::HarnessResult {
                status,
                output: final_output,
                error,
                session_id,
                usage: final_usage,
                duration: start.elapsed(),
            });
```

Remove the now-unused local `status` computed at `:105-109` (replaced above). Keep the `td_rx.await` → `aborted` and the `current_turn` reset (`:98-104`) unchanged.

- [ ] **Step 5: Run the full runtime suite**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime`
Expected: PASS — all `finalize_*` tests pass; the real-stream fixture still completes (it has text + usage, so it stays `Completed`); no regressions.

- [ ] **Step 6: Commit**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): pi surfaces error on no-output/zero-usage turns"
```

---

### Task 9: Build, deploy, and live-verify against the managed session

**Files:**
- No source edits. Rebuild images and verify. Reference: `deploy/deploy.sh`, `deploy/docker/pi.Dockerfile`.

**Interfaces:**
- Consumes: all prior tasks. Verification target: JoySafeter at `http://localhost:3000`, session `sess_019fdb56-90ff-7201-932c-a22a440ffe4f`, account `admin@jd.com`, JD Cloud endpoint.
- Produces: a live pi turn that shows visible assistant output (or a visible error), proving the models.json + Envoy key-interception path (design risks R1/R3/R7).

- [ ] **Step 1: Run every automated test added in this plan**

```bash
cd backend/app/joysafeter_orchestrator_rs && cargo test
cd ../../../sandbox-runner && cargo test -p joysafeter-runtime
cd .. && bash deploy/tests/pi-entrypoint-test.sh
```
Expected: all PASS (orchestrator Postgres tests self-skip if no DB).

- [ ] **Step 2: Rebuild the pi image and orchestrator**

Rebuild the joysafeter-pi image (picks up `pi-entrypoint.sh` + the runner binary with the pi.rs changes) and the orchestrator (engine registry + protocol plumbing). Use the repo's normal build path:

```bash
bash deploy/deploy.sh   # or the project's documented pi-image + orchestrator build/restart
```
Expected: images rebuild; orchestrator restarts. Confirm the pi image tag matches `JOYSAFETER_IMAGE_PI`.

- [ ] **Step 3: Codex baseline sanity (proves the node/undici proxy path)**

Before testing pi, confirm a codex session against JD Cloud still returns output through the same runtime proxy (design R1 baseline). If codex works and pi doesn't, the issue is pi-specific config, not egress.

- [ ] **Step 4: Live pi "say pong" in the managed session**

In the managed UI (`http://localhost:3000/managed/sessions/sess_019fdb56-90ff-7201-932c-a22a440ffe4f`, logged in as `admin@jd.com`), send a pi turn like "say pong". 
Expected: a visible assistant text event with non-zero usage. Confirm inside/against the sandbox that `/home/agent/.pi/agent/models.json` exists, declares provider `joysafeter` with the right `api` for the operator's protocol, `baseUrl` = the repointed egress URL, and `apiKey: "$OPENAI_API_KEY"` (or `$ANTHROPIC_API_KEY`).

- [ ] **Step 5: Live negative check (no-silent-empty)**

Temporarily configure a deliberately broken model id and send a turn.
Expected: the session shows a surfaced error event (from Task 8, including the pi stderr tail) — NOT a silent idle turn. Restore the correct model afterward.

- [ ] **Step 6: Final commit / notes**

If any image-build or env wiring adjustments were needed (e.g. `JOYSAFETER_IMAGE_PI`, `python3` in the pi image), commit them with a clear message. Record the live verification outcome (pong text + error-surfacing) in the PR description.

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-08-07-engine-model-egress-design.md`):
- §1.2 / §A.1 model-resolution mismatch → Tasks 1–2 (pi reads `OPENAI_MODEL`/`ANTHROPIC_MODEL`).
- §1.4 / §A.2 custom endpoint via `models.json` → Task 5 (entrypoint generation), with the codex-mirror decision replacing the orchestrator-descriptor variant per user direction; §A.4 base-URL "no drift" is satisfied by using the same repointed `OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL` the container already holds (raw passthrough, exactly like codex).
- Protocol-driven `api` (Responses vs Chat Completions vs Anthropic, user decision) → Task 3 (plumb protocol) + Task 5 (map to `api`).
- §B.1 drain stderr → Task 6. §B.2 broaden error mapping → Task 7. §B.3 no-silent-empty → Task 8. §B.4 fail-fast config → partially covered by Task 5's "write no file → pi errors visibly" + Task 8 surfacing; full resolution-time fail-fast in the orchestrator is not added (YAGNI: the empty-turn surfacing already makes misconfig visible).
- §1.1 image fix → already committed (out of scope, confirmed at `config.rs:387`).
- Provider `--model` selection → Task 4.
- §6 testing + §8 rollout / R1,R3,R7 → Task 9.

**Placeholder scan:** No TBD/TODO; every code step has complete content.

**Type consistency:** `PI_PROVIDER_NAME` = `"joysafeter"` used identically in Task 4 (pi.rs) and Task 5 (entrypoint). `finalize_pi_turn` signature identical between Task 8 definition and its tests. `push_bounded` signature identical between Task 6 definition, its test, and its Task 6 caller. `model_protocol_env_value` consistent across Task 3. Protocol string values (`openai_responses`/`chat_completions`/`anthropic_messages`/`custom`) consistent across Tasks 3 and 5.

**Out-of-scope (explicit):** no proto changes; no orchestrator→runner file shipping; no Envoy changes; no reasoning-effort/thinkingLevelMap for pi; no changes to claude/codex behavior beyond reading the shared placeholder/base-url conventions.
