# SP-1: Truthful Capability / Isolation Profile Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale, Docker-centric provider capability taxonomy (`NetworkIsolation` enum + `has_egress_management` bool) with a typed `IsolationProfile` so each provider declares what egress isolation it can actually enforce, and the resolver's fail-closed gate matches on it.

**Architecture:** `ProviderCapabilities` drops `has_egress_management: bool` and `network_isolation: NetworkIsolation`, gaining a single `isolation: IsolationProfile` field. `IsolationProfile` is `Open | PlatformManaged | Mediated { boundary: EgressBoundary }`, with `EgressBoundary` = `EnvoySocket | SharedEnvoy`. A method `IsolationProfile::manages_egress()` (`true` only for `Mediated`) replaces every `has_egress_management` read. This is a **behavior-preserving** migration: the gate decision is identical (Mediated ⇔ old `has_egress_management == true`); only the type representation changes, and it corrects K8s to declare `Mediated { SharedEnvoy }` instead of the misleading `Platform`. No enforcer split (that is SP-2), no credential changes (SP-3).

**Tech Stack:** Rust, cargo, `async_trait`. Crate dir: `backend/app/joysafeter_orchestrator_rs`.

## Global Constraints

- Behavior-preserving: the resolver fail-closed gate and warm-pool skip must make the identical decision for every provider before and after. Verify via the existing resolver/k8s tests staying green.
- No new dependencies.
- Both Docker and K8s providers compile and their tests pass at the end of each task.
- Commit message style is conventional commits, matching repo history (`refactor:`, `test:`, `feat:`).
- All `cargo` commands run from `backend/app/joysafeter_orchestrator_rs`.

---

### Task 1: Migrate the capability taxonomy to a typed `IsolationProfile`

Atomic type migration — the crate will not compile until the new types and all
consumers change together, so this is one test cycle. Existing tests are
translated to the new API with equivalent assertions (K8s `Platform` →
`Mediated { SharedEnvoy }`, the intended taxonomy correction).

**Files:**
- Modify: `src/sandbox/provider.rs` (types, `ProviderCapabilities`, default `capabilities()`, conformance tests)
- Modify: `src/sandbox/docker.rs:23` (import) and `:847-857` (`capabilities()`)
- Modify: `src/sandbox/k8s.rs:14` (import), `:790-805` (`capabilities()`), `:915-923` (tests)
- Modify: `src/sandbox/e2b.rs:8` (import) and `:186-191` (`capabilities()`)
- Modify: `src/sandbox/daytona.rs:8` (import) and `:199-204` (`capabilities()`)
- Modify: `src/kernel/sandbox_resolver.rs:581` (gate) and `:1802-1807` (test provider `capabilities()`)
- Modify: `src/kernel/sandbox_controller.rs:978` (warm-pool skip)

**Interfaces:**
- Produces:
  - `enum IsolationProfile { Open, PlatformManaged, Mediated { boundary: EgressBoundary } }` (Debug, Clone, PartialEq, Eq)
  - `enum EgressBoundary { EnvoySocket, SharedEnvoy }` (Debug, Clone, PartialEq, Eq)
  - `impl IsolationProfile { pub fn manages_egress(&self) -> bool }` — `true` iff `Mediated`
  - `struct ProviderCapabilities { pub has_host_mount: bool, pub isolation: IsolationProfile }`
- Consumes: existing `SandboxProvider` trait, `ProviderCapabilities` (reshaped), `file_injection::select_strategies_from_capabilities` (unchanged — still reads `has_host_mount`).

- [ ] **Step 1: Replace the enum and struct in `src/sandbox/provider.rs`**

Replace the `NetworkIsolation` enum and `ProviderCapabilities` struct (lines 20–43) with:

