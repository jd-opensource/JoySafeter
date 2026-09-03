# Agent Gateway tests

- `unit/` contains white-box unit tests grouped by the source module they verify.
  Source modules include these files with `#[cfg(test)]` and `#[path = ...]`, so
  tests can exercise private invariants without widening production visibility.
- Top-level `tests/*.rs` files are reserved for black-box integration and
  contract tests that use only the crate's public API.

Unit test files use the `<module>_test.rs` suffix and mirror the `src/` module
hierarchy, for example `src/xds/auth.rs` maps to
`tests/unit/xds/auth_test.rs`.
