# MCP Configuration and Credential Closure Design

Date: 2026-08-25
Status: Implemented

## Goal

Make every MCP configuration surface express one consistent lifecycle from Agent
declaration, through project-scoped credential storage and Session authorization,
to orchestrator resolution and runner projection.

## Canonical Mental Model

1. An Agent declares every MCP server it can use.
2. An MCP credential member stores authentication material for one normalized
   remote MCP URL and belongs to one project-scoped credential group.
3. A Session selects credential groups as the credentials eligible for that run.
4. The orchestrator matches eligible credentials to Agent-declared remote servers
   by the canonical normalized URL. Names and group names are not identity keys.
5. The runner receives connection configuration without secret headers. Envoy is
   the only boundary that receives and injects MCP HTTP authentication material.

A credential member without a corresponding Agent server does not create an MCP
connection. An Agent server that requires authentication is not runnable unless
the Session selects exactly one matching active credential.

## Authoritative Invariants

### Agent MCP declarations

- Remote transports use exactly `streamable_http` or `sse` with `name`, `url`,
  and explicit `auth_requirement`.
- Local processes use exactly `local_stdio` with `name`, `command`, `args`, and
  `env`; they never use credential groups.
- Server names are unique within an Agent because MCP tool policy references the
  server name.
- `streamable_http` supports `required`, `optional`, and `none`.
- Current runtime networking supports `sse` only without managed credential
  injection. Therefore new or updated `sse` declarations must use
  `auth_requirement: none`.
- Local stdio environment values are ordinary Agent configuration, not encrypted
  credential material. UI and documentation must warn users not to place secrets
  there.

### MCP credential members

- A member has one `mcp_server_url`, one supported `auth_scheme`, and encrypted
  scheme-specific material.
- The Rust credential storage adapter reveals only the fields required by the
  canonical scheme: `token_value` for `static_bearer`, an optional custom
  `header_name` for `header_api_key`, and the required `header_name` plus optional
  `value_prefix` for `custom_header`. Unrelated encrypted fields remain sealed.
- Envoy consumes the resolved header injection plan; it does not interpret
  credential schemas or select credential material.
- The canonical URL normalizer is shared by Python, Rust, frontend display logic,
  and test vectors.
- The database uniqueness boundary remains `(group_id,
  normalized_mcp_server_url)`: one active logical endpoint per group.

### Session authorization and matching

- `credential_group_ids` belong to the Session, not the Agent.
- Only Agent-declared remote URLs participate in Session coverage and ambiguity
  checks.
- For `required`, exactly one active selected member must match.
- For `optional`, zero or one active selected member may match.
- For `none`, matching members are ignored and never decrypted or injected.
- Duplicate credentials for URLs not declared by the Agent do not block the
  Session or runtime plan.
- Multiple selected credentials matching one `required` or `optional` Agent
  endpoint fail with `CREDENTIAL_GROUP_URL_CONFLICT`.
- A missing `required` credential fails Session creation with
  `SESSION_MCP_CREDENTIAL_REQUIRED`; the Rust runtime retains the same fail-closed
  check for state changes after Session creation.

### Credential group mutation

- Adding or restoring a member checks active Sessions already bound to that group.
- The mutation conflicts only when it would create multiple eligible credentials
  for an Agent endpoint used by one of those Sessions.
- Adding the first matching credential for a required endpoint is valid and makes
  that Session runnable after runtime-policy refresh.
- Unrelated duplicate URLs across groups are permitted until a Session selects the
  groups for an Agent that declares that URL.

## UI Contract

### Agent editor

- Label the section as connection configuration and state that secrets live in
  MCP credential groups selected per Session.
- Explain that URL is the credential matching key.
- Prevent `sse` from being saved with `required` or `optional`; selecting `sse`
  sets the requirement to `none` and displays the networking limitation.
- Keep MCP tool approval policy separate from credential requirement.

### Credential group member editor

- Explain that the server URL must match an Agent MCP URL after normalization.
- Keep authentication scheme fields focused on secret header construction.
- Do not imply that creating a credential creates or attaches an MCP server.

### Session creation

- Present credential groups as per-run authorization, not Agent attachment.
- Resolve selected group members through existing member APIs and show one status
  row per Agent remote MCP server: matched, optional anonymous, not required,
  missing required, or ambiguous.
- Block Session submission when a required endpoint is missing or an eligible
  endpoint has multiple matches.
- Matching uses the same frontend canonical URL helper as Quickstart.

### Quickstart

- A credentialed MCP flow creates both the Agent server declaration and the
  matching credential group member, then selects the group on Session creation.
- Capability evidence uses the canonical frontend normalizer.

## CLI and Manifest Contract

- Interactive Agent creation asks for `auth_requirement` for
  `streamable_http`.
- Interactive SSE creation emits `auth_requirement: none`.
- Manifest parsing rejects unsupported authentication values and rejects SSE with
  any requirement other than `none` before issuing an API request.

## Compatibility and Data

- Existing canonical URL normalization remains unchanged.
- Existing persisted SSE declarations with `required` or `optional` are invalid
  configurations that never had a supported credential-injection path. A
  migration/preflight must fail with actionable resource identification rather
  than silently downgrade them to anonymous access.
- No secret material is added to API responses, frontend state summaries, logs,
  gRPC, or runner configuration.

## Error Ownership

- Agent configuration errors are owned by the Agent application boundary.
- Session coverage and ambiguity errors are owned by credential/session binding.
- Concurrent lifecycle drift remains owned by the Rust runtime planner.
- Network-policy and Envoy publication failures remain owned by the orchestrator.

## Verification

- Python domain tests prove required/optional/none coverage and relevant-only
  duplicate detection.
- Repository/integration tests prove bound-session member mutations use the same
  relevance rule.
- Rust tests prove runtime parity and fail-closed behavior.
- Frontend unit/component tests prove canonical matching, SSE restrictions, and
  Session submission blocking.
- CLI tests prove interactive and manifest parity.
- Contract/live matrix tests declare credentialed servers on the Agent and bind
  the matching group to the Session.
