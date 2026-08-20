# Quickstart Capability Closure Design

## Objective

Make Quickstart a self-consistent desktop workflow that not only creates an Agent, Environment, MCP authorization, and Session, but also explains which capabilities the task needs, maps recommendations to real platform resources, preserves explicit user control, and proves what was actually used at runtime.

## Product Model

Keep the four user outcomes:

1. **Understand** — determine the goal, runtime, model connection, and capability requirements.
2. **Design** — review the professional Agent Blueprint and its Skill, Tool, and MCP capability plan.
3. **Protect** — review or configure the execution environment, network boundary, and external-tool authorization.
4. **Prove** — run an acceptance message and summarize observable capability and safety evidence.

The six internal resource steps remain unchanged. Resource creation is always explicit.

## Capability Contract

The generated Agent Blueprint gains a structured `capability_plan` containing:

- `skills`: specialized reusable behaviors, optionally bound to a real published Skill ID.
- `tools`: built-in execution abilities and their intended use.
- `mcp_servers`: external systems, their purpose, and optional server URL.

Each recommendation contains a name, purpose, and workflow timing. Availability is derived by the frontend from real catalog/configuration state; the model must not claim that an unavailable capability is ready.

The Quickstart request includes a bounded catalog of published, runtime-eligible Skills. The model may only attach Skill IDs from that catalog. The frontend filters generated Skill references against the same catalog before creation.

## User Interaction

- The Blueprint displays Capability Plan before lower-level behavioral sections.
- Recommended Skills that match real catalog entries can be selected or removed before Agent creation.
- Tools distinguish configured built-in tools from narrative recommendations.
- MCP recommendations clearly separate server configuration from credential authorization.
- Missing setup uses neutral `Needs setup` or `Not authorized` states, never success styling.
- Environment and MCP may be skipped, but the Protect outcome becomes `Reviewed with gaps`, not silently complete or permanently pending.

## Runtime Evidence

The Prove screen derives evidence only from observable state:

- Session response received.
- Controlled Environment attached, or no custom environment attached.
- MCP credential group attached, or external tools not authorized.
- Tool calls observed, including tool names when available.
- MCP calls observed, including server/tool names when available.
- Transcript and Debug events available for inspection.

The UI must not claim allowlist enforcement, credential injection, Skill execution, or policy compliance without corresponding runtime evidence.

## Architecture

- Extend the pure Blueprint normalizer for structured capability recommendations.
- Add a pure capability resolver that combines recommendations, real Skill catalog entries, actual Agent configuration, and runtime events.
- Extend the Quickstart backend request/tool schema with bounded available Skills and generated `skills`/`mcp_servers` fields.
- Keep UI rendering in focused components rather than expanding the main page further.
- Track skipped protection steps explicitly so outcome state remains truthful.

## Constraints

- Desktop web is the target surface.
- Do not add frontend dependencies.
- Do not modify unrelated credential-domain worktree changes.
- Agent, Environment, Credential Group, and Session creation remain explicitly confirmed.
- Existing legacy Blueprint payloads remain readable.
- All capability claims must be derived from real configuration or runtime events.

## Verification

- Unit tests for normalization, catalog filtering, outcome states, and evidence derivation.
- Component tests for Capability Plan and Capability Evidence.
- Backend contract tests for available Skill context and generated Agent schema.
- Existing Quickstart tests, type-check, focused formatting, and production build.
- Playwright at 1440×900 for Design, Protect with gaps, Secure Launch, and Prove evidence.
