# K8s Sandbox Egress and Secret Boundary Architecture

Status: design accepted, Phase 0/1 guardrails complete, Phase 2 gateway core, K8s env/network policy wiring, startup recovery, and k3s validation entrypoints implemented
Date: 2026-07-30

## Implementation Status

Implemented in Phase 0:

- K8s Pod manifest generation rejects real LLM secret env values before
  serializing the Pod spec.
- The resolver now requires provider egress management before resolving any
  sandbox context that has limited networking, credential routes, or real LLM
  secret env values.
- K8s defaults to `has_egress_management=false`, so secret-backed model tasks
  fail closed unless the gateway URL/control token, NetworkPolicy targets, and
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

Implemented in Phase 2:

- Added a standalone `joysafeter-egress-gateway` Rust binary with `/healthz`,
  `/readyz`, and a fail-closed proxy entrypoint.
- Added an explicit gateway policy-store contract and in-memory implementation
  for tests and the next control-plane wiring step.
- Added an authenticated control-plane API to install and revoke per-sandbox
  policies at `PUT/DELETE /control/sandboxes/{sandbox_id}/policy`. The API
  requires `JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN`; without it, `/readyz`
  remains unavailable and policy mutation is disabled.
- Added an orchestrator-side `EgressGatewayControlClient` and `K8sEgressManager`.
  It installs/revokes per-sandbox gateway policy over HTTP using the shared
  `SandboxEgressPolicy` schema. K8s provider capabilities remain disabled by
  default and become enabled only under the explicit production egress switch.
- Added sandbox token authentication using SHA-256 token hashes and
  constant-time comparison. Requests can authenticate with
  `x-joysafeter-sandbox-token`, `Authorization: Bearer <token>`, or common
  provider credential headers carrying the sandbox token (`x-api-key`,
  `api-key`, `x-goog-api-key`). The gateway strips these sandbox-supplied
  credential headers before injecting real upstream credentials.
- Added route authorization for `/sandbox/{sandbox_id}/egress/{route_id}/...`
  so traffic is denied unless the sandbox has an installed policy route.
- Added upstream HTTP forwarding with policy-driven path/query rewriting,
  sandbox-supplied credential header stripping, platform credential injection,
  hop-by-hop header filtering, and structured fail-closed error mapping.
- Added K8s Pod env rewrite for limited-networking LLM placeholders:
  `http://llm-egress.internal` base URLs become
  `{JOYSAFETER_EGRESS_GATEWAY_URL}/sandbox/{sandbox_id}/egress/llm`, and
  provider SDK key env vars are populated with the per-sandbox runner token
  instead of real model credentials. Manifest tests cover Anthropic, OpenAI,
  Gemini, and Azure OpenAI.
- Added per-sandbox K8s `NetworkPolicy` rendering and setup wiring. The policy
  selects only the target sandbox Pod and allows egress only to DNS,
  orchestrator, and the egress gateway; it never encodes model-provider domains
  or hardcoded IPs. RBAC grants apply/update/patch for NetworkPolicies, not
  delete.
- Added K8s orchestrator startup recovery. On restart, the provider lists live
  limited-networking sandboxes from the database, reads the stored runner token
  from sandbox config, re-derives egress credentials from DB/Vault, reapplies the
  per-sandbox NetworkPolicy, and reinstalls the gateway policy. Real provider
  credentials are not persisted in gateway files or K8s resources.
- Added tests for readiness, missing policy, missing/invalid token,
  unauthorized route, path allowlist escape, request rendering, and a real
  loopback upstream forwarding flow that verifies injected credentials without
  printing secret values.
- The gateway path is explicitly gated in K8s provider capabilities:
  `has_egress_management=true` only when
  `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true`, gateway control is
  configured, and both orchestrator and gateway NetworkPolicy targets resolve.
- The orchestrator image now includes both `joysafeter-orchestrator` and
  `joysafeter-egress-gateway` binaries, and the k3s base manifests run the
  gateway as a dedicated Deployment/Service.
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

Not implemented yet:

- Production gateway HA policy backend. The current gateway binary has an
  in-memory policy store and authenticated mutation API. K8s orchestrator
  startup recovery can reinstall policies after orchestrator restart, but
  multi-replica gateway HA still needs a shared policy backend or a watch-based
  reconciler.
