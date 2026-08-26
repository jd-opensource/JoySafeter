# MCP Egress Endpoint Routing Design

**Date:** 2026-08-25

**Status:** Implemented

**Builds on:** `docs/superpowers/specs/2026-08-23-mcp-runtime-plan-architecture.md`

## Goal

Make remote MCP routing preserve the configured endpoint exactly, prevent unsafe
or accidental retries, expose unsupported transport combinations honestly, and
verify the complete runtime-plan-to-harness-to-Envoy path with executable tests.

## Problem Statement

An agent configured with:

```text
http://host.docker.internal:3404/mcp
```

receives this limited-networking projection:

```text
http://mcp-egress.internal/r/<route-key>/
```

The runtime planner currently changes the upstream path from `/mcp` to `/mcp/`.
FastMCP redirects `/mcp/` back to `/mcp`. Its client follows redirects, so the
next request targets the real upstream authority. Envoy correctly rejects that
authority because only the placeholder MCP route is allowlisted.

The observed request chain is:

```text
POST http://mcp-egress.internal/r/<route-key>/
  -> Envoy rewrites to http://host.docker.internal:3404/mcp/
  -> upstream returns 307 Location: http://host.docker.internal:3404/mcp
  -> client follows through the proxy
  -> Envoy returns 403 Host not in allowlist
```

This is not a DNS, socket, xDS ACK, or upstream availability failure. The host
endpoint returns a valid MCP initialize response, the per-sandbox Unix socket is
present, the runner proxy is listening, the policy is ready, and the configured
opaque route reaches the intended upstream.

## Root Causes

### Endpoint identity and request routing are conflated

`mcp_url::normalize` and the equivalent Python helper intentionally treat
`/mcp` and `/mcp/` as the same credential lookup identity. The runtime planner
then reuses that normalization concept when deriving route identity and target
paths. Credential lookup equivalence must not determine the HTTP request target.

### Remote MCP endpoints are modeled as prefixes

`McpEndpoint.upstream_prefix` converts every non-root endpoint into a directory-
style prefix. A Streamable HTTP MCP URL is an exact endpoint used for GET, POST,
and DELETE; it is not an arbitrary subtree.

### The generic egress route permits invalid combinations

`EgressCredentialRoute` represents path behavior through the combination of
`match_prefix`, `exact_path`, `exposure`, and `upstream_prefix`. Some combinations
have unclear semantics. In particular, an exact placeholder route currently
rewrites the Host but does not rewrite the path.

### MCP requests inherit unsafe generic retries

Every egress route currently retries `5xx`, reset, and connection failure twice.
MCP requests are commonly POST requests and may execute tools. Transparent retry
can therefore duplicate a non-idempotent operation.

### Verification does not exercise the production composition

The live Envoy test constructs route objects manually instead of generating them
from `ResolvedMcpRuntimePlan`. Its fixture accepts prefix-style paths, so it does
not detect mutation of `/mcp` into `/mcp/`. The higher-level live suite converts
runtime task failures into skips after execution has started, allowing a broken
MCP path to appear non-failing.

## Ownership

- The Python API owns schema validation and durable storage of the user-entered
  endpoint.
- The Rust orchestrator owns parsing the endpoint, selecting credentials,
  resolving and pinning addresses, and compiling the runtime routing policy.
- Envoy owns network enforcement, upstream authority/TLS selection, and secret
  header injection.
- The sandbox runner owns harness-specific serialization and proxy environment
  setup. It must not reinterpret endpoint paths.
- The harness owns MCP protocol behavior but must only receive sandbox-safe URLs.

## Endpoint Model

The runtime model must separate credential lookup identity from request routing:

```rust
pub struct McpEndpoint {
    pub configured_url: String,
    pub credential_match_key: String,
    pub routing_identity: String,
    pub host: String,
    pub port: u16,
    pub path: String,
    pub query: Option<String>,
    pub tls: bool,
    pub vetted_addresses: Vec<IpAddr>,
}
```

### `configured_url`

