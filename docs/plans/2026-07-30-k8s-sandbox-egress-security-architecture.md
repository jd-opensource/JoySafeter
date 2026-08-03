# K8s Sandbox Egress and Secret Boundary Architecture

Status: superseded by the shared Envoy + durable PostgreSQL authority architecture; Phase 0/1 guardrails remain valid, while the Phase 2 HTTP proxy path has been removed from runtime code and manifests.
Date: 2026-07-30

## Implementation Status

Implemented in Phase 0:

- K8s Pod manifest generation rejects real LLM secret env values before
  serializing the Pod spec.
- The resolver now requires provider egress management before resolving any
  sandbox context that has limited networking, credential routes, or real LLM
  secret env values.
- K8s defaults to `has_egress_management=false`, so secret-backed model tasks
  fail closed unless shared Envoy, durable authority, NetworkPolicy targets, and
  explicit `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true` switch are all
  configured.
- Regression tests cover real-secret rejection, placeholder allowance, and the
  resolver capability gate.

Implemented in Phase 1:

- Added provider-neutral `sandbox::egress_policy` types for credential routes,
  sandbox credentials, egress policy, upstream targets, placeholder hosts, and
  deterministic upstream naming.
- Kept `lds_backend` as an Envoy renderer with a narrow compatibility re-export
  while resolver/provider call sites move to the neutral module.
- Moved LLM route construction and LLM host allowlist/private-network
  validation into `kernel::llm_egress`, outside the sandbox lifecycle resolver.
- Moved MCP, Git, and external-service credential route construction into
  `kernel::credential_egress`, leaving `sandbox_resolver` responsible for
  lifecycle orchestration instead of route-building details.
- Added provider conformance tests around shared egress policy rendering and
  provider capability declarations, so providers without a credential boundary
  cannot claim production egress management by accident.

Superseded Phase 2 HTTP proxy work:

- The standalone Rust HTTP proxy binary, policy-store contract, control API, and
  K8s manager adapter were removed after the architecture converged on shared
  Envoy + durable PostgreSQL authority.
- K8s provider capabilities remain disabled by default and become enabled only
  under the explicit production egress switch plus durable authority.
- Added sandbox token authentication using SHA-256 token hashes and
  constant-time comparison. Requests can authenticate with
  `x-joysafeter-sandbox-token`, `Authorization: Bearer <token>`, or common
  provider credential headers carrying the sandbox token (`x-api-key`,
  `api-key`, `x-goog-api-key`). ext_authz strips these sandbox-supplied
  credential headers before injecting real upstream credentials.
- Added route authorization for `/sandbox/{sandbox_id}/egress/{route_id}/...`
  so traffic is denied unless the sandbox has an installed policy route.
- Added upstream HTTP forwarding with policy-driven path/query rewriting,
  sandbox-supplied credential header stripping, platform credential injection,
  hop-by-hop header filtering, and structured fail-closed error mapping.
- Added K8s Pod env rewrite for limited-networking LLM placeholders:
  `http://llm-egress.internal` base URLs become per-route shared Envoy URLs, and
  provider SDK key env vars are populated with the per-sandbox runner token
  instead of real model credentials. Manifest tests cover Anthropic, OpenAI,
  Gemini, and Azure OpenAI.
- Added per-sandbox K8s `NetworkPolicy` rendering and setup wiring. The policy
  selects only the target sandbox Pod and allows egress only to DNS,
  orchestrator, and shared Envoy; it never encodes model-provider domains
  or hardcoded IPs. RBAC grants apply/update/patch for NetworkPolicies, not
  delete.
- Added K8s orchestrator startup recovery. On restart, the provider lists live
  limited-networking sandboxes from the database, reads the stored runner token
  from sandbox config, re-derives egress credentials from DB/Vault, reapplies the
  per-sandbox NetworkPolicy, and redeclares the durable policy. Real provider
  credentials are not persisted in xDS or K8s resources.
- Added tests for readiness, missing policy, missing/invalid token,
  unauthorized route, path allowlist escape, request rendering, and a real
  loopback upstream forwarding flow that verifies injected credentials without
  printing secret values.
- The shared Envoy path is explicitly gated in K8s provider capabilities:
  `has_egress_management=true` only when
  `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true`, durable authority is
  configured, and both orchestrator and shared Envoy NetworkPolicy targets resolve.
