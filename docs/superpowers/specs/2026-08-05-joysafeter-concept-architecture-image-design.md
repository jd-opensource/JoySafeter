# JoySafeter Concept Architecture Image Design

## Purpose

Create a polished concept image for general project presentation rather than a literal technical architecture diagram. The image should communicate that JoySafeter is a self-hosted platform for securely operating managed AI agents.

## Output

- Format: PNG
- Orientation: 16:9 landscape
- Intended location: `docs/assets/joysafeter-concept-architecture.png`
- Rendering method: image generation, not Mermaid or Graphviz

## Composition

Use a layered, isometric 3D composition:

1. Place the JoySafeter control platform at the center as the visual hub.
2. Surround it with several visibly isolated sandbox cells containing AI agents and security tools.
3. Show controlled connections from the platform to model providers, MCP/tool services, and authorized target systems.
4. Represent memory, event history, and audit storage as a stable data layer beneath the platform.
5. Use shields, guarded gateways, and constrained network paths to convey isolation and fail-closed security.

The visual hierarchy should read from platform, to sandboxed execution, to external capabilities and targets, with memory and auditability supporting the full system.

## Visual Direction

- Premium dark technology aesthetic
- Deep navy and blue-violet base palette
- Electric cyan connections with restrained orange security accents
- Clean, credible enterprise-security tone
- Cinematic depth without excessive visual clutter
- High contrast and generous spacing suitable for a README, website, or presentation

## Text Policy

Keep embedded text minimal because generated-image typography can be unreliable. The only required title is `JoySafeter`. Optional short labels are `Secure Agent Platform`, `Sandbox`, `Tools`, `Memory`, and `Audit`; omit any optional label that does not render cleanly.

## Constraints

- No people, mascots, logos from other companies, watermarks, or illegible pseudo-text
- No depiction of uncontrolled access, exposed credentials, or open network paths
- Do not imply a single model vendor or engine
- Do not present the image as an exact deployment topology
- Preserve a clear central focal point and readable system relationships at presentation size

## Acceptance Criteria

- The image is a valid landscape PNG.
- A viewer can recognize a central managed-agent platform, isolated execution environments, controlled tool/target access, and a memory/audit foundation.
- The result feels suitable for public project presentation and remains understandable without a legend.
- Required title text is legible; optional labels are either legible or absent.