The trimmed user value retained for diagnostics and unrestricted-mode delivery.

### `credential_match_key`

The existing cross-language normalized value used only for credential lookup and
current database uniqueness behavior. Keeping it separate avoids an unrelated
credential migration in this repair.

The slash-insensitive credential identity remains a documented compatibility
constraint. A future credential-schema revision may make path identity exact,
but that is not required to repair transport routing.

### `routing_identity`

A canonical URL used for route identity and revision calculation. It normalizes
scheme and host casing and removes default ports, but preserves the path, trailing
slash, query ordering, and duplicate query parameters.

Changing `/mcp` to `/mcp/` must change `routing_identity` and the egress revision.

### `path` and `query`

These are parsed directly from the configured URL and preserved exactly. Empty
HTTP paths are represented as `/`, matching the request-target sent on the wire.

## Egress Route Model

Replace the ambiguous boolean/prefix combination with explicit path behavior:

```rust
pub enum EgressPathMapping {
    Passthrough {
        matcher: EgressPathMatcher,
    },
    RewriteExact {
        exposed_path: String,
        upstream_path: String,
    },
    RewritePrefix {
        exposed_prefix: String,
        upstream_prefix: String,
    },
}

pub enum EgressPathMatcher {
    Any,
    Exact(String),
    Prefix(String),
}

pub enum EgressRetryMode {
    Disabled,
    SafeIdempotent,
}
```

The Envoy JSON and protobuf renderers must consume these enums identically. An
invalid state such as “exact match without required placeholder rewrite” becomes
unrepresentable.

The pinned `envoy-types` protobuf version represents the exact replacement with
`prefix_rewrite` on an exact `path` match. Because the matcher admits only the
single exposed path, the complete matched path is replaced and descendants are
not authorized; JSON and protobuf renderers use the same representation.

Existing LLM, Git, and external-service routes retain their current behavior by
mapping explicitly to the appropriate enum variants.

## Streamable HTTP Contract

The runner-facing URL remains opaque and stable:

```text
http://mcp-egress.internal/r/<route-key>/[?<configured-query>]
```

The generated route is exact:

```text
match:    /r/<route-key>/
rewrite:  <configured-path-exactly>
```

For the reported configuration, the mapping is:

```text
/r/<route-key>/ -> /mcp
```

GET, POST, and DELETE use the same exact path. Query parameters remain attached
to the request and are not merged or reordered by the route compiler.

No descendant prefix route is created for Streamable HTTP. Requests such as
`/r/<route-key>/admin` fail closed instead of receiving the MCP credential.

## Redirect Policy

The system must not broaden the network allowlist to make redirects work.

- Correctly configured canonical endpoints should not redirect because the
  configured path is preserved exactly.
- A remaining upstream redirect to the real authority continues to fail closed.
- Envoy access logs must retain the upstream status and route identity.
- The task-facing error should identify an upstream redirect and recommend the
  canonical endpoint without exposing credential material.
- Automatic cross-origin redirect support is out of scope for this change.

A future protocol-aware gateway may safely translate same-origin redirects back
to opaque URLs, but adding that component is not justified for Streamable HTTP
correctness.

## Retry Policy

MCP routes use `EgressRetryMode::Disabled`.

The network layer must not retry MCP POST requests because it cannot know whether
the upstream executed the JSON-RPC operation before a reset or 5xx response.
Stream reconnection and protocol-level recovery remain the MCP client's
responsibility.

Existing retry behavior for LLM, Git, and external-service routes remains
unchanged in this scope.

## Legacy SSE Policy

Standard SSE MCP servers send an `endpoint` event containing a message path such
as `/messages/?session_id=...`. The client resolves that path against the
sandbox-visible origin. The current shared-host/path-key design loses the route
key, so generic Envoy prefix rewriting cannot implement the protocol correctly.

For this change:

- `sse` remains valid in unrestricted networking, where the harness uses the
  configured URL directly.
- `sse` is rejected during limited-networking activation with a stable,
  actionable error code.