```rust
/// What egress isolation a provider can actually enforce for a sandbox.
///
/// Only `Mediated` is a credential boundary; it is the sole profile permitted to
/// run secret-backed or limited-networking sandboxes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IsolationProfile {
    /// No isolation — sandbox has full outbound access.
    Open,
    /// The platform (E2B/Daytona) isolates the sandbox internally, but JoySafeter
    /// does not mediate credentialed egress. Not a credential boundary.
    PlatformManaged,
    /// JoySafeter mediates credentialed egress (allowlist + credential injection)
    /// through the given boundary.
    Mediated { boundary: EgressBoundary },
}

/// Where and how a sandbox reaches its mediated egress boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EgressBoundary {
    /// Docker: per-sandbox Envoy listeners over a Unix socket volume.
    EnvoySocket,
    /// K8s: an in-cluster shared Envoy HTTP(S) service.
    SharedEnvoy,
}

impl IsolationProfile {
    /// True when this profile mediates credentialed egress — the replacement for
    /// the former `has_egress_management` boolean.
    pub fn manages_egress(&self) -> bool {
        matches!(self, IsolationProfile::Mediated { .. })
    }
}

/// Capabilities declared by a provider, used by the framework to select
/// strategies (e.g., file injection, networking) without provider-specific
/// branching.
#[derive(Debug, Clone)]
pub struct ProviderCapabilities {
    /// Provider supports host filesystem bind-mounts (Docker volumes).
    /// When true, the HostMount file injection strategy is available.
    pub has_host_mount: bool,
    /// Egress isolation this provider can enforce.
    pub isolation: IsolationProfile,
}
```

- [ ] **Step 2: Update the default `capabilities()` in `src/sandbox/provider.rs` (lines 182–188)**

```rust
    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            isolation: IsolationProfile::Open,
        }
    }
```

- [ ] **Step 3: Update `src/sandbox/docker.rs`**

Change the import at line 23 from `NetworkIsolation, ProviderCapabilities, ...` to `EgressBoundary, IsolationProfile, ProviderCapabilities, ...` (drop `NetworkIsolation`, keep the rest of that `use` list intact). Replace `capabilities()` (lines 847–857):

```rust
    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: true,
            isolation: if self.envoy_manager.is_some() {
                IsolationProfile::Mediated {
                    boundary: EgressBoundary::EnvoySocket,
                }
            } else {
                IsolationProfile::Open
            },
        }
    }
```

- [ ] **Step 4: Update `src/sandbox/k8s.rs`**

Change the import at line 14 to `EgressBoundary, IsolationProfile, ProviderCapabilities, ...` (drop `NetworkIsolation`). Replace `capabilities()` (lines 790–805):

```rust
    fn capabilities(&self) -> ProviderCapabilities {
        let egress_ready = self.egress_management_enabled
            && self.shared_envoy_network_target.is_some()
            && self.orchestrator_network_target.is_some();
        ProviderCapabilities {
            has_host_mount: false,
            isolation: if egress_ready {
                IsolationProfile::Mediated {
                    boundary: EgressBoundary::SharedEnvoy,
                }
            } else {
                IsolationProfile::Open
            },
        }
    }
```

(Leave the `info!(... has_egress_management = ...)` log block at lines 75–85 unchanged — it computes a local bool for logging and does not touch `ProviderCapabilities`.)

- [ ] **Step 5: Update `src/sandbox/e2b.rs` and `src/sandbox/daytona.rs`**

In both files, change the import (line 8 in each) to replace `NetworkIsolation` with `IsolationProfile`. Replace each `capabilities()` body (e2b.rs 186–191, daytona.rs 199–204) with:

```rust
    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            isolation: IsolationProfile::PlatformManaged,
        }
    }
```

- [ ] **Step 6: Update the resolver gate and its test provider in `src/kernel/sandbox_resolver.rs`**

Line 581, change the gate condition:

```rust
        if context.requires_egress_management() && !capabilities.isolation.manages_egress() {
```

Lines 1802–1807, replace the `RecordingProvider::capabilities()` body:

```rust
        fn capabilities(&self) -> crate::sandbox::provider::ProviderCapabilities {
            use crate::sandbox::provider::{EgressBoundary, IsolationProfile, ProviderCapabilities};
            ProviderCapabilities {
                has_host_mount: false,
                isolation: if self.egress_management_disabled {
                    IsolationProfile::Open
                } else {
                    IsolationProfile::Mediated {
                        boundary: EgressBoundary::EnvoySocket,
                    }
                },
            }
        }
```

