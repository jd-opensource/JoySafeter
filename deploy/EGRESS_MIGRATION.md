# Unified Egress Migration Status

## Target Architecture

The target request path is:

`sandbox -> shared Envoy -> orchestrator ext_authz -> upstream`

The control path is:

`orchestrator durable policy authority -> PostgreSQL -> Go egress-controller -> ADS/xDS -> Envoy ACK/NACK -> PostgreSQL`

PostgreSQL is authoritative for desired generations and apply status. Secrets
are resolved per request and are never stored in xDS or sandbox Pod/container
environment variables.

## Migration Matrix

| Area | Target state | Repository state | Remaining rollout work |
| --- | --- | --- | --- |
| Kubernetes production | Shared Envoy + PostgreSQL authority | Production overlay enables both flags and removes the legacy gateway | Supply managed services/Secrets/PKI, pin images, execute live smoke and soak |
| Kubernetes base/local | Compatibility and developer validation | Base still contains the legacy gateway and defaults disabled | Remove after the rollback observation window and after all local scripts use the unified overlay |
| Docker Compose | Go controller + durable authority | Unified path is now the default; filesystem mode is explicit rollback-only | Run compose e2e on every supported host architecture |
| xDS apply state | HA-safe terminal state machine | `failed` and `superseded` cannot regress; late ACK cannot erase NACK | Observe multi-controller failover under real rolling restarts |
| Rust build/release | First-class artifact | Locked build dependency, CI job, and Docker release matrix are present | Clear non-blocking style/complexity lint backlog |
| Legacy Rust gateway | Rollback-only | Binary and compatibility code remain; production overlay does not deploy it | Delete after the agreed deprecation window |
| Legacy filesystem xDS | Rollback-only | Available only by explicit Docker environment override | Delete after Docker controller-mode soak and rollback-window closure |

## Capability Impact After Cutover

### Improvements

- Durable desired state and last-known-good restore survive controller restarts.
- Multiple controllers and Envoy replicas can operate without a single local
  in-memory source of truth.
- ACK/NACK status is queryable and release gates can require all ready nodes to
  acknowledge every required xDS type.
- Model/provider credentials are injected per request by ext_authz instead of
  being embedded in xDS, files, Pod specs, or sandbox environment variables.
- Kubernetes and Docker converge on one policy compiler and one control-plane
  state model.

### Changed Failure Modes

- PostgreSQL is now a hard control-plane dependency for new policy generations.
- Policy changes are not complete until the required Envoy nodes ACK them;
  callers may observe additional apply latency.
- NACK is terminal for that generation. Recovery requires a new generation or
  release rollback, not a late ACK.
- xDS, ext_authz, and downstream TLS certificates become production lifecycle
  dependencies and must be monitored before expiry.
- New or unhealthy Envoy replicas can block the all-node rollout gate even when
  existing traffic continues on the last-known-good generation.

## Production Gates

All of the following must pass on the exact release commit and images:

1. Clean `cargo build --locked --release --bins` from an isolated checkout.
2. Rust format, correctness/suspicious/perf Clippy groups, full Rust tests with
   migrated PostgreSQL, Go race tests, backend tests, frontend tests/build.
3. Multi-architecture Docker builds for orchestrator-rs and egress-controller.
4. `kubectl kustomize` render checks for base, local, and production overlays.
5. Docker compose four-source egress proof.
6. Kubernetes egress smoke proving sanitized Pod env, Envoy-only NetworkPolicy,
   wrong-token denial, direct-bypass denial, and all-node ACK.
7. Six-hour fail-fast soak including controller/orchestrator/Envoy rolling
   restarts and PostgreSQL reconnects.

Any missing gate keeps the release at **No-Go**.
