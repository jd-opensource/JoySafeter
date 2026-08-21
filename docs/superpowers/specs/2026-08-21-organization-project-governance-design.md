# Organization and Project Governance Design

## Goal

Make organization, project, membership, permission, default-project, and lifecycle behavior form one predictable model across persistence, APIs, navigation, and UI.

## Domain Model

- A user belongs to an organization through an organization membership.
- Organization roles are `owner`, `admin`, and `member`.
- A project belongs to exactly one organization.
- Ordinary organization members access non-default projects through explicit project memberships.
- Project roles are `admin`, `editor`, and `viewer`.
- Organization owners and administrators inherit Project Admin capability across the organization.
- Project creation provenance is stored separately from authorization. Being the creator never creates an irreversible authorization bypass.
- “Workspace” is not presented as a separate domain object. The UI uses “current organization” and “current project”.

## Project Creation Policy

Each organization has a `project_creation_policy`:

- `admins_only` — organization owners and administrators may create projects.
- `all_members` — every organization member may create projects.

The default is `admins_only`.

When an ordinary member creates a project under `all_members`, the member receives an explicit Project Admin grant. When an owner or organization administrator creates a project, no redundant explicit project grant is created because their organization role already grants Project Admin capability.

Every project stores nullable `created_by_user_id` for audit and display. Creator identity does not override current authorization.

## Default Project

Every organization has exactly one active default project.

The default project is:

- the preferred project when entering or switching to an organization;
- the project where ordinary organization members receive implicit Viewer access when they have no explicit project role.

The default project is not a special immutable project type. Its name may be changed by a Project Admin. Its slug may be changed by an organization owner or administrator.

The default project cannot be archived. Another active project must be made default first. Setting a new default changes the implicit Viewer target immediately and does not create or migrate `ProjectMember` rows.

Effective project capability is computed as follows:

1. Organization owner/admin: Project Admin.
2. Ordinary member with an explicit project role: that explicit role.
3. Ordinary member without an explicit role on the active default project: Viewer.
4. Otherwise: no access.

Explicit Editor or Admin grants on the default project override the implicit Viewer baseline.

## Role Transitions

- The owner role is created only with the organization or through the explicit ownership-transfer operation. Member-add and ordinary role-update APIs never assign `owner`.
- Promoting a member to organization owner/admin removes redundant direct project memberships.
- Demoting an owner/admin to member does not reactivate historical hidden grants; the member receives only implicit Default Viewer access unless new explicit grants are assigned.
- Reapplying the same effective organization role is idempotent and does not clear direct project memberships. Legacy role aliases may be normalized without changing project access.
- Removing a user from an organization removes all direct project memberships and invalidates project credentials whose creator no longer has access.
- Ownership transfer clears direct project memberships for both the previous and new owner so it does not create hidden project-specific privileges.
- A user cannot change or remove their own membership from member management. Leaving an organization is a distinct lifecycle operation and must handle active-context recovery explicitly.

## Capability Matrix

| Capability | Owner | Org Admin | Project Admin | Editor | Viewer |
| --- | --- | --- | --- | --- | --- |
| View organization | Yes | Yes | Yes | Yes | Yes |
| Edit organization | Yes | Yes | No | No | No |
| Manage organization members | Yes | Yes, except owner | No | No | No |
| Transfer/delete organization | Yes | No | No | No | No |
| Create project | Yes | Yes | Policy controlled | Policy controlled | Policy controlled |
| Rename project | Yes | Yes | Yes | No | No |
| Change project slug | Yes | Yes | No | No | No |
| Manage project access | Yes | Yes | Yes | No | No |
| Manage project access tokens | Yes | Yes | Yes | No | No |
| Pause/resume project triggers | Yes | Yes | Yes | No | No |
| Set default project | Yes | Yes | No | No | No |
| Archive/restore project | Yes | Yes | No | No | No |
| Edit project resources | Yes | Yes | Yes | Yes | No |
| Read project resources | Yes | Yes | Yes | Yes | Yes |

## API Boundaries

- Route-target project authorization is mandatory for every project-management endpoint.
- Project name changes require Project Admin.
- Project slug changes require organization Admin.
- Trigger pause/resume requires Project Admin.
- Default selection and archive/restore require organization Admin.
- Project access and project token management require Project Admin.
- Project access tokens use project-scoped routes instead of relying on the global active project.
- API responses expose explicit booleans or capabilities needed by the UI; frontend components do not infer project administration from organization role alone.

## Management Information Architecture

The sidebar retains only `Organizations` and `Projects` under Management.

Organization routes:

- `/managed/settings`
- `/managed/settings/organizations/{organizationId}`
- `/managed/settings/organizations/{organizationId}/members`

`/managed/settings` is the organization collection page only. It must not display organization-scoped tabs because it represents multiple organizations.

The organization detail shell always displays the target organization name, the viewer's organization role, current-context state, and a return link to the organization list. Its tabs are `Overview & Settings` and `Members & Roles`, and both preserve the explicit `organizationId` route parameter.

Organization list `Switch` changes the active working context. `Manage` or `View` opens the selected organization detail and never changes active organization or project context.

Member list, candidate search, add, role update, removal, and ownership transfer APIs receive the target organization ID in the route. They never infer the managed organization from the active project context. The legacy global member page and implicit `/auth/members` and `/auth/search-users` organization-member APIs are removed rather than redirected or retained as aliases.

Project routes remain under `/managed/projects/{projectId}` with Overview, Access, Access Tokens, and Lifecycle tabs.

Opening a management detail page never changes the global working organization or project. “Manage” and “Use/Switch” are separate explicit actions.

## List Interaction Rules

- Resource names are explicit links.
- Every row has a persistent primary action: `Manage` when actionable, otherwise `View`.
- Project rows separately expose `Use project` when the project is active and accessible.
- Organization rows separately expose `Switch to organization` when not current.
- Overflow menus contain only low-frequency secondary actions and are omitted when empty.
- Destructive actions are not performed directly from index pages.
- Lists display current-context state, default state, lifecycle state, and the viewer's effective role as separate concepts.
- Mobile layouts use stacked resource cards instead of requiring horizontal table discovery.
- Keyboard focus is visible and table semantics are not replaced with `role="button"` rows.

## Permission Feedback

- Readable pages remain visible when mutation permission is absent.
- Disabled controls include an adjacent reason or accessible tooltip.
- A `403` is represented as insufficient permission, not empty data.
- Saving and destructive actions expose pending, success, and failure states near the action.
- Slug changes and destructive lifecycle operations require impact-aware confirmation.
- Member-add copy must describe the implemented lifecycle accurately: the current API adds an existing registered account and does not send an invitation or create a pending invite.

## Migration Rules

- Add `Organization.project_creation_policy` with database default `admins_only`.
- Add nullable `Project.created_by_user_id`.
- Remove legacy default-project Viewer rows because default Viewer becomes implicit.
- Remove direct project memberships for current organization owners/admins because those grants are redundant and unsafe after demotion.
- Preserve explicit Editor/Admin grants for ordinary members.
- Existing projects with unknown creators retain `created_by_user_id = NULL`.
- Migration and role transitions emit or preserve sufficient audit evidence.

## Validation

- Backend tests cover creation policy, creator authority, route-target authorization, default switching, role promotion/demotion, and token management.
- Frontend tests cover visible list actions, non-mutating management navigation, permission reasons, responsive resource cards, and consistent destructive flows.
- Type checking, linting, formatting, backend focused tests, frontend focused tests, full frontend tests, and production build must pass.
- Rendered browser QA must verify organization and project management flows when a browser runtime is available.