- [ ] **Step 7: Update the warm-pool skip in `src/kernel/sandbox_controller.rs` (line 978)**

```rust
        if self.provider.capabilities().isolation.manages_egress() {
```

- [ ] **Step 8: Translate the conformance tests in `src/sandbox/provider.rs`**

Replace the helper and the two test bodies (lines 227–266). Note `NetworkIsolation` no longer exists; use `IsolationProfile`/`EgressBoundary` (in scope via `use super::*`):

```rust
    fn assert_no_credential_egress_boundary(provider: &impl SandboxProvider) {
        let capabilities = provider.capabilities();

        assert!(
            !capabilities.isolation.manages_egress(),
            "{} must not claim egress management until it can enforce allowlist + credential injection",
            provider.provider_name()
        );
    }

    #[test]
    fn provider_conformance_k8s_does_not_claim_egress_management_until_shared_envoy_exists() {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        let provider = K8sProvider::new(&config);

        assert_no_credential_egress_boundary(&provider);
        assert_eq!(provider.capabilities().isolation, IsolationProfile::Open);
    }

    #[test]
    fn provider_conformance_remote_platforms_do_not_claim_credential_egress_yet() {
        let daytona = DaytonaProvider::new("https://daytona.example", "test-key", "", "");
        let e2b = E2bProvider::new("https://e2b.example", "test-key", "template");

        assert_no_credential_egress_boundary(&daytona);
        assert_no_credential_egress_boundary(&e2b);
        assert_eq!(
            daytona.capabilities().isolation,
            IsolationProfile::PlatformManaged
        );
        assert_eq!(
            e2b.capabilities().isolation,
            IsolationProfile::PlatformManaged
        );
    }
```

- [ ] **Step 9: Translate the K8s capability test in `src/sandbox/k8s.rs` (lines 915–923)**

```rust
    #[test]
    fn k8s_capability_requires_explicit_enablement_and_shared_envoy_config() {
        assert!(!provider().capabilities().isolation.manages_egress());
        assert!(!provider_with_shared_envoy().capabilities().isolation.manages_egress());

        let enabled = provider_with_enabled_shared_envoy().capabilities();
        assert!(enabled.isolation.manages_egress());
    }
```

(The exact `Mediated { boundary: SharedEnvoy }` assertion is added in Task 2.)

- [ ] **Step 10: Build the whole crate**

Run: `cargo build`
Expected: `Finished` with no errors. (Pre-existing warnings such as `event::*` unused are acceptable; there must be no `error[...]` and no new warnings referencing `NetworkIsolation` or `has_egress_management`.)

- [ ] **Step 11: Run the affected tests**

Run: `cargo test --bin joysafeter-orchestrator -- provider_conformance sandbox_resolver k8s_capability`
Expected: PASS — including `provider_conformance_k8s_does_not_claim_egress_management_until_shared_envoy_exists`, `provider_conformance_remote_platforms_do_not_claim_credential_egress_yet`, the resolver `egress_tests` gate tests, and `k8s_capability_requires_explicit_enablement_and_shared_envoy_config`.

- [ ] **Step 12: Confirm no stale symbols remain**

Run: `grep -rn "NetworkIsolation\|has_egress_management" src --include="*.rs"`
Expected: the only match is the log-only `has_egress_management = ...` field in `src/sandbox/k8s.rs` (lines ~75–85). No `NetworkIsolation` matches anywhere.

- [ ] **Step 13: Commit**

```bash
git add src/sandbox/provider.rs src/sandbox/docker.rs src/sandbox/k8s.rs src/sandbox/e2b.rs src/sandbox/daytona.rs src/kernel/sandbox_resolver.rs src/kernel/sandbox_controller.rs
git commit -m "refactor: replace has_egress_management bool with typed IsolationProfile"
```

---

### Task 2: Strengthen conformance to assert the typed egress contract

