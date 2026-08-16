# Final Fix: JD Agent Snapshot Opt-Out

Date: 2026-08-16

## Root Cause

The session execution snapshot already preserved `metadata.agent_identity.enabled=false` over later live-agent metadata. The JD provider bypassed that snapshot decision in two places: `has_config()` always returned `true`, and `resolve()` converted the parser's disabled result into default-enabled configuration.

## Fix

- Preserve global/default JD behavior when `agent_identity` is absent.
- Treat explicit `enabled=true` as active and explicit `enabled=false` as authoritative.
- Return an empty injection from `resolve()` for explicit false before Redis, HTTP, token exchange, or header injection.
- Add a run-spec regression where live metadata is true while the session snapshot is false.
- Add JD crate coverage for absent, explicit true, explicit false, and disabled resolution.

## TDD Evidence

RED:

```text
cargo test -p jd-agent-identity explicit_disabled -- --nocapture
2 failed: has_config returned true; resolve attempted createBotToken.
```

GREEN / verification:

```text
cargo test -p jd-agent-identity                         6 passed
cargo test -p agent-identity-trait                      passed
cargo test -p joysafeter-orchestrator kernel::run_spec::tests
cargo test -p joysafeter-orchestrator kernel::agent_identity_config::tests
cargo test -p joysafeter-orchestrator --features jd-identity kernel::run_spec::tests
cargo test -p joysafeter-orchestrator --features jd-identity kernel::agent_identity_config::tests
cargo check -p jd-agent-identity
cargo check -p joysafeter-orchestrator
cargo check -p joysafeter-orchestrator --features jd-identity
cargo fmt --all -- --check
git diff --check
```

All commands exited successfully. Existing workspace dead-code/unused warnings remain unchanged.

## Scope and Risk

Only the JD identity crate, the run-spec regression test, and this report are included. No deployment configuration or generic no-provider behavior changed. The actual parent at commit preparation is `07ed8c852a07cb9d98e67f9297dc28adf67006f6`; the earlier seven-file private-endpoint commit `40264a2c98cbb28a0de1e2dd47dccde980fd5098` was not modified or staged by this fix.
