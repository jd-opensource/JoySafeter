# Engine model resolution & egress hardening (pi/codex/native)

Date: 2026-08-07
Status: Draft for review
Scope: all non-claude engines (pi, codex, native) — model resolution, engine
config generation, and fail-loud observability. Limited-networking stays; all
model traffic keeps flowing through Envoy.

## 1. Problem

A `pi`-engine session ("发起会话无响应") produced no output. Investigation found
two independent defects; neither is in the egress/credential path.

### 1.1 Silent outage that was already fixed (context)
`JOYSAFETER_IMAGE_PI` was unset, so `image_for_provider("pi")` fell back to the
claudecode image, whose runner has no `pi` adapter → `No adapter for provider:
pi`. Fixed separately: env var added to `backend/.env` + `deploy/.env`, and
`config.rs::image_for_provider` now returns `Result` and fails loudly for a
known non-claude engine whose image is unset (orchestrator rebuilt, 182 tests
pass, live pi task now shows `image=joysafeter-pi:latest`, `providers=["pi"]`).

### 1.2 Model resolution mismatch (root cause of empty output)
`backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs`:
- codex: `model_secret_keys = ["OPENAI_MODEL"]`
- pi:    `model_secret_keys = ["PI_MODEL", "MODEL"]`

The operator's "pi" vault secret stores `OPENAI_MODEL=GPT-4.1` (frontend
pi/native_openai group, `frontend/lib/managed/secret-keys.ts`). `PI_MODEL` is
never populated anywhere. So `resolve_model_from_secrets`
(`harness_input_builder.rs:2111`) leaves `input.model = None`, pi is launched as
`pi --mode rpc` with no `--model` (`sandbox-runner/.../pi.rs:440`), and the pi
binary falls back to its **built-in default model** (observed `gpt-5.5`) — a
model the JD Cloud endpoint does not serve.

### 1.3 pi fails silently (why it looked like "no response")
- `pi.rs:450` sets `stderr(piped())` but never drains `child.stderr` → pi's
  error text is invisible and the pipe can eventually stall pi.
- `map_pi_event` only maps a top-level `{"type":"error"}`; other shapes hit
  `_ => {}` and are dropped (`pi.rs:275`).
- `HarnessResult.error` is hardcoded `None` (`pi.rs:113`); a turn is marked
  `Completed` on `agent_settled` regardless of whether any text/usage was
  produced. A failed/empty model call → "0 tokens, no text, clean end_turn".

### 1.4 pi cannot be pointed at a custom OpenAI-compatible endpoint by env alone
`pi --help`: default `--provider google`; `--model` is a **catalog pattern**;
its env list has **no `OPENAI_BASE_URL`** (only `AZURE_OPENAI_BASE_URL`). Per pi
docs (`packages/coding-agent/docs/models.md`), a custom OpenAI-compatible
endpoint must be declared in `~/.pi/agent/models.json`:

```json
{ "providers": { "<name>": {
  "baseUrl": "http://host:port/v1",
  "api": "openai-completions",
  "apiKey": "$OPENAI_API_KEY",
  "models": [ { "id": "<model-id>", "name": "<match-name>" } ]
} } }
```

`apiKey` supports `$ENV` interpolation, so it can reference the **placeholder**
`OPENAI_API_KEY` in the sandbox; Envoy still injects the real key at the
boundary. This differs from codex, which already writes `~/.codex/config.toml`
from env in `codex-entrypoint.sh`.

## 2. Confirmed facts (verified live)

- **Envoy runtime credential injection WORKS and is engine-agnostic.** From
  inside a live pi sandbox, a request through the proxy
  (`127.0.0.1:3128` + runner token) carrying only the placeholder
  `joysafeter-placeholder-openai-api-key` was rewritten by Envoy to the real key
  and returned a real completion (`gpt-4.1-2025-04-14`, `content: "pong"`). So
  "dynamic replacement / 运行时流量拦截替换" already exists and is universal for the
  OpenAI family. The sandbox never holds the real key. `extract_llm_egress`
  keys on `OPENAI_API_KEY` presence; no codex-vs-pi branching.