- The orchestrator image now includes only the `joysafeter-orchestrator` binary;
  the k3s base manifests do not run a separate Rust HTTP proxy Deployment/Service.
- Added `deploy/k8s/k3s-egress-smoke.sh` and `VALIDATION_MODE=egress` support
  in `k3s-long-run.sh`. These scripts preserve evidence and do not delete
  users, Secrets, Environments, Agents, Tasks, Pods, Jobs, namespaces, PVCs, or
  database rows.
- K8s runtime resources are applied with server-side apply so sandbox env values
  are not persisted into `kubectl.kubernetes.io/last-applied-configuration`.
  The egress smoke rejects sandbox Pods that carry env values in annotations.
- Full egress smoke now requires the model-backed task output to contain
  `K3S_EGRESS_OK`. `ALLOW_UPSTREAM_MODEL_ERROR=true` is reserved for
  connectivity-only checks when an upstream key reaches the provider but is not
  authorized for the selected model.
- K8s sandbox and NetworkPolicy runtime operations now use the Kubernetes API
  client, not `kubectl`: Pods are created/executed/deleted via `kube::Api<Pod>`,
  and per-sandbox NetworkPolicies are server-side-applied/deleted/listed via
  `kube::Api<NetworkPolicy>`.
- K8s per-sandbox NetworkPolicy lifecycle cleanup is implemented: explicit and
  passive destroy paths call enforcer teardown, teardown deletes the named
  policy idempotently, and orchestrator startup recovery prunes platform-owned
  policies whose sandbox row is no longer live. Live validation on 2026-08-03
  pruned 15 destroyed-sandbox policies and left one `idle` live policy intact.
- K8s smokes now fail fast on runtime architecture drift, API-only image shape,
  sandbox Pod client-side apply annotations, and orchestrator RBAC for Pod
  create/delete/exec plus NetworkPolicy get/list/create/patch/delete.
- Durable egress apply-state now has a serialized PostgreSQL recompute path:
  ACK, connect, disconnect, publish, and periodic backstop recomputes use a
  transaction-scoped advisory lock per `(group_key, generation)` so concurrent
  controller replicas do not lose ACK counts. Integration coverage includes the
  lost-update race, disconnect convergence, ticker convergence, and the
  ACK-before-apply-row publish ordering race.
- Live 2×2 HA JDCloud Anthropic-compatible validation on 2026-08-03 passed
  through the shared Envoy path with two egress-controller replicas and two
  Envoy replicas: task `019fc5f7-0088-7e52-b893-b937d870e5e4`, sandbox
  `019fc5f7-0093-7c73-955e-f0f8a665f32b`, generation `42`, output
  `K3S_EGRESS_OK`. The DB apply-status row was `applied` with
  `connected_nodes=2`, `required_acks=4`, `acked_acks=4`, and four node ACKs
  with zero NACKs.
- JDCloud compatibility root cause was narrowed to Claude Code 2.1.220's
  default request surface, not the egress boundary: captured CLI requests send
  `?beta=true`, `anthropic-beta`, auto-title prompts, `thinking`, metadata,
  streaming, system blocks, and tool schemas. Minimal Messages requests through
  the Envoy route succeeded. The smoke Agent now sets Claude Code compatibility
  env vars to disable title/thinking/experimental-beta behavior for the egress
  proof; broader provider normalization/error taxonomy remains product work.

Not implemented yet:

- Long-run shared Envoy/controller/orchestrator HA chaos. A one-shot 2×2 live
  smoke passed, but repeated policy update/destroy/reuse cycles during rolling
  controller/envoy/orchestrator restarts still need to run end-to-end.
- Egress audit events, metrics, request timeouts, streaming-body hardening,
  and detailed upstream error classification.
- Provider compatibility/error taxonomy for Anthropic-compatible gateways that
  accept only a subset of Anthropic Messages or Claude Code SDK parameters.
  JDCloud accepted minimal Messages through Envoy but rejected the default
  Claude Code 2.1.220 beta/thinking/title/tool request shape until the smoke
  disabled those CLI features; product agents need provider capability profiles
  or explicit, structured failure messaging.
- Production long-run/chaos validation for K8s NetworkPolicy lifecycle under
  controller restarts, concurrent sandbox destroy/reuse, and multi-replica
  orchestrator rollout.

## Context

