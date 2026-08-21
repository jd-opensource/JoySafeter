# Management Information Architecture and Interaction Design

## Goal

Make organization and project administration understandable without requiring users to learn the internal authorization model first. Navigation identifies the object being managed; object-specific actions live inside that object's detail experience.

## Navigation

The sidebar Management section contains only two stable entries:

```text
Management
├── Organizations
└── Projects
```

Organization Members and Project Access Tokens are removed from the sidebar. Existing routes remain available for compatibility, but the primary navigation moves them into the correct object scope.

The organization/project switcher remains the place for changing active scope. It also exposes an explicit Manage Organizations action.

## Organization Management

`/managed/settings` becomes the organization management surface with route-driven tabs:

- Organizations
- Members & Roles

The existing organization list remains available under Organizations. The existing organization-member experience is presented under Members & Roles. Role changes and removals continue to show their organization/project impact explicitly.

## Project Management

`/managed/projects` is a searchable project index. The whole row is keyboard- and pointer-actionable and opens `/managed/projects/{projectId}`. The list is not the primary editing surface.

Project creation asks for a name. The slug is generated automatically and may be edited later in Project Overview.

The row overflow menu contains only lifecycle shortcuts that remain meaningful without opening the detail surface, primarily Archive or Restore. Editing, access, tokens, trigger pausing, and default-project selection move into project settings.

## Project Settings

Every project detail route is wrapped in a scope-aware project settings shell. The shell switches the active managed context to the route project before rendering children and continuously displays:

- Organization name
- Project name
- Effective project permission
- Archived/default state

Tabs:

```text
Project Settings
├── Overview
├── Access
├── Access Tokens
└── Lifecycle
```

Routes:

- `/managed/projects/{projectId}`
- `/managed/projects/{projectId}/access`
- `/managed/projects/{projectId}/tokens`
- `/managed/projects/{projectId}/lifecycle`

The legacy `/managed/projects/{projectId}/members` route redirects to Access.

## Interaction Rules

### Overview

- Show identity, slug, default/archive state, and caller capability.
- Edit name and slug with an explicit Save action.
- Show pending state and preserve the form on failure.

### Access

- Organization owners/admins display locked inherited Project Admin permission.
- Ordinary organization members use an inline permission selector.
- A changed row displays Saving, then Saved feedback.
- Revocation requires confirmation.
- Default-project revocation is visibly unavailable with an inline reason.
- Empty state directs the user to Members & Roles.

### Access Tokens

- The project settings shell provides persistent project context.
- Newly created raw tokens remain visible until the user confirms they have saved them.
- Copy provides immediate success feedback.
- Revoke confirmation includes the token name.

### Lifecycle

- Set Default and Pause/Resume Triggers are separated from destructive actions.
- Archive impact is explained before confirmation.
- Archive confirmation requires typing the project name.
- Restore is available for archived projects.

## Authorization Consistency

Project-access endpoints must authorize against the project identified in the route, not merely the currently active project in request context. An ordinary Project Admin for project A must not manage access for project B.

Organization owner/admin retains inherited Project Admin capability for every project. Ordinary organization members require an explicit `ProjectMember` role for the target project.

## Compatibility

- Database tables, audit event names, and API paths retain existing internal `member` terminology.
- `/managed/members` and `/managed/api-keys` remain functional but are no longer primary navigation destinations.
- `/managed/projects/{projectId}/members` redirects to `/access`.

## Validation

- Backend tests cover target-project authorization.
- Sidebar tests cover the simplified Management section and organization-manager link.
- Project settings shell tests cover context switching and route tabs.
- Project list tests cover row navigation and reduced action menus.
- Access helper/component tests cover pending/saved/default-project behavior.
- Frontend type-check, lint, production build, and relevant existing tests pass.

