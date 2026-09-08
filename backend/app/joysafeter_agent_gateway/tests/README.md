# Agent Gateway tests

- `unit/` contains white-box unit tests grouped by the source module they verify.
  Source modules include these files with `#[cfg(test)]` and `#[path = ...]`, so
  tests can exercise private invariants without widening production visibility.
- Top-level `tests/*.rs` files are reserved for black-box integration and
  contract tests that use only the crate's public API.
- Live Kubernetes HA and xDS recovery checks are in
  `deploy/tests/e2e_agent_gateway.sh`; its default `invariants` mode is
  read-only, while `failover`, `envoy-recovery`, `soak`, and `all` delete test
  pods and must only be run against an approved non-production namespace.

Unit test files use the `<module>_test.rs` suffix and mirror the `src/` module
hierarchy, for example `src/xds/auth.rs` maps to
`tests/unit/xds/auth_test.rs`.