JoySafeter has two materially different sandbox execution paths today:

- Docker provider: has a mature limited-networking path based on `NetworkMode=none`
  plus Envoy Unix-socket listeners.
- K8s provider: can create sandbox Pods, but does not yet implement the same
  egress and secret boundary.

The k3s validation exposed the gap. A real Claude Secret was attached to an
Agent and the sandbox Pod started correctly, but the model call failed because
the sandbox namespace has deny-by-default egress and no production-grade model
egress path. More importantly, the current K8s provider writes decrypted Secret
values directly into the Pod env, which makes them visible in Pod specs and is
not acceptable for production.

This design treats K8s as a first-class execution plane, not as a small patch on
the current Pod launcher.

## Current Implementation Assessment

### Docker provider strengths

The Docker provider already has the right security shape:

- Limited networking becomes `NetworkMode=none`.
- The sandbox mounts the shared socket volume and reaches the orchestrator via
  `unix:///sockets/{sandbox_id}/grpc.sock`.
- LLM credentials are removed from sandbox env.
- The sandbox receives non-secret placeholder credentials so CLIs do not fall
  back to interactive login.
- The real upstream host, path, TLS mode, and credential header are held in
  Envoy policy.
- Envoy injects real credentials at the egress boundary and denies unmatched
  hosts.

Relevant code:

- `sandbox_resolver.rs`: derives limited networking, removes LLM keys from env,
  rewrites base URL to `llm-egress.internal`, and builds credential routes.
- `docker.rs`: uses `network_mode=none`, mounts `/sockets`, and delegates
  networking setup to Envoy.
- `envoy.rs` / `lds_backend.rs`: creates per-sandbox gRPC and HTTP listeners,
  dynamic upstream clusters, host/path rewrites, and credential injection.

### K8s provider status

The original K8s provider gaps are mostly closed for secret-backed LLM tasks:

- It creates Pods through the Kubernetes API and rewrites real LLM credential env
  to sandbox-scoped placeholders before the Pod manifest is submitted.
- It no longer shells out to runtime `kubectl`; Pod create/exec/delete and
  NetworkPolicy apply/list/delete use the Kubernetes API client.
- It delegates credentialed egress to the shared Envoy + durable authority path,
  with per-sandbox NetworkPolicy allowing only DNS, orchestrator, and shared Envoy.
- It fails closed when an Agent needs a Secret but no K8s shared-Envoy enforcer is
  available.
- It cleans up platform-owned per-sandbox NetworkPolicies on explicit/passive
  destroy and prunes destroyed-sandbox policies during startup recovery.

Remaining gaps:

- Live HA/chaos evidence is still missing for multi-replica shared Envoy and
  egress-controller rollouts under active sandbox traffic. The code has durable
  PostgreSQL reconciliation and serialized apply-state recompute, but the
  production proof still needs repeated rollout/failover runs.
- Generic `NetworkPolicy` cannot express FQDN allowlists; Envoy enforces product
  host policy while NetworkPolicy restricts the sandbox to the egress boundary.
- Structured upstream error classification still needs product-facing polish for
  "bad model", "bad key", provider 4xx/5xx, and upstream timeout cases.

### Why small fixes are wrong

Adding a hardcoded `ipBlock` for the current DNS answer of `ai-api.jdcloud.com`
is not a production design:

- DNS answers can change.
- Multiple model gateways or regional endpoints cannot be represented safely.
- Kubernetes `NetworkPolicy` is IP/CIDR based and cannot enforce domain policy.
- It does not solve Secret exposure in Pod specs.
- It creates a second, weaker security model for K8s than Docker.

## Design Goals

1. Preserve Docker's security invariant across all infrastructure:
   sandbox does not hold real model credentials.
2. Make K8s production-grade, not just smoke-test capable.
3. Support multiple execution backends: Docker, K8s/k3s, E2B, Daytona, and
   future ECS/Nomad-like runtimes.
4. Keep egress policy domain-oriented at the product layer.
5. Make the default mode deny-by-default.
6. Make failures attributable and user-actionable.
7. Keep temporary local validation separate from production architecture.

## Non-Goals

- Do not make every sandbox directly reachable from the internet.
- Do not rely on cluster-wide permissive egress.
- Do not require users to know Kubernetes, Envoy, or NetworkPolicy.
- Do not store or log prompts/responses in the egress boundary unless a separate
  product decision enables content observability.
