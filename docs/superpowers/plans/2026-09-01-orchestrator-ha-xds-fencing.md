# Orchestrator HA and xDS Fencing Implementation Plan

1. Add xDS transport regression coverage for authority-bound TCP connections.
2. Implement epoch-bound connection admission and forced transport shutdown.
3. Extract the Redis instance registry and add self-healing heartbeat tests.
4. Register the heartbeat loop with critical runtime supervision.
5. Add exact bridge-generation ownership to local and Redis bridge stores.
6. Fence bridge-health recovery before DB and provider side effects.
7. Introduce structured sandbox destruction outcomes at the provider boundary.
8. Make Kubernetes deletion node-aware and residual cleanup non-fatal.
9. Update lifecycle callers and regression tests for partial destruction.
10. Harden Helm topology, disruption budget, and Envoy connection lifetime.
11. Add opt-in Kubernetes xDS failover and Redis recovery verification.
12. Run focused Rust, Python contract, Helm, and shell verification suites.
