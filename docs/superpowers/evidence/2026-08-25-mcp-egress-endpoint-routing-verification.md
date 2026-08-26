# MCP Egress Endpoint Routing Verification

**Date:** 2026-08-25

**Status:** Implemented and verified, except database-backed integration tests requiring an external migrated PostgreSQL URL

## Implemented Invariant

- Credential matching continues to use the existing slash-insensitive normalized MCP URL.
- Routing identity and egress revisions preserve the configured path, trailing slash, query order, and duplicate query parameters.
- Limited-networking Streamable HTTP exposes one exact opaque path and rewrites it to the configured upstream path without authorizing descendants.
- MCP routes omit Envoy retry policy, preventing transparent replay of non-idempotent POST tool calls.
- SSE is rejected in limited networking with `MCP_SSE_UNSUPPORTED_WITH_LIMITED_NETWORKING`; unrestricted SSE still receives the configured URL.
- Redirects to the real upstream authority remain outside the allowlist and fail closed.

## Architectural Owner

The Rust orchestrator owns endpoint parsing and runtime route compilation. Envoy remains the enforcement and header-injection boundary. No gateway or database migration was introduced.

## Verification Results

- `cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --check`: passed.
- `git diff --check`: passed.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --lib -- --test-threads=1`: 320 passed.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --lib mcp_url -- --test-threads=1`: passed.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --lib mcp_runtime_plan -- --test-threads=1`: 15 passed.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --lib sandbox::lds_backend::tests -- --test-threads=1`: 30 passed.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test mcp_live_envoy --no-run`: compiled successfully.
- `JOYSAFETER_RUN_LIVE_ENVOY=1 cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test mcp_live_envoy -- --ignored --nocapture --test-threads=1`: 1 passed. The runtime-plan-generated route delivered `POST /mcp?tenant=a&tenant=b` exactly, rejected a descendant path, and produced one upstream request for a `503` MCP POST.
- `cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l3_live.py -q -k require_successful_live_task`: 3 passed.
- `cd tests/mcp_connection_matrix && JOYSAFETER_TEST_PASSWORD='<redacted>' ../../backend/.venv/bin/python -m pytest test_matrix_infrastructure.py test_l1_direct.py test_l2_contract.py test_l3_live.py -q -k 'not test_live_'`: 94 passed, 2 live tests deselected.
- `cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l3_live.py -q --collect-only`: 5 tests collected.
- `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline -- --test-threads=1`: the complete library suite passed 320 tests, then the first database-backed integration test stopped because none of `JOYSAFETER_CREDENTIAL_RUNTIME_TEST_DATABASE_URL`, `JOYSAFETER_TEST_DATABASE_URL`, or `DATABASE_URL` was set.

## Remaining Risk

- Database-backed Rust integration tests were not executable without a migrated PostgreSQL test URL. Compilation succeeded, and the failure occurred in test setup before exercising application behavior.
- The real model-backed L3 tests were collected but not run because they consume external model credentials and task capacity. Their post-start failure semantics are covered by deterministic helper tests.

## Deployment Actions

- Rebuild and restart the Rust orchestrator and Envoy/sandbox runtime images.
- Recreate or refresh affected sandboxes so the new xDS policy is applied.
- Confirm the active network-policy generation is ACKed before rerunning the agent.