- Do not put decrypted provider keys in Pod specs, ConfigMaps, annotations, or
  logs.

## Security Invariants

These must hold for every provider:

1. A sandbox receives only non-sensitive public env and placeholder credentials.
2. A sandbox cannot call arbitrary external hosts by default.
3. Real provider credentials are decrypted only in the control/egress boundary.
4. Egress policy is scoped by `project_id`, `session_id`, and `sandbox_id`.
5. Every egress decision is auditable without logging credential values.
6. Provider implementations must fail closed if they cannot enforce the required
   isolation profile.
7. Restart recovery must rebuild egress policy from database state without
   relying on stale in-memory state.

## Target Architecture

```text
Browser / API clients
  -> API
  -> PostgreSQL / Redis
  -> Orchestrator
      -> SandboxProvider
          -> Docker container
          -> K8s Pod
          -> E2B / Daytona / future provider
      -> EgressPolicyManager
      -> CredentialBroker

Sandbox
  -> Orchestrator gRPC channel
  -> Shared Envoy
      -> Policy check
      -> Credential injection
      -> Domain/path allowlist
      -> Upstream model / MCP / Git / external service
```

The sandbox should never know whether the real upstream is
`api.anthropic.com`, `ai-api.jdcloud.com`, Azure OpenAI, or an internal gateway.
It calls a platform-controlled placeholder endpoint. The egress boundary maps
that placeholder to the real upstream and injects the right headers.

## Unified Provider Contract

The current `SandboxCreateConfig.env` is too broad. It mixes public env,
runtime identity, and decrypted Secret values. Replace it conceptually with:

```text
SandboxCreateConfig
  sandbox_id
  image
  labels
  resources
  public_env
  runtime_identity
  mounts
  isolation_profile
  egress_policy_ref
```

`public_env` may include:

- non-sensitive model name
- placeholder base URLs
- placeholder API keys
- runtime feature flags

`runtime_identity` may include:

- sandbox id
- runner token
- orchestrator URL
- short-lived egress token or mounted service identity

It must not include:

- provider API keys
- OAuth tokens
- Git tokens
- MCP credentials

## Egress Policy Model

Policy should be provider-neutral:

```text
EgressPolicy
  sandbox_id
  project_id
  session_id
  routes:
    - kind: llm | mcp | git | external
      placeholder_host
      match_prefix
      upstream_host
      upstream_port
      upstream_tls
      upstream_prefix
      credential_ref
      inject_header
      allowed_methods
      allowed_paths
```

The existing Docker `EgressCredentialRoute` is close to this shape. The design
should generalize it rather than inventing a parallel K8s-only policy.

## K8s Production Design

### Components

1. Shared Envoy fleet
   - Runs in the egress namespace.
   - Receives sandbox HTTP(S) model/MCP/Git/external traffic.
   - Calls orchestrator ext_authz for sandbox identity, route authorization, and
     credential injection.
   - Emits audit metrics/events.

2. `K8sEnvoyNetworkPreparer`
   - Implemented behind the `EgressEnforcer` contract.
   - Creates/updates per-sandbox NetworkPolicy and relies on durable authority for
     per-sandbox policy desired state.
   - Does not put provider credentials into sandbox Pods.

3. `CredentialBroker`
   - Decrypts managed Secrets.
   - Provides credentials to ext_authz in memory.
   - Never serializes decrypted provider keys to Kubernetes Pod specs.

4. `NetworkPolicy`
   - Default deny for sandbox namespace.
   - Allow DNS.
   - Allow orchestrator gRPC.
   - Allow shared Envoy.
   - Do not allow direct model gateway egress from sandbox Pods.

### Sandbox Pod Shape

The sandbox Pod should receive:

```text
JOYSAFETER_SANDBOX_ID=<uuid>
JOYSAFETER_ORCHESTRATOR_URL=http://joysafeter-orchestrator...:9090
JOYSAFETER_EGRESS_BASE_URL=https://shared-envoy.../v1/sandbox/<id>/route/<route>
JOYSAFETER_EGRESS_TOKEN=<short-lived sandbox token>
ANTHROPIC_BASE_URL=https://shared-envoy.../v1/sandbox/<id>/route/<route>
ANTHROPIC_API_KEY=joysafeter-placeholder-anthropic-api-key
ANTHROPIC_MODEL=<model>
```

