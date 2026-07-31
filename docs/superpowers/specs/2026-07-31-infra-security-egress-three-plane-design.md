# Infra/Security Collaboration: Three-Plane Egress Architecture

Status: design draft (brainstorming output), awaiting review
Date: 2026-07-31
Supersedes coupling described in: `docs/plans/2026-07-30-k8s-sandbox-egress-security-architecture.md`
Scope: architecture overview + decomposition roadmap. Each sub-project (SP-1/2/3)
gets its own detailed spec → plan → implementation cycle.

## Context

The K8s egress work (see the 2026-07-30 plan) introduced a provider-neutral
egress policy shared by Docker (Envoy) and K8s (gateway), and the module was
later consolidated under a single `src/egress/` tree. The domain now has a home,
but the **infrastructure plane (sandbox providers) and the security plane (egress
enforcement) are still entangled, and the core security invariant is enforced by
convention rather than by construction.** Concretely, from `src/sandbox/provider.rs`:

- `SandboxProvider` is a god-trait spanning four concerns: compute lifecycle,
  startup/shutdown hooks, **networking/egress enforcement**, and file injection.
- `setup_networking` has a **fail-open default**: the trait default body is
  `Ok(())`, so a provider that does not override it accepts plaintext credentials
  and silently succeeds while enforcing nothing. The only thing preventing a
  secret leak is a *separate* capability gate in the resolver. Two places must
  stay in sync; any path that reaches a provider without the resolver gate
  (warm-pool reuse, restart recovery, future direct-create) bypasses enforcement.
- Credentials flow as **values, not references**: `SandboxCredentials` carries
  plaintext `inject_headers`, which cross the orchestrator→provider boundary and,
  for K8s, the orchestrator→gateway HTTP control call, then sit in the gateway's
  in-memory store for every live sandbox. This diverges from the earlier design's
  own `credential_ref` model.
- The capability taxonomy is stale: `NetworkIsolation` has `None|Platform|Envoy`
  (Envoy — a Docker impl detail — leaks into a "neutral" type), and K8s declares
  `None` even though it can enforce gateway + NetworkPolicy.

**Goal:** restructure the infra/security collaboration into three planes with
explicit contracts so that the security invariant holds *by construction*, the
egress boundary never holds standing decrypted secrets, and Docker and K8s both
converge on the same target — migrated incrementally with both providers working
at every step.

## Design principles

1. **Security by construction, not convention.** "No enforcer" must be a
   wiring-time absence that makes secret-backed sandboxes un-runnable, not a
   defaulted `Ok(())`.
2. **Single decrypt point.** Real credentials are decrypted only at the egress
   boundary, resolved on demand from a reference. Neither data plane holds a
   standing decrypted-secret store.
3. **Provider-neutral policy, provider-specific enforcement.** The policy
   vocabulary and the credential broker are shared; only the binding to a
   concrete mechanism (Envoy vs gateway) is provider-specific.
4. **Strangler migration.** Docker and K8s stay green throughout; the target
   (including request-time credential resolution) applies to both.

## Target architecture: three planes

```text
Decision plane      (control, provider-neutral, security-owned)
  build ref-only SandboxEgressPolicy from DB/Vault
  compute required IsolationProfile for the task
  fail-closed gate: required ⊆ (provider × enforcer) capability
        │
        ▼
Enforcement plane   (data, provider-specific, infra-owned)
  EgressEnforcer binds policy → mechanism
    Docker → EnvoyEnforcer   (Envoy xDS listeners)
    K8s    → GatewayEnforcer (gateway policy + NetworkPolicy)
        │
        ▼
Credential plane    (broker, provider-neutral, security-owned)
  policy carries credential_ref only
  CredentialBroker resolves ref → secret at request time
  short-TTL memory cache; evicted on teardown
```

Collaboration sequence: resolver (decision) builds a ref-only policy and computes
the required profile → gate matches profile against provider+enforcer, fail-closed
if unmet → provider creates compute → enforcer binds policy to its mechanism → at
egress time the boundary asks the broker to resolve refs, injects, and forwards.

## Plane 1 — Decision (control)

Owner: `SandboxResolver` (kernel) + the `egress` policy builders.

- Builds `SandboxEgressPolicy` as **references only** (no secret values).
- Computes the required `IsolationProfile` from task shape: references a secret
  and/or limited networking ⇒ `Mediated`; otherwise `Open`/`PlatformManaged`.
- Runs the fail-closed gate: `required ⊆ enforcer.isolation()`. If the provider
  has no matching enforcer, fail before compute with `SANDBOX_EGRESS_MANAGER_REQUIRED`.

