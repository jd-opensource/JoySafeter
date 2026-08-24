# MCP Runtime Plan and xDS Authority Verification

Date: 2026-08-24

## Verified Architecture

- PostgreSQL owns durable MCP runtime generations and networking status.
- Redis Stream `joysafeter:network-policy:requests` is an exact-generation wakeup channel, not xDS state.
- One Kubernetes Lease-elected authority owns recovery, apply, remove, and prune operations.
- Authority activation is Lease acquisition → epoch advertisement → PostgreSQL recovery and Envoy ACK → ready → ADS serving → leader label publication.
- Authority revocation fences the epoch, disables ADS, closes established streams, removes the leader label, and releases the Lease.
- All networking mutations share one authority application lock; generation CAS prevents stale ACK/NACK persistence.
- The MCP runtime plan is the single source for runner-safe configuration, credential-bearing Envoy routes, DNS pinning, and network-policy readiness.

## Final Contract Audit

- MCP transport is explicit at the API/domain boundary; persisted or submitted server entries without a canonical
  `streamable_http`, `sse`, or `local_stdio` transport fail closed instead of inheriting an implicit default.
- MCP credential APIs reject the model-only `auto` authentication scheme. Omission remains the only defaulting signal,
  while the Anthropic adapter privately normalizes its own omitted scheme to `auto`.
- Frontend credential and credential-group parsers consume the backend's complete strict response contract, including
  `auth_scheme`; MCP group members additionally require MCP kind, group identity, canonical URL, and canonical auth scheme.

## Verification Evidence

- Rust orchestrator: `cargo fmt --all -- --check`, `cargo check --offline`, and
  `cargo test --offline --lib -- --test-threads=1` passed; 318 tests passed.
- PostgreSQL network-policy integration: `network_policy_generation` passed with 5 tests, including
  same-generation late-NACK protection and durable-lifecycle validation before teardown.
- PostgreSQL credential integration: `credential_store_integration` passed with 19 tests, including
  canonical MCP auth resolution, disabled OAuth tombstones, audit behavior, and runtime generation guards.
- Live Envoy: `live_envoy_enforces_mcp_routes_headers_streaming_rotation_and_recovery` passed with Docker and Envoy v1.37.1.
- Python migration coverage includes canonicalization of every persisted MCP surface, atomic rollback
  for unknown transports, strict malformed remote/local shape rejection, and preservation of disabled OAuth tombstones.
- Python protobuf package import passed; `McpConfig` has typed field 8 `transport`, field/name 5 remains
  reserved, `server_type` is absent, and all three canonical enum values load through the package.
- Python backend: the full suite passed with 2499 tests; 981 existing warnings were reported, primarily
  SQLAlchemy foreign-key-cycle warnings plus HTTPX per-request-cookie deprecations.
- Python quality: changed non-generated Python files passed Ruff check and Ruff format check. Generated
  protobuf files remain excluded by repository policy.
- Frontend: 135 files and 1184 tests passed; `bun run type-check` and Prettier passed; ESLint exited zero
  with 562 existing repository warnings and no errors.
- Sandbox runner: formatting, offline check, and all workspace tests passed (CLI 4, runner 34, runtime 59, types 1).
- The unused `joysafeter-types::vault` module and its obsolete MCP OAuth refresh abstractions were removed;
  the workspace compile and test pass proves there are no remaining callers.
- Kubernetes manifest: parsed successfully as 11 YAML documents; leader-only Service selector, Lease
  permissions, pod label patch permission, Lease name, gRPC xDS mode, and dedicated xDS host wiring were asserted.
- Helm CLI was not installed, so rendered-chart validation was not available; chart templates were statically checked for the same Service, selector, RBAC, and xDS host contracts.
- Documentation contract checks and `git diff --check` passed.
- Legacy scans found no production Redis key or ownership path from the retired replicated-xDS design.
  Remaining old transport/auth literals are limited to the irreversible migration, explicit rejection tests,
  protobuf reservations, and disabled credential tombstones.

## Cleanup Evidence

- Removed the disposable PostgreSQL container `joysafeter-mcp-cas-20260824`.
- The live Envoy test removed its `joysafeter-mcp-live-*` network, fixture/Envoy containers, and socket volume;
  final Docker queries returned no matching resources.
- Removed the temporary local `backend/.venv` and `frontend/node_modules` dependency directories used for verification.
- Removed pytest caches, Python `__pycache__` directories, and `/tmp/joysafeter-mcp-*` scratch paths created by verification.
- Existing fixed-name development services and orchestrator-managed warm-pool sandboxes were not removed because
  they are owned by the running local environment, not by this verification run.

## Known Existing Noise

- Rust compilation reports existing unrelated warnings outside this change's scope.
- Frontend ESLint reports repository-wide existing warnings but zero errors.
- Backend pytest reports existing SQLAlchemy foreign-key-cycle and HTTPX deprecation warnings.
- Helm rendered-chart verification remains unavailable until Helm is installed; static YAML/template checks
  and the real Envoy integration cover the relevant runtime wiring in this workspace.