It must not receive:

```text
ANTHROPIC_API_KEY=<real key>
ANTHROPIC_AUTH_TOKEN=<real token>
OPENAI_API_KEY=<real key>
Git token
MCP OAuth token
```

### Shared Envoy Request Flow

```text
1. Runner/CLI sends request to placeholder base URL.
2. NetworkPolicy allows only the shared Envoy destination.
3. Envoy/ext_authz authenticates sandbox by mTLS, service account token, or short-lived
   runner/egress token.
4. ext_authz looks up policy by sandbox_id.
5. ext_authz validates route kind, method, path, and upstream host.
6. ext_authz retrieves credential from CredentialBroker.
7. Envoy/ext_authz removes sandbox-supplied auth headers.
8. Envoy/ext_authz injects platform credential header.
9. Envoy forwards to real upstream.
10. Envoy/ext_authz records audit metadata and returns upstream response.
```

### Egress Boundary Implementation Options

Chosen path for the K8s MVP:

- Use shared Envoy plus orchestrator ext_authz.
- Integrate CredentialBroker and structured audit in the orchestrator.
- Keep the route model aligned with Docker's `EgressCredentialRoute`.
- Add a control-plane API, Redis watcher, or DB watcher for policy updates
  before enabling K8s provider egress management.

Still viable later:

- Add an in-cluster Envoy boundary controlled by orchestrator-generated xDS or
  config snapshots if Rust proxy behavior becomes too broad to maintain.

Production-hardening option:

- Use Cilium FQDN policy or an enterprise egress boundary below JoySafeter.
- This is additive. It should not replace application-layer credential
  injection and policy checks.

## Multi-Infrastructure Strategy

### Docker

Keep the existing Envoy Unix-socket model.

Required improvements:

- Make the Docker egress route model the shared model.
- Add tests proving no real model key remains in container env when limited
  networking is active.

### K8s / k3s

Implement the missing equivalent:

- Native Kubernetes client.
- `K8sEnvoyNetworkPreparer`.
- In-cluster shared Envoy fleet.
- No provider secret in Pod env.
- NetworkPolicy only allows shared Envoy and orchestrator.

### E2B / Daytona

Treat platform isolation as compute isolation only. Credential boundary still
belongs to JoySafeter unless the provider can prove equivalent guarantees.

Preferred mode:

- Remote sandbox uses JoySafeter shared egress boundary over a reachable endpoint.
- If unavailable, provider must declare `has_egress_management=false` and the
  orchestrator must fail closed for secret-backed Agents.

### Future Providers

Every new provider must declare:

- lifecycle support
- file injection support
- network isolation mechanism
- egress management support
- secret boundary support

Providers without egress management may only run offline or non-secret tasks.

## API and Configuration Changes

### Backend / Orchestrator config

Add explicit settings:

```text
JOYSAFETER_EGRESS_MODE=envoy|platform|disabled
JOYSAFETER_EGRESS_FAIL_CLOSED=true
JOYSAFETER_EGRESS_POLICY_BACKEND=db|redis|xds
JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS=...
```

`disabled` should be allowed only for local development and non-secret tasks.

### Provider capability enforcement

When an Agent or Environment references a Secret and networking is `limited`,
the orchestrator must require:

```text
provider.capabilities().has_egress_management == true
```

If false, fail before creating the sandbox with a structured error:

```text
SANDBOX_EGRESS_MANAGER_REQUIRED
```

### Secret validation

Secret creation/test should continue to validate base URL host against
`JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS`, but runtime must also validate the
resolved egress route before sandbox creation.

## Observability and Error Model

The platform should report where failure happened:

- `EGRESS_POLICY_DENIED`: host/path not allowlisted.
- `EGRESS_BOUNDARY_UNREACHABLE`: sandbox cannot reach shared Envoy.
- `UPSTREAM_CONNECT_FAILED`: shared Envoy cannot connect to upstream.
- `UPSTREAM_4XX`: upstream rejected key/model/request.
- `UPSTREAM_5XX`: model gateway unavailable.
- `SANDBOX_CLI_TIMEOUT`: CLI did not finish before task timeout.
- `SANDBOX_CANCEL_RELAY_FAILED`: cancel command could not reach runtime.