- Complete production orchestrator-side policy lifecycle cleanup semantics for
  sandbox destroy/reuse and platform-owned NetworkPolicy/gateway policy
  resources. Install and startup recovery exist, but explicit cleanup policy is
  still pending long-run validation and operator approval because it deletes
  platform-owned runtime objects.
- Gateway audit events, metrics, request timeouts, streaming-body hardening,
  and detailed upstream error classification.
- Production hardening for K8s NetworkPolicy lifecycle, including recovery and
  explicit cleanup semantics for platform-owned per-sandbox policies.
- Native Kubernetes client replacement for `kubectl`.

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

### K8s provider gaps

The K8s provider currently only creates Pods:

- It serializes `config.env` directly into Pod `env`.
- It shells out to `kubectl` instead of using a native Kubernetes API client.
- It has no provider-specific `setup_networking` implementation.
- It does not have a credential boundary equivalent to Docker Envoy.
- It relies on generic `NetworkPolicy`, which cannot express FQDN allowlists.
- It cannot distinguish "network denied", "gateway unavailable", "bad model",
  "bad key", and "upstream timeout" as structured platform errors.
- It does not fail closed when an Agent needs a Secret but no egress manager is
  available.

### Why small fixes are wrong

Adding a hardcoded `ipBlock` for the current DNS answer of `ai-api.jdcloud.com`
is not a production design:

- DNS answers can change.
- Multiple gateways or regional endpoints cannot be represented safely.
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
- Do not store or log prompts/responses in the egress gateway unless a separate
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
  -> Egress Gateway
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

1. `joysafeter-egress-gateway`
   - Runs in the control namespace.
   - Receives sandbox HTTP(S) model/MCP/Git/external traffic.
   - Authenticates sandbox identity.
   - Loads or receives per-sandbox egress policy.
   - Injects credentials.
   - Emits audit metrics/events.

2. `K8sEgressManager`
   - Implemented behind the `SandboxProvider::setup_networking` contract.
   - Creates/updates per-sandbox egress policy.
   - Optionally creates short-lived Kubernetes Secrets for non-provider runtime
     identity only.
   - Does not put provider credentials into sandbox Pods.

3. `CredentialBroker`
   - Decrypts managed Secrets.
   - Provides credentials to the gateway in memory.
   - Never serializes decrypted provider keys to Kubernetes Pod specs.

4. `NetworkPolicy`
   - Default deny for sandbox namespace.
   - Allow DNS.
   - Allow orchestrator gRPC.
   - Allow egress gateway.
   - Do not allow direct model gateway egress from sandbox Pods.

### Sandbox Pod Shape

The sandbox Pod should receive:

```text
JOYSAFETER_SANDBOX_ID=<uuid>
JOYSAFETER_ORCHESTRATOR_URL=http://joysafeter-orchestrator...:9090
JOYSAFETER_EGRESS_BASE_URL=http://joysafeter-egress-gateway.../sandbox/<id>/egress
JOYSAFETER_EGRESS_TOKEN=<short-lived sandbox token>
ANTHROPIC_BASE_URL=http://joysafeter-egress-gateway.../sandbox/<id>/egress/llm
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

### Gateway Request Flow

```text
1. Runner/CLI sends request to placeholder base URL.
2. NetworkPolicy allows only egress-gateway destination.
3. Gateway authenticates sandbox by mTLS, service account token, or short-lived
   runner/egress token.
