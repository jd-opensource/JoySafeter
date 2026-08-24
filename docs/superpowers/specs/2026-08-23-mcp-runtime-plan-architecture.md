# MCP Runtime Plan Architecture

**Date:** 2026-08-23

**Status:** Approved for implementation

**Supersedes:** `docs/superpowers/plans/2026-08-23-mcp-egress-module-systematic-design.md`

## Goal

Make MCP configuration, credential injection, network enforcement, runner delivery,
and live refresh one coherent fail-closed subsystem across the Python API, PostgreSQL,
the Rust orchestrator, Envoy, sandbox runner, and frontend.

## Current Failure Chain

The current implementation has no authoritative runtime representation of an MCP
server. The harness builder and sandbox resolver independently interpret the same
agent JSON:

- the harness builder decides which endpoint enters `.mcp.json`;
- the sandbox resolver independently decides which Envoy route and credential apply;
- effective networking is calculated separately from the global `envoy_enabled`
  switch used by the harness builder;
- credential records only support `static_bearer` end to end even though the storage
  shape can carry other schemes;
- the original MCP hostname is added to the ordinary allowlist, so a request can
  bypass the credential-injection placeholder route;
- route paths use the user-controlled display name;
- Envoy host rewrite drops a non-default upstream port;
- URL creation validates only the scheme, while activation does not revalidate the
  destination or pin vetted addresses;
- missing credentials silently become unauthenticated access;
- policy refresh can be reported before Envoy has ACKed the replacement policy.

These are manifestations of one ownership defect: the runtime MCP decision is split
across transport, orchestration, and infrastructure code.

## Authoritative Owner

The Rust orchestrator owns MCP runtime activation because it already owns scheduling,
sandbox lifecycle, credential material access, and Envoy policy construction.

The orchestrator must build one `ResolvedMcpRuntimePlan` per captured session runtime
generation. Every downstream representation is derived from that immutable plan:

- the runner-safe projection supplies `.mcp.json` and contains no remote secret or
  remote authority;
- the Envoy projection supplies upstream targets and secret headers and is never sent
  into the sandbox;
- the network fingerprint includes the plan revision and drives lifecycle decisions.

The Python API owns write-time schema validation and persistence. Envoy owns network
enforcement and secret injection. The runner owns harness-specific serialization only.

## Core Runtime Model

```rust
pub struct ResolvedMcpRuntimePlan {
    pub runtime_generation: i64,
    pub harness_revision: String,
    pub egress_revision: String,
    pub servers: Vec<ResolvedMcpServer>,
}

pub struct ResolvedMcpServer {
    pub server_id: String,
    pub display_name: String,
    pub transport: McpTransport,
    pub original_endpoint: Option<McpEndpoint>,
    pub sandbox_endpoint: Option<String>,
    pub local_command: Option<ResolvedLocalCommand>,
    pub auth_requirement: McpAuthRequirement,
    pub credential_id: Option<CredentialId>,
    pub injection: Option<McpHeaderInjection>,
    pub egress: Option<McpEgressTarget>,
}
```

### Transport

`McpTransport` has exactly three canonical values:

- `streamable_http`: remote HTTP MCP;
- `sse`: remote SSE MCP;
- `local_stdio`: local process launched inside the sandbox.

Remote transports require an HTTP(S) URL and prohibit `command`, `args`, and `env`.
`local_stdio` requires a non-blank command, prohibits URL and remote authentication,
and keeps command environment values in the ordinary agent configuration boundary.

### Authentication Requirement

Remote MCP configuration carries an explicit `auth_requirement`:

- `required`: exactly one active bound credential must match the normalized URL;
- `optional`: zero or one matching credential is accepted;
- `none`: no credential may be injected even if a matching group is bound.

New API writes default to `required`. The irreversible MCP contract migration rewrites
historical remote entries without the field to explicit `optional` before the strict
runtime is deployed. API, frontend, CLI, and orchestrator paths do not carry a legacy
read mode after the migration.

