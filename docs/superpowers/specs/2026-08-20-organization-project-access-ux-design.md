# Organization and Project Access UX Design

## Problem

The product currently presents organization membership and project authorization as two kinds of “members.” This makes users ask whether a person is a member of the organization or of a project, and it hides important inheritance rules behind identical role names such as “Admin.”

The backend model is sound but the frontend language and navigation do not expose it consistently:

- A user belongs to an organization through an organization membership.
- An organization owns projects.
- Organization owners and administrators inherit administrator capability in every project.
- Ordinary organization members need an explicit project access grant.
- Every organization member must retain access to the default project.

## Accepted Information Architecture

Keep **Organization** as the top-level administrative and security boundary. Do not rename it to Workspace.

Use this user-facing model:

```text
Organization
├── Organization members and organization roles
└── Projects
    └── Project access and project permission levels
```

“Project member” is not a user-facing concept. Project-scoped records are presented as access grants for existing organization members.

## Terminology

### Organization scope

- Members page: **Organization Members** / **组织成员**
- Role column: **Organization Role** / **组织角色**
- Roles: Organization Owner, Organization Admin, Organization Member
- Invite action: Invite Organization Member
- Removal action: Remove from Organization

### Project scope

- Project page/action: **Project Access** / **项目访问权限**
- Permission column: **Project Permission** / **项目权限**
- Permission levels: Project Admin, Editor, Viewer
- Grant action: Grant Project Access
- Removal action: Revoke Project Access
- No row: Not Granted
- Owner/admin inheritance: Inherited from Organization — Project Admin

Internal API routes, database model names, audit event names, and source-code identifiers may retain `member` terminology where changing them would be a compatibility migration.

## Permission Presentation

The frontend must explain the effective rules directly:

1. Organization owners and administrators automatically administer every project.
2. Ordinary organization members receive project access explicitly.
3. Inviting an ordinary organization member grants Viewer access to the default project.
4. Access to the default project cannot be revoked independently; remove the user from the organization instead.

Organization-level and project-level roles must never share an unscoped “Admin” label in management views.

Organization invitation and role-edit controls must use only `owner/admin/member` vocabulary. The least-privilege default for a new invitation is `member`; legacy values such as `developer` and project-only values such as `viewer` must never be submitted as organization roles.

## Functional Consistency

Project list responses must include the caller's effective `capability` and explicit `project_role` for each project. This lets the frontend expose Project Access to an ordinary organization member who is a Project Admin, without exposing organization-only actions such as project creation, archival, or default-project selection.

The projects page must split action authorization:

- Organization owner/admin: create, edit, archive, restore, set default, pause triggers.
- Effective project admin: manage Project Access for that project.

The project access selector must fail closed to Viewer when an explicit backend role is absent or malformed. It must never display Editor as an implicit fallback because the backend defaults grants to Viewer.

## Validation

- Translation contract tests prevent ambiguous user-facing “Project Members” terminology from returning.
- Frontend unit tests cover effective project-access display and action authorization.
- Backend route tests verify per-project capability and role enrichment.
- Existing organization membership, project membership, context switching, and sidebar tests remain green.