- **The divergence is purely model selection (§1.2/§1.4) and error visibility
  (§1.3).** Proxy/env injection into the child is identical for pi and codex
  (`pi.rs:451` vs `codex.rs:153`; proxy via `merge_process_proxy_env`).

## 3. Goals / non-goals

Goals:
1. pi/codex/native reliably use the operator-configured model against a custom
   OpenAI-compatible endpoint, through Envoy, under limited-networking.
2. No engine ever "completes" a turn silently after a failed/empty model call —
   the error reaches the session event stream (and thus the UI).
3. Single source of truth for an engine's model key; no drift between
   orchestrator, entrypoints, and secret templates.

Non-goals:
- Changing the egress/credential mechanism (it works). No Envoy changes.
- Disabling or weakening limited-networking.
- Reworking claude.

## 4. Design

### Pillar A — Model + provider config, generated outside the sandbox

Chosen approach: **orchestrator builds the engine config; runner writes it into
the sandbox before launching the agent.** (User decision: "沙箱外搞";
"Orchestrator builds config".)

A.1 **Canonical model var in `EngineSpec`.** Add a single field naming the
env/secret key that carries the model for that engine, and make it authoritative:
- `EngineSpec.model_secret_keys` becomes the one place; for the OpenAI family
  (codex, pi, native) it resolves `OPENAI_MODEL` (keep `MODEL` as a generic
  fallback). This fixes `resolve_model_from_secrets` for pi immediately.

A.2 **Orchestrator emits a provider-config artifact for engines that need one.**
Extend the harness input the orchestrator sends the runner with an optional
"engine config file" descriptor: `{ path, contents }`, rendered from the
resolved (post-egress) env:
- For pi: render `~/.pi/agent/models.json` with a single custom provider
  `{ baseUrl: <OPENAI_BASE_URL, already repointed to the plaintext egress host>,
  api: "openai-completions", apiKey: "$OPENAI_API_KEY" (placeholder value in
  sandbox), models: [{ id: <OPENAI_MODEL>, name: <stable match name> }] }`, and
  pass `--provider <name> --model <id>` (or `--model <name>/<id>`).
- codex already has an equivalent (`config.toml`); align it to the same
  orchestrator-driven descriptor so both engines share one mechanism instead of
  per-image entrypoint shell logic. (Entrypoint generation may remain as a
  fallback but is no longer the source of truth.)

A.3 **Runner writes the descriptor** into the sandbox filesystem (owned by the
sandbox user, correct mode) before spawning the agent, then launches the agent
with the resolved `--model`.

A.4 **Base URL / port normalization.** The egress repoints `OPENAI_BASE_URL` to
a plaintext `http://<host>:<port>`; the pi provider `baseUrl` must be the
`/v1`-suffixed form of that repointed URL so pi's requests traverse the proxy
and Envoy injects the key. This must match exactly what `extract_llm_egress`
produced (single source: the resolved env, not a re-derivation).

### Pillar B — Fail loud (all non-claude engines, focus pi)