This plane already mostly exists; the change is that it composes an explicit
`Option<EgressEnforcer>` alongside the provider instead of calling a defaulted
trait method, and it emits ref-only policy.

## Plane 2 — Enforcement (data)

New provider-neutral trait, separate from `SandboxProvider`:

```rust
trait EgressEnforcer: Send + Sync {
    fn isolation(&self) -> IsolationProfile;   // what it actually enforces
    fn boundary(&self) -> EgressBoundary;      // where the sandbox reaches it
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        policy: &SandboxEgressPolicy,
    ) -> anyhow::Result<EnforcementHandle>;
    async fn teardown(&self, handle: EnforcementHandle) -> anyhow::Result<()>;
}
```

- `SandboxProvider` sheds `setup_networking`, `teardown_networking`, and the
  `has_egress_management` bool — returning to pure compute lifecycle.
- Capability becomes a typed `IsolationProfile` replacing `NetworkIsolation`:
  `Open` | `PlatformManaged` | `Mediated { boundary: EgressBoundary }`.
  (No `resolution` sub-field — target state is uniformly request-time, so
  distinguishing request- vs install-time would be speculative. Dropped per YAGNI.)
- `EgressBoundary` describes where/how the sandbox reaches the boundary
  (Docker: Unix socket path; K8s: gateway service URL) — making the previously
  config-hidden coupling explicit in the contract.
- Implementations are thin adapters over existing code: `EnvoyEnforcer` wraps the
  current Envoy/`lds_backend` setup; `GatewayEnforcer` wraps `K8sEgressManager` +
  NetworkPolicy rendering. E2B/Daytona provide no enforcer (or a
  `PlatformManaged` one only if platform isolation is proven).

The structural win: a secret-backed sandbox requires `Some(enforcer)`; there is
no defaulted no-op success path. Enforcement is independently testable without a
compute backend, and compute is testable without an egress mechanism.

## Plane 3 — Credential (broker)

Target: **the egress boundary holds no standing decrypted-secret store** for both
providers, reached in one step (no temporary value-push for Docker).

Policy schema change — `EgressCredentialRoute` replaces the plaintext
`inject_headers: Vec<(String, String)>` with:

```rust
credential_ref: CredentialRef,   // opaque, non-secret handle (vault/secret id + key + scope)
inject_header_name: String,      // e.g. "authorization", "x-api-key"
scheme: InjectScheme,            // Bearer | Basic | ApiKey | Raw
```

`CredentialRef` is safe to persist, log, and send over the control plane.

```rust
trait CredentialBroker: Send + Sync {
    async fn resolve(&self, cred_ref: &CredentialRef, scope: &SandboxScope)
        -> anyhow::Result<SecretMaterial>;
}
```

Backed by Vault/DB decrypt (`VaultCipher`), short-TTL in-memory cache keyed by
`ref + scope`, evicted on sandbox teardown. Rotation staleness is bounded by TTL.

**Two data planes, one broker, request-time resolution for both:**

- **K8s (Rust gateway):** the gateway is our own code, so it calls
  `CredentialBroker::resolve` **in-process** at request time. Zero standing secret
  is reached directly.
- **Docker (Envoy):** Envoy cannot call the Rust broker inline, so it uses an
  **ext_authz callout** to a small gRPC `CredentialResolutionService` that wraps
  the same `CredentialBroker`. Per request, Envoy calls the service with the
  sandbox/route identity; the service resolves the ref and returns the header to
  inject on the allow response (`ok_response.headers_to_add`). Envoy injects it,
  strips sandbox-supplied auth, and forwards. The Envoy LDS config no longer bakes
  in `inject_headers` values — it references the ext_authz filter. Zero standing
  secret is reached for Docker in the same sub-project.

  Choice: **ext_authz**, not ext_proc — ext_authz is purpose-built for
  per-request allow/deny + header injection, which is exactly this need. ext_proc
  (streaming body mutation) is heavier than required.

Envoy↔`CredentialResolutionService` must be authenticated (service identity +
per-sandbox context carried in the ext_authz request) so the service resolves the
correct ref for the calling sandbox and route.

## Data flow

**K8s target state:**
1. Resolver builds ref-only `SandboxEgressPolicy`; required = `Mediated`.
2. Gate: K8s paired with `GatewayEnforcer`, `isolation() ⊇ Mediated` ⇒ proceed
   (else `SANDBOX_EGRESS_MANAGER_REQUIRED`).
3. Provider creates Pod: public env + runtime identity + placeholder creds; no
   secrets.
4. `GatewayEnforcer::enforce`: installs ref-only policy to the gateway control
   API; renders per-sandbox NetworkPolicy (DNS + orchestrator + gateway only).