4. Gateway looks up policy by sandbox_id.
5. Gateway validates route kind, method, path, and upstream host.
6. Gateway decrypts or retrieves credential from CredentialBroker.
7. Gateway removes sandbox-supplied auth headers.
8. Gateway injects platform credential header.
9. Gateway forwards to real upstream.
10. Gateway records audit metadata and returns upstream response.
```

### Gateway Implementation Options

Chosen path for the first K8s MVP:

- Implement a Rust egress gateway service using `hyper` / `reqwest`.
- Easier to integrate CredentialBroker and structured audit.
- Harder to match Envoy's mature proxy behavior.
- Keep the route model aligned with Docker's `EgressCredentialRoute`.
- Add a control-plane API, Redis watcher, or DB watcher for policy updates
  before enabling K8s provider egress management.

Still viable later:

- Add an in-cluster Envoy gateway controlled by orchestrator-generated xDS or
  config snapshots if Rust proxy behavior becomes too broad to maintain.

Production-hardening option:

- Use Cilium FQDN policy or an enterprise egress gateway below JoySafeter.
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
- `K8sEgressManager`.
- In-cluster egress gateway.
- No provider secret in Pod env.
- NetworkPolicy only allows gateway and orchestrator.

### E2B / Daytona

Treat platform isolation as compute isolation only. Credential boundary still
belongs to JoySafeter unless the provider can prove equivalent guarantees.

Preferred mode:

- Remote sandbox uses JoySafeter egress gateway over a reachable endpoint.
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
JOYSAFETER_EGRESS_MODE=envoy|gateway|platform|disabled
JOYSAFETER_EGRESS_FAIL_CLOSED=true
JOYSAFETER_EGRESS_GATEWAY_URL=http://joysafeter-egress-gateway...
JOYSAFETER_EGRESS_POLICY_BACKEND=db|redis|xds
JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN=...
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
- `EGRESS_GATEWAY_UNREACHABLE`: sandbox cannot reach gateway.
- `UPSTREAM_CONNECT_FAILED`: gateway cannot connect to upstream.
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
  egress gateway exists.
- Add fail-closed checks so K8s cannot silently run secret-backed Agents without
  egress management.
- Add tests that detect real provider keys in generated K8s Pod manifests.

### Phase 1: Shared Egress Policy Extraction

- Extract Docker's route construction into a provider-neutral module.
- Split `env` into public env and secret-derived egress policy.
- Preserve Docker behavior with parity tests.
- Add regression tests for Anthropic, OpenAI, Gemini, Azure, MCP, Git, and
  external services.

### Phase 2: K8s Gateway MVP

- Add `joysafeter-egress-gateway` deployment and service.
- Add production policy backend and restart recovery.
- Add `K8sEgressManager`.
- Generate per-sandbox policy and expose it to the gateway.
- Rewrite K8s sandbox env to placeholder endpoints.
- Add NetworkPolicy allowing sandbox to gateway and orchestrator only.
- Prove real model task completion through the gateway.

### Phase 3: Production Hardening

- Replace `kubectl` shell-out with a native Kubernetes client.
- Add gateway HA and policy recovery after restart.
- Add mTLS or short-lived token auth between sandbox and gateway.
- Add audit events and Prometheus metrics.
- Add resource limits and autoscaling for gateway.
- Add Cilium FQDN policy option for clusters that support it.

### Phase 4: Multi-Provider Enforcement

- Apply the same fail-closed contract to E2B and Daytona.
- Require provider capability declarations in tests.
- Add conformance tests every provider must pass.

## Validation Matrix

### Security

- K8s generated Pod spec does not contain real `ANTHROPIC_API_KEY`.
- `kubectl get pod -o yaml` does not reveal provider secrets.
- Sandbox direct curl to model host is denied.
- Sandbox curl to gateway is allowed.
- Gateway denies unallowlisted host.
- Gateway strips sandbox-supplied `authorization` / `x-api-key`.
- Gateway injects the platform credential only for allowed routes.

### Runtime

- Claude baseline task completes through gateway.
- OpenAI/Codex task completes through gateway.
- MCP remote credential route works without exposing token to sandbox.
- Git credential route works without exposing token to sandbox.
- Task cancel reaches a running sandbox.
- Orchestrator restart rebuilds egress policy.
- Gateway restart does not strand running sandboxes.

### Operations

- Long-run validation with repeated tasks.
- Concurrent sandbox creation under quota.
- Gateway latency and upstream status metrics are emitted.
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

1. Add production gateway HA policy backend or watch-based reconciler.
2. Add K8s lifecycle cleanup semantics for platform-owned
   per-sandbox NetworkPolicies and gateway policies.
3. Run long-cycle k3s validation with real secret-backed LLM tasks, then flip
   K8s `has_egress_management=true`.
4. Add gateway audit events, metrics, request timeout policy, and structured
   upstream error classification.
5. Replace `kubectl` shell-out with a native Kubernetes client.

These tasks deliberately start with tests and contracts before adding new
infrastructure. The objective is to prevent another one-off path from becoming
the default production behavior.