The current "API Error: Unable to connect to API (ConnectionRefused)" is too
low-level and does not identify whether the issue is policy, gateway, upstream,
or CLI behavior.

## Migration Plan

### Phase 0: Guardrails

- Stop documenting IP-based egress as an acceptable solution.
- Mark K8s provider as smoke-only for secret-backed real model tasks until
  shared Envoy + durable authority exists.
- Add fail-closed checks so K8s cannot silently run secret-backed Agents without
  egress management.
- Add tests that detect real provider keys in generated K8s Pod manifests.

### Phase 1: Shared Egress Policy Extraction

- Extract Docker's route construction into a provider-neutral module.
- Split `env` into public env and secret-derived egress policy.
- Preserve Docker behavior with parity tests.
- Add regression tests for Anthropic, OpenAI, Gemini, Azure, MCP, Git, and
  external services.

### Phase 2: K8s Shared Envoy MVP

- Add shared Envoy deployment and service.
- Add production policy backend and restart recovery.
- Add `K8sEnvoyNetworkPreparer`.
- Generate per-sandbox policy and expose it to durable authority.
- Rewrite K8s sandbox env to placeholder endpoints.
- Add NetworkPolicy allowing sandbox to shared Envoy and orchestrator only.
- Prove real model task completion through shared Envoy.

### Phase 3: Production Hardening

- Add shared Envoy HA and multi-replica rollout/chaos validation for the durable
  PostgreSQL policy/apply-state path.
- Add mTLS or short-lived token auth between sandbox and shared Envoy.
- Add audit events and Prometheus metrics.
- Add resource limits and autoscaling for shared Envoy.
- Add Cilium FQDN policy option for clusters that support it.
- Add long-run/chaos coverage for concurrent sandbox destroy/reuse and
  per-sandbox NetworkPolicy cleanup under orchestrator/controller rollouts.

### Phase 4: Multi-Provider Enforcement

- Apply the same fail-closed contract to E2B and Daytona.
- Require provider capability declarations in tests.
- Add conformance tests every provider must pass.

## Validation Matrix

### Security

- K8s generated Pod spec does not contain real `ANTHROPIC_API_KEY`.
- `kubectl get pod -o yaml` does not reveal provider secrets.
- Sandbox direct curl to model host is denied.
- Sandbox curl to shared Envoy is allowed.
- ext_authz denies unallowlisted host.
- ext_authz strips sandbox-supplied `authorization` / `x-api-key`.
- ext_authz injects the platform credential only for allowed routes.

### Runtime

- Claude baseline task completes through shared Envoy.
- OpenAI/Codex task completes through shared Envoy.
- MCP remote credential route works without exposing token to sandbox.
- Git credential route works without exposing token to sandbox.
- Task cancel reaches a running sandbox.
- Orchestrator restart rebuilds egress policy.
- Envoy/controller restart does not strand running sandboxes.

### Operations

- Long-run validation with repeated tasks.
- Concurrent sandbox creation under quota.
- Envoy/ext_authz latency and upstream status metrics are emitted.
- Upstream 4xx/5xx are mapped to structured task errors.

## Acceptance Criteria

K8s can be considered production-ready for secret-backed Agents only when:

1. No real provider Secret appears in sandbox Pod manifests.
2. Sandboxes cannot directly reach arbitrary external hosts.
3. All LLM/MCP/Git/external credentialed egress goes through the platform
   egress boundary.
4. Domain allowlist is enforced by product policy, not hardcoded IPs.
5. Failure modes are structured and actionable.
6. Restart recovery preserves or rebuilds egress policy.
7. Docker and K8s pass the same provider conformance test suite.

## Immediate Next Engineering Tasks

1. Run long-cycle k3s HA/chaos validation with real secret-backed LLM tasks,
   repeated policy updates, sandbox reuse/destroy, and rolling
   controller/envoy/orchestrator restarts.
2. Add provider capability profiles for Anthropic-compatible gateways so Claude
   Code beta/thinking/tool request shapes are either normalized or fail with a
   structured actionable error.
3. Add ext_authz audit events, metrics, request timeout policy, and structured
   upstream error classification.
4. Add production FQDN-policy integration for clusters with Cilium or equivalent
   DNS-aware NetworkPolicy support.

These tasks deliberately start with tests and contracts before adding new
infrastructure. The objective is to prevent another one-off path from becoming
the default production behavior.