Additive test-only change. Separable from Task 1: a reviewer could accept the
migration but want different guarantees here. Adds the SP-1 invariant ("only
`Mediated` manages egress") at the type level and pins K8s's enabled boundary.

**Files:**
- Modify: `src/sandbox/provider.rs` (add one test to `provider_conformance_tests`)
- Modify: `src/sandbox/k8s.rs:915-923` (assert the exact `Mediated { SharedEnvoy }` variant)

**Interfaces:**
- Consumes: `IsolationProfile`, `EgressBoundary`, `IsolationProfile::manages_egress` from Task 1.

- [ ] **Step 1: Add the invariant test in `src/sandbox/provider.rs`**

Add inside `mod provider_conformance_tests` (after the existing tests):

```rust
    #[test]
    fn provider_conformance_only_mediated_profiles_manage_egress() {
        assert!(IsolationProfile::Mediated {
            boundary: EgressBoundary::SharedEnvoy
        }
        .manages_egress());
        assert!(IsolationProfile::Mediated {
            boundary: EgressBoundary::EnvoySocket
        }
        .manages_egress());
        assert!(!IsolationProfile::Open.manages_egress());
        assert!(!IsolationProfile::PlatformManaged.manages_egress());
    }
```

- [ ] **Step 2: Run the new test**

Run: `cargo test --bin joysafeter-orchestrator -- provider_conformance_only_mediated_profiles_manage_egress`
Expected: PASS. (This is a pure logic test over Task 1's `manages_egress`; it asserts the SP-1 invariant directly. If it fails, `manages_egress` from Task 1 is wrong and must be revisited.)

- [ ] **Step 3: Pin the K8s enabled boundary in `src/sandbox/k8s.rs`**

Replace the enabled assertion block in `k8s_capability_requires_explicit_enablement_and_shared_envoy_config`:

```rust
        let enabled = provider_with_enabled_shared_envoy().capabilities();
        assert_eq!(
            enabled.isolation,
            IsolationProfile::Mediated {
                boundary: EgressBoundary::SharedEnvoy
            }
        );
```

- [ ] **Step 4: Run the conformance and k8s tests**

Run: `cargo test --bin joysafeter-orchestrator -- provider_conformance k8s_capability`
Expected: PASS for all, including the new `provider_conformance_only_mediated_profiles_manage_egress` and the pinned `k8s_capability_requires_explicit_enablement_and_shared_envoy_config`.

- [ ] **Step 5: Commit**

```bash
git add src/sandbox/provider.rs src/sandbox/k8s.rs
git commit -m "test: assert only Mediated isolation manages egress and K8s uses SharedEnvoy boundary"
```

---

## Self-Review

**Spec coverage (SP-1 section of the design doc):**
- "Replace `NetworkIsolation` + `has_egress_management` bool with typed `IsolationProfile` + `EgressBoundary`" → Task 1 Steps 1–7.
- "Make K8s declare its real capability behind the existing enable switch" → Task 1 Step 4 (`egress_ready` unchanged; now maps to `Mediated { SharedEnvoy }`).
- "Update the resolver's fail-closed gate to match on IsolationProfile" → Task 1 Step 6.
- "Extend `provider_conformance_*` tests to assert declarations" → Task 1 Step 8 (translate) + Task 2 (strengthen).
- "Foundational, small, behavior-preserving (no enforcer split)" → no trait methods removed; `setup_networking` untouched; gate decision preserved (Step 11 verifies).

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Every command shows expected output.

**Type consistency:** `IsolationProfile` / `EgressBoundary` / `manages_egress()` / `ProviderCapabilities.isolation` are used identically across Task 1 and Task 2. `has_host_mount` retained everywhere it was read (`file_injection.rs` needs no change). K8s enabled maps to `Mediated { SharedEnvoy }` consistently in Task 1 Step 4, Task 1 Step 9 (`manages_egress`), and Task 2 Step 3 (exact variant).

**One intended behavior note (not a gap):** K8s enabled previously declared `NetworkIsolation::Platform`; it now declares `Mediated { SharedEnvoy }`. The gate decision is unchanged (both mean "manages egress = true"); only the taxonomy is corrected, which is the explicit purpose of SP-1.