5. Sandbox calls `…/egress/llm`; NetworkPolicy allows only the gateway.
6. Gateway authenticates the sandbox token, authorizes the route, calls
   `CredentialBroker::resolve(ref, scope)` in-process, injects, strips
   sandbox-supplied auth, forwards to the real upstream.
7. Teardown: enforcer revokes gateway policy + NetworkPolicy; broker evicts cache.

**Docker target state:** identical decision/gate; `EnvoyEnforcer::enforce` renders
per-sandbox Envoy listeners whose routes reference the ext_authz filter (no baked
secrets). At request time Envoy → `CredentialResolutionService` → broker resolves
→ header injected → forwarded.

## Error model and invariants

Structured errors (from the prior plan, retained): `EGRESS_POLICY_DENIED`,
`EGRESS_GATEWAY_UNREACHABLE`, `UPSTREAM_CONNECT_FAILED`, `UPSTREAM_4XX`,
`UPSTREAM_5XX`, `SANDBOX_EGRESS_MANAGER_REQUIRED`. New: `CREDENTIAL_RESOLVE_FAILED`
(broker could not resolve a ref).

Invariants — must hold for every provider, verified by conformance tests:
1. A sandbox never holds real credentials (only public env + placeholders).
2. Policy leaving the control plane / persisted / logged carries refs only.
3. A secret-backed task requires an enforcer — absence fails closed *by
   construction* (no defaulted success path).
4. Neither data plane (Envoy config or gateway store) holds standing decrypted
   secrets; resolution is request-time.
5. Teardown revokes enforcement and evicts broker cache.
6. Restart rebuilds policy from DB refs without stale in-memory state.

## Decomposition and strangler roadmap

Three sub-projects, each its own spec → plan → implementation cycle; both
providers stay green after each.

- **SP-1 — Truthful capability/profile model.** Replace `NetworkIsolation` +
  `has_egress_management` bool with typed `IsolationProfile` + `EgressBoundary`.
  Make K8s declare its real capability (behind the existing enable switch).
  Conformance tests assert declarations. Foundational, small, no behavior change.
  Touch points: `src/sandbox/provider.rs`, each provider's `capabilities()`,
  `provider_conformance_*` tests.

- **SP-2 — EgressEnforcer extraction + fail-closed by construction.** Introduce
  `EgressEnforcer`; move `setup_networking`/`teardown_networking` logic into
  `EnvoyEnforcer` (Docker) and `GatewayEnforcer` (K8s) as thin adapters over
  existing code; make the resolver compose `(provider, Option<enforcer>)`; delete
  the `Ok(())` default. Behavior-preserving; the win is structural. Touch points:
  `src/egress/` (new enforcer module), `src/sandbox/provider.rs`,
  `src/kernel/sandbox_resolver.rs`, `src/sandbox/{docker,k8s}.rs`.

- **SP-3 — Credential reference plane + Broker (both providers request-time).**
  Change `EgressCredentialRoute` to refs; add `CredentialBroker`; K8s gateway
  resolves in-process; add the ext_authz `CredentialResolutionService` and rework
  `src/sandbox/lds_backend.rs` so Envoy references it instead of baking headers.
  Both providers reach zero standing secret. Largest sub-project. Touch points:
  `src/egress/policy.rs`, `src/egress/credential.rs`, `src/egress/gateway.rs`,
  `src/sandbox/lds_backend.rs`, new credential-resolution service + Broker.

Order: SP-1 → SP-2 → SP-3.

## Testing / conformance

A shared provider + enforcer conformance suite every infrastructure must pass,
extending the existing `provider_conformance_*` tests:
- Sandbox create config contains no real credentials.
- Policy leaving the control plane carries refs only (no secret values).
- A secret-backed task with no enforcer fails closed before compute.
- Teardown revokes enforcement and evicts the broker cache.
- Restart rebuilds policy from DB refs.
- Broker resolve returns correct material and evicts on teardown; resolve failure
  maps to `CREDENTIAL_RESOLVE_FAILED`.
- Gateway and Envoy both strip sandbox-supplied auth and inject only for allowed
  routes; neither holds a standing secret store (assert Envoy generated config
  carries no injected secret values, only the ext_authz reference).

## Open items to resolve in sub-project specs

- SP-1: exact `IsolationProfile` / `EgressBoundary` variants and how E2B/Daytona
  map onto them.
- SP-2: `EnforcementHandle` shape and how restart recovery re-derives it.
- SP-3: Envoy↔`CredentialResolutionService` authentication mechanism; broker cache
  TTL and eviction policy; `CredentialRef` encoding (vault id vs secret name+key).
