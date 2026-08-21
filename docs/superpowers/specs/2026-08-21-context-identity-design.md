# Organization And Project Context Identity Design

## Goal

Make every organization and project recognizable before a user switches context, while removing the legacy behavior that creates indistinguishable `Default / Default` identities.

## Naming Contract

- `is_default` is lifecycle state, never a display-name convention.
- A bootstrap organization uses the user's non-empty profile name as its initial name.
- If the profile name is empty or is the legacy generic word `default`, the email local part is used.
- A newly provisioned default project is named `Main` and uses slug `main`.
- User-created organizations continue to accept an explicit organization name and receive a `Main` default project.
- Names are not required to be globally unique; the UI supplies ownership and role context for disambiguation.

## Ownership Contract

- Organization APIs expose the current owner's name and email to organization members.
- The viewer's membership role remains separate from owner identity.
- The UI labels owner memberships as “Owned by you” and other memberships by their role.
- Shared organizations include owner identity as secondary text.

## Context Switcher Contract

- The closed switcher presents organization and project on separate lines.
- Organization names are not manually truncated to four characters.
- Organization avatar colors are derived from organization ID, not list position.
- The open switcher groups organizations into owned and shared sections.
- Every organization row includes role/ownership and owner identity where needed.
- Every project row includes default and current state independently from its name.
- Search matches organization name, slug, owner name, owner email, project name, and project slug.

## Historical Cleanup

- Legacy bootstrap organizations are identified by the exact pair `name = 'Default'` and `slug = 'default'`.
- Those organization names are replaced with their owner's profile name, falling back to the email local part and then `Personal`.
- Their slug is replaced by a stable `workspace-<id-prefix>` value.
- Legacy default projects identified by `is_default = true`, `name = 'Default'`, and `slug = 'default'` become `Main/main`.
- Downgrade does not restore ambiguous names because doing so would destroy user-facing identity improvements.

## Non-Goals

- Introducing a separate Workspace domain entity.
- Requiring globally unique organization or project display names.
- Persisting a cross-device last-used project in this change.
- Changing organization or project permission semantics.