- Existing persisted configurations are not rewritten silently; attempts to
  activate them fail closed and explain the required migration to
  `streamable_http` or unrestricted networking.

If limited-networking SSE becomes a product requirement, it requires a separate
approved design for either:

1. a trusted MCP-aware gateway that rewrites the SSE endpoint event and enforces
   the announced message endpoint; or
2. per-server opaque authorities with an explicitly accepted origin-wide
   credential scope.

The gateway is not introduced by this repair because it adds protocol state,
stream lifecycle, HA, backpressure, and observability responsibilities that the
current incident does not require.

## Runtime Revision and Lifecycle

- `harness_revision` continues to cover runner-visible server configuration.
- `egress_revision` includes `routing_identity`, vetted addresses, route mapping,
  retry mode, and credential injection metadata.
- A path-only change therefore republishes policy and waits for Envoy ACK.
- The sandbox must not execute while the target generation is stale, pending,
  NACKed, or timed out.
- Existing sandbox reuse remains allowed only after runtime and networking
  generation checks pass.

## Failure Contract

Add stable failures at the owning boundary:

- `MCP_SSE_UNSUPPORTED_WITH_LIMITED_NETWORKING`
- `MCP_ENDPOINT_REDIRECT_BLOCKED`
- `MCP_EGRESS_ROUTE_NOT_READY`
- `MCP_EGRESS_UPSTREAM_UNREACHABLE`

Transport-level failures should retain the server display name, transport,
sandbox ID, route key, and status code where available. They must not include
credential values.

## Verification

### Unit tests

- `/mcp` remains `/mcp`.
- `/mcp/` remains `/mcp/`.
- `/` remains `/`.
- Query ordering and duplicate query values are preserved.
- Credential matching continues using the compatibility key.
- Routing identity distinguishes `/mcp` from `/mcp/`.
- MCP routes disable retries.
- Limited-networking SSE fails with the documented error.

### Envoy rendering tests

- JSON and protobuf renderers produce identical exact-path rewrites.
- The placeholder Host rewrites to the real authority, including non-default
  ports.
- Exact-path routes do not authorize descendant paths.
- Proxy authorization remains mandatory.

### Live Envoy regression

Build the Envoy policy from a real `ResolvedMcpRuntimePlan`, not handcrafted
routes. Run a FastMCP server whose endpoint is `/mcp` and verify:

1. initialize returns 200 without a redirect;
2. tools/list succeeds;
3. tools/call succeeds exactly once;
4. session DELETE reaches `/mcp`;
5. direct requests to the real host remain denied;
6. injected credentials replace attacker-supplied headers.

### End-to-end harness tests

Run the same Streamable HTTP MCP server through Claude, Codex, and native where
those adapters support MCP. Once a live task has been accepted, connection or
tool-call failure is a test failure, not a skip. Skips are permitted only before
execution when an explicit external prerequisite is absent.

## Rollout

1. Add failing runtime-plan and Envoy rendering tests.
2. Introduce the separated endpoint and typed route models.
3. Change Streamable HTTP compilation to exact-path rewriting with retries off.
4. Reject limited-networking SSE at activation.
5. Add the runtime-plan-driven live Envoy regression.
6. Correct L3 skip behavior and run one real harness validation.
7. Rebuild and restart the orchestrator and sandbox images.
8. Recreate or refresh affected sandboxes and verify xDS ACK before execution.

No database schema migration is required for this repair because the existing
credential match key remains intact. No new service is introduced.

## Non-Goals

- Allowlisting the real MCP host inside limited sandboxes.
- Automatically following arbitrary upstream redirects.
- Implementing OAuth flows for MCP.
- Adding a protocol-aware MCP gateway without a confirmed limited-SSE product
  requirement.
- Refactoring unrelated LLM, Git, or external-service behavior.

## Decision

The preferred solution is to repair endpoint semantics inside the existing Rust
orchestrator and Envoy boundary, disable unsafe generic retries for MCP, and fail
closed for legacy SSE in limited networking. A protocol-aware gateway remains a
separate future capability rather than part of this bug fix.