B.1 **Drain stderr.** `pi.rs` must `take()` and read `child.stderr`, log it
(bounded, e.g. last N KB retained), and on a failed/empty turn attach the
captured tail to the surfaced error. Removes both the invisibility and the
pipe-stall risk. (codex nulls stderr; pi should capture it since pi has no RPC
error channel as rich as codex's.)

B.2 **Broaden error mapping.** Detect pi error signals beyond the single
top-level `{"type":"error"}` shape (nested errors, error-bearing message_end),
and stop dropping them via `_ => {}`.

B.3 **No silent empty completion.** Define an explicit rule: if a turn settles
with **zero assistant text, zero tool activity, and zero model usage**, treat it
as a failure — populate `HarnessResult.error` (with the stderr tail if any) and
surface a session event so the UI shows an error instead of an empty idle turn.
This directly addresses "发起会话无响应". A legitimately empty assistant turn is
not expected for these engines; if it turns out to be, gate on usage==0 AND an
error/empty-choice signal to avoid false positives.

B.4 **Config validation / fail-fast (parallels the image fix).** If an engine is
selected but its required model/provider config cannot be resolved (no model
key, no base URL), fail at resolution with an actionable message rather than
launching an agent that will silently misbehave.

## 5. Components & interfaces

- `engine_adapter.rs::EngineSpec` — canonical model key(s); add a
  `provider_config` descriptor builder (or a hook) per engine family.
- `harness_input_builder.rs` — `resolve_model_from_secrets` (unchanged logic,
  now correct keys); new step to build the provider-config descriptor from the
  resolved env; carry it on `HarnessInput`.
- runner (`runner.rs`) — write the descriptor file into the sandbox before
  dispatch.
- `pi.rs` — accept the written config; pass `--provider/--model`; drain stderr;
  broaden error mapping; enforce the no-silent-empty rule.
- `codex.rs`/entrypoint — align onto the same descriptor (dedupe).

Each unit stays independently testable: model resolution (pure fn over
secrets), descriptor rendering (pure fn → JSON/TOML string), runner file write
(fs), pi stderr/error handling (stream → events/result).

## 6. Testing

- Unit: `resolve_model_from_secrets` picks `OPENAI_MODEL` for pi/codex/native;
  descriptor renderer produces valid `models.json`/`config.toml` from a resolved
  env (incl. placeholder apiKey and repointed baseUrl).
- Unit: pi event mapping surfaces errors for the broadened shapes; a settle with
  no text+no usage yields `HarnessResult.error`.
- Integration (live, scripted): create a pi session, send "say pong", assert an
  `assistant`/text event with non-zero usage appears; assert a deliberately
  broken model name yields a surfaced error event (not a silent idle).

## 7. Risk register & verification (one by one)

| # | Risk | Verify |
|---|------|--------|
| R2 | Envoy doesn't inject real key on live path | DONE — live proxy request swapped placeholder → real key, got `pong`. |
| R1 | pi (node/undici) doesn't honor the runner proxy the way curl does — manual node fetch tests failed with `UND_ERR_INVALID_ARG` while curl succeeded | Establish codex baseline (same node/undici runtime) works end-to-end against JD → proves the runtime proxy path; then one real pi run after implementing config + `--model`. If pi still can't proxy, investigate pi's HTTP client proxy support (NODE_USE_ENV_PROXY / undici dispatcher) — may need an env/config toggle. **Blocking for pillar A completion.** |
| R3 | pi rejects the JD model id `GPT-4.1` as a `--model` pattern / provider match | With models.json declaring the provider+model, run pi and `pi --list-models`; confirm the id/name resolves to the jdcloud provider. |
| R4 | No-silent-empty rule false-positives on a legit empty turn | Gate on usage==0 AND (error signal OR empty choices); test a known-good run is not flagged. |
| R5 | stderr draining changes lifecycle / unbounded capture | Bounded ring buffer (last N KB); test with a chatty pi. |
| R6 | Model/base-url drift between descriptor and egress repoint | Render descriptor from the same resolved env `extract_llm_egress` used; unit-assert baseUrl matches repointed value. |
| R7 | Requires rebuilding pi image only if pi.rs/entrypoint change | Rebuild joysafeter-pi + orchestrator; rerun the exact "say pong" scenario; confirm visible assistant output. |

## 8. Rollout

1. Backend: EngineSpec canonical key + descriptor builder + fail-fast; unit tests.
2. Runner + pi.rs: write descriptor, pass `--model`, drain stderr, error rules.
3. Rebuild orchestrator + joysafeter-pi image; restart.
4. Live verify R1/R3/R7 (codex baseline first, then pi). Adjust if pi proxy needs
   a toggle.
5. Extend the same descriptor path to codex/native; dedupe entrypoint logic.