The runtime planner rejects duplicate active credentials for the same normalized URL,
unknown schemes, missing required credentials, and credentials selected for a server
declared as `none` only when the caller attempts an explicit credential binding to that
server. Merely binding a group containing unrelated members does not fail activation.

### Server Identity and Route Key

Display names remain the harness-visible names used by MCP tool references. They are
never interpolated into network paths or cluster names.

The runtime planner derives `server_id` as lowercase hexadecimal SHA-256 over a framed
tuple containing the agent id, canonical transport, normalized endpoint or local
command identity, and ordinal. The Envoy route key is the first 32 hexadecimal
characters. This yields a stable safe route without adding a database column or trusting
user input.

The sandbox endpoint is:

```text
http://mcp-egress.internal/r/<route-key>/
```

## Credential Scheme Contract

MCP credential schemes are a closed enum shared by API contracts and Rust runtime:

| Scheme | Required material | Injected header |
|---|---|---|
| `static_bearer` | `token_value` | `Authorization: Bearer <token>` |
| `header_api_key` | `token_value`, optional `header_name` | `<header_name or X-Api-Key>: <token>` |
| `custom_header` | `token_value`, `header_name`, optional `value_prefix` | `<header_name>: <value_prefix><token>` |

The Python repository stores the canonical scheme in the existing free-text
`credential_type` column. API responses expose it as `auth_scheme`. The cutover migration
rewrites active historical aliases once; disabled OAuth tombstones remain readable only
so they can stay archived or be deleted, and cannot be restored or activated.

Material validation is scheme-specific at creation and update. The Rust resolver reads
the same fields it audits. It decrypts only credentials selected by the runtime plan,
not every member of every bound group.

### Header Safety

Header names must be valid RFC token characters and may not contain whitespace,
control characters, colon, CR, or LF. The following names are always rejected,
case-insensitively:

- `host`, `content-length`, `transfer-encoding`, `connection`, `upgrade`, `te`,
  `trailer`, `keep-alive`;
- `proxy-authenticate`, `proxy-authorization`;
- any name beginning with `x-envoy-`.

`token_value` and `value_prefix` must not contain CR, LF, NUL, or other ASCII control
characters. Envoy removes all supported authentication header names before adding the
selected injection header.

## URL and SSRF Policy

Write-time validation and activation-time validation are both mandatory.

For remote MCP endpoints:

- only `http` and `https` are accepted;
- URL userinfo and fragments are rejected;
- host and port must parse successfully;
- the path and query are preserved exactly as endpoint identity;
- metadata, unspecified, multicast, link-local, and broadcast IP ranges are blocked;
- blocked metadata hostnames are rejected;
- activation resolves DNS and rejects the plan if any answer is prohibited;
- Envoy receives the vetted addresses for that generation instead of independently
  resolving an unchecked hostname.

Private and loopback destinations remain deployment-policy controlled because local MCP
servers are a supported use case. They are never implicitly allowed by the ordinary
domain allowlist: the MCP route is the only path to the selected destination.

## Effective Networking

One function resolves the effective network mode before the MCP plan is built:

```rust
pub enum EffectiveNetworkMode {
    Limited,
    Unrestricted,
    Disabled,
}
```

- `limited` requires an available Envoy manager and uses placeholder routes;
- `unrestricted` rejects remote MCP servers whose plan would inject credentials;
- `disabled` rejects every remote MCP server and permits `local_stdio` only.

The harness builder and sandbox resolver consume this resolved value. Neither reads the
global `envoy_enabled` switch independently after resolution.

Real MCP upstream hosts are excluded from the general allowlist. The only allowlisted
MCP hostname visible inside a limited sandbox is `mcp-egress.internal`.

## Endpoint and Envoy Semantics

Each remote MCP server gets a per-upstream cluster with a unique cluster name. Route
authority is canonical `host[:port]`; non-default ports are retained. TLS clusters use
the original hostname for SNI while connecting only to vetted addresses.

Path rewriting preserves the endpoint base path and query:

- sandbox `/r/<key>/` maps to the upstream base path;
- sandbox `/r/<key>/<suffix>` appends `<suffix>` to the normalized upstream base path;
- the original query remains present unless the MCP client supplies a replacement
  query, in which case activation rejects the ambiguous configuration rather than
  silently merging secrets or parameters.

MCP routes disable response buffering and have no route timeout so both streamable HTTP
and SSE remain streaming. Retry policy must not retry non-idempotent MCP requests;
connection retries are limited to safe connection establishment behavior.

## Lifecycle and Refresh

`runtime_config_generation` remains PostgreSQL's durable source of truth. The MCP plan
records the captured generation and produces two revisions:

- `harness_revision`: changes when server names, transport, local command, sandbox URL,
  or other runner-visible configuration changes;
- `egress_revision`: changes when endpoint, resolved addresses, authentication material,
  or injected-header policy changes.

Lifecycle behavior:

| Change | Required action |
|---|---|
| credential material or header metadata | push egress policy and wait for xDS ACK |
| remote endpoint, transport, server name, local command | recreate/setup sandbox |
| network mode | recreate/setup sandbox |
| archive/delete required credential | mark generation stale and block execution |
| restore/create matching credential | rebuild plan; ACK before ready |

A refresh command is successful only after the requested policy version is ACKed and
the database records `networking_status = ready`. NACK, timeout, orchestrator restart,
or persistence failure leaves the sandbox non-ready. Task claim/start already checks the
captured runtime generation and must additionally retain the networking-ready gate.

Secrets are never reused from an older plan after a failed refresh.

## Frontend Contract

Agent MCP editing exposes:

- transport: Streamable HTTP, SSE, or Local stdio;
- remote URL or local command fields according to transport;
- authentication requirement: Required, Optional, or None.

Credential member creation exposes:

- Bearer token;
- API key header, with optional header name defaulting to `X-Api-Key`;
- Custom header with required header name and optional value prefix.

Frontend validation is advisory. Backend validation remains authoritative and returns
stable semantic error codes.

## Compatibility

- stored `type: "url"` maps to `streamable_http`;
- missing `auth_requirement` maps to `optional` only for existing stored data;
- existing `static_bearer` rows are unchanged;
- disabled OAuth aliases remain rejected;
- current credential group and session binding APIs remain unchanged;
- no plaintext material is added to API responses, logs, fingerprints, or runner input.

## Failure Ownership

- API validation failures: HTTP 422 or the existing structured invalid-request response;
- credential mismatch or missing required auth: orchestrator activation failure;
- unsafe DNS/IP result: orchestrator activation failure before listener publication;
- Envoy NACK or ACK timeout: networking status remains non-ready and execution blocks;
- local command serialization failure: harness setup failure;
- unsupported transport or structurally corrupt persisted data: activation failure,
  never silent skip.

## Verification Matrix

The implementation is complete only when evidence covers:

- transports: streamable HTTP, SSE, local stdio;
- ports: 80, 443, 8765, 8443;
- endpoints: root path, nested path, trailing slash, query;
- auth: bearer, API key, custom header, required/optional/none;
- networking: limited, unrestricted, Envoy disabled;
- security: metadata IP, link-local, multicast, userinfo, CRLF, reserved headers,
  DNS answer rejection, direct-host bypass;
- lifecycle: create, update, rotation, archive, restore, delete, generation race,
  xDS ACK, xDS NACK, ACK timeout;
- integration: PostgreSQL persistence, API/frontend contract, `.mcp.json`, Envoy route,
  live upstream request, streaming behavior.

## Rollback

The cutover is intentionally irreversible. Deployment order is migration first, followed
by API, orchestrator, runner, and frontend as one coordinated release. Rollback requires
restoring a pre-cutover database backup together with the prior binaries; the migration
does not synthesize legacy transport or authentication fields.
