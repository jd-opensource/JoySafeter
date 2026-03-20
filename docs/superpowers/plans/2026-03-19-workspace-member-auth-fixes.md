# Workspace Member Authorization System Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical bugs, security holes, and inconsistencies in the workspace member authorization system so that "1 workspace = 1 team" with creator-managed membership is fully self-consistent end-to-end.

**Architecture:** Fixes are organized into 4 phases — (P1) Backend critical route/security fixes, (P2) Backend service-layer logic fixes, (P3) Frontend bug fixes, (P4) Resource access control gaps. Each phase is independently testable and committable.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), TypeScript/Next.js/React Query (frontend)

---

## Phase 1: Backend Critical Route & Security Fixes

### Task 1: Fix route ordering — invitation routes shadowed by `/{workspace_id}`

All `GET /invitations*` routes are declared AFTER `GET /{workspace_id}`, so FastAPI matches "invitations" as a `workspace_id` UUID and returns 422. Move all invitation routes before the dynamic `/{workspace_id}` route.

Note: `/members/{user_id}` routes (PATCH/DELETE) are NOT affected by this shadowing issue — they have a different prefix segment ("members") and don't collide with `/{workspace_id}`. Only invitation routes need to be moved.

**Files:**
- Modify: `backend/app/api/v1/workspaces.py`

- [ ] **Step 1: Move all `/invitations*` routes before `/{workspace_id}`**

Move the following route blocks (currently at lines 166-263) to appear BEFORE `@router.get("/{workspace_id}")` (currently at line 89):

```python
# --- Static invitation routes (MUST be before /{workspace_id}) ---

@router.get("/invitations")
async def list_invitations(...):
    ...

@router.get("/invitations/pending")
async def list_pending_invitations(...):
    ...

@router.get("/invitations/all")
async def list_all_invitations(...):
    ...

@router.post("/invitations")
async def create_invitation(...):
    ...

@router.get("/invitations/{token}")
async def get_invitation_by_token(...):
    ...

@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(...):
    ...

@router.post("/invitations/{invitation_id}/reject")
async def reject_invitation(...):
    ...

@router.post("/invitations/token/{token}/accept")
async def accept_invitation_by_token(...):
    ...

# --- Dynamic workspace routes (AFTER all static paths) ---

@router.get("/{workspace_id}")
async def get_workspace(...):
    ...
```

The final order in the file should be:
1. `GET /` (list workspaces)
2. `POST /` (create workspace)
3. All `/invitations*` routes (GET, POST, accept, reject, token-accept)
4. `GET /{workspace_id}` and other `/{workspace_id}/*` routes
5. `/members/{user_id}` routes (can stay at end — not shadowed)

- [ ] **Step 2: Verify by starting the server and testing**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.api.v1.workspaces import router; print([r.path for r in router.routes])"`
Expected: `/invitations` appears before `/{workspace_id}` in the route list.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/workspaces.py
git commit -m "fix: reorder workspace routes to prevent invitation paths being shadowed by /{workspace_id}"
```

---

### Task 2: Delete unused `require_roles()` — dead code with broken logic

`require_roles(*roles)` accepts roles but never checks them — any authenticated user passes. Confirmed via grep: this function is NOT called anywhere in the backend. It is only defined in `dependencies.py`. Delete it.

**Files:**
- Modify: `backend/app/common/dependencies.py:138-146`

- [ ] **Step 1: Delete the `require_roles` function (lines 138-146)**

Remove the entire function:

```python
# DELETE THIS ENTIRE BLOCK:
def require_roles(*roles: str):
    """角色权限检查装饰器"""

    async def check_roles(current_user: User = Depends(get_current_user)):
        if current_user.is_superuser:
            return current_user
        return current_user

    return Depends(check_roles)
```

- [ ] **Step 2: Verify no import breakage**

```bash
cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter && grep -rn "require_roles" backend/
```

Expected: Only appears in the import line of the file being edited (if any), and the definition itself. After deletion, zero matches.

- [ ] **Step 3: Commit**

```bash
git add backend/app/common/dependencies.py
git commit -m "fix: remove unused require_roles function that silently bypassed role checks"
```

---

### Task 3: Protect owner from being removed via `remove_member`

An admin can currently remove the workspace owner from `workspace_members`. Add a guard identical to what exists in `update_member_role`.

**Files:**
- Modify: `backend/app/services/workspace_service.py:921-960`

- [ ] **Step 1: Add owner removal guard**

Add after the `NotFoundException` guard (after `if not target_member: raise NotFoundException(...)` at line 941), before `current_role` is fetched:

```python
# 不能移除工作空间拥有者
if str(workspace.owner_id) == str(target_user_id):
    raise BadRequestException("Cannot remove workspace owner")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workspace_service.py
git commit -m "fix: prevent workspace owner from being removed via remove_member"
```

---

## Phase 2: Backend Service Logic Fixes

### Task 4: Fix repository `update_status` double-commit breaking transaction atomicity

`WorkspaceInvitationRepository.update_status()` calls `self.db.commit()` directly, but its callers (`accept_invitation`, `reject_invitation`) also call `self.commit()`. This breaks atomicity — the invitation status update and member creation happen in separate transactions.

**Files:**
- Modify: `backend/app/repositories/workspace.py:136-144`

- [ ] **Step 1: Replace `commit()` with `flush()` in `update_status`**

```python
async def update_status(self, invitation_id: uuid.UUID, status: WorkspaceInvitationStatus) -> WorkspaceInvitation:
    """更新邀请状态"""
    invitation = await self.get(invitation_id)
    if not invitation:
        raise NotFoundException("Invitation not found")
    invitation.status = status
    await self.db.flush()  # flush, not commit — let the service layer control the transaction
    await self.db.refresh(invitation)
    return invitation
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories/workspace.py
git commit -m "fix: use flush instead of commit in invitation update_status to preserve transaction atomicity"
```

---

### Task 5: Fix `accept_invitation` — mutates state then raises error for existing members

**Dependency: Task 4 must be completed first** (Task 4 changes `update_status` from `commit()` to `flush()`, which this task relies on for correct transaction behavior).

When a user is already a member, the code marks the invitation as `accepted` and THEN raises a 400 error. The invitation is permanently consumed for no reason. Fix: return success instead (idempotent behavior). Note: `accept_invitation_by_token` (line 673-678) calls this method internally, so it also gets the fix.

**Files:**
- Modify: `backend/app/services/workspace_service.py:620-626`

- [ ] **Step 1: Return success instead of raising error when already a member**

Replace lines 620-626:

```python
# 检查用户是否已经是成员
existing_member = await self.member_repo.get_member(invitation.workspace_id, current_user.id)
if existing_member:
    # 用户已是成员 — 标记邀请为已接受并返回成功（幂等操作）
    await self.invitation_repo.update_status(invitation.id, WorkspaceInvitationStatus.accepted)
    await self.commit()
    workspace = await self.workspace_repo.get(invitation.workspace_id)
    return {
        "success": True,
        "workspace": await self._serialize_workspace(workspace, current_user),
        "message": "You are already a member of this workspace",
    }
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/workspace_service.py
git commit -m "fix: accept_invitation returns success for existing members instead of error"
```

---

### Task 6: Add duplicate invitation check in `create_invitation`

`find_pending()` repository method exists but is never called. An admin can spam unlimited invitations to the same email.

**Files:**
- Modify: `backend/app/services/workspace_service.py:269-310`

- [ ] **Step 1: Add duplicate check after existing-member check (around line 295)**

Insert after the existing-member check block:

```python
# 检查是否已有未过期的待处理邀请
existing_pending = await self.invitation_repo.find_pending(workspace_id, email.lower())
if existing_pending:
    if existing_pending.expires_at and existing_pending.expires_at > datetime.now(timezone.utc):
        raise BadRequestException(
            f"A pending invitation already exists for {email}. 该用户已有待处理的邀请"
        )
```

- [ ] **Step 2: Normalize email to lowercase before storing**

Change line 302 from `"email": email,` to `"email": email.lower(),`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workspace_service.py
git commit -m "fix: prevent duplicate invitations and normalize email to lowercase"
```

---

### Task 7: Remove dead code — `datetime.utcnow()` call and deprecated method

**Files:**
- Modify: `backend/app/services/workspace_service.py`

- [ ] **Step 1: Verify no callers of deprecated method exist**

```bash
cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter && grep -rn "list_all_invitations_for_user[^_]" backend/
```

Expected: Only the method definition itself appears. If any route or service calls it, do NOT delete — update the caller to use the paginated version first.

- [ ] **Step 2: Remove orphaned `datetime.utcnow()` call at line 134**

Delete the line `datetime.utcnow()` in `create_workspace`.

- [ ] **Step 3: Remove deprecated `list_all_invitations_for_user` method (lines 439-478)**

Delete the entire method that is marked `已废弃，使用分页版本`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workspace_service.py
git commit -m "chore: remove dead code (orphaned datetime call, deprecated invitation list method)"
```

---

### Task 8: Delete unused `_ensure_workspace_role` in environment.py

The local helper in `environment.py` (lines 34-46) doesn't handle superusers or owners not in the members table. However, **the function is never called** — the actual workspace routes in this file already use `require_workspace_role` from `dependencies.py` as a FastAPI dependency. Simply delete the dead code.

**Files:**
- Modify: `backend/app/api/v1/environment.py:34-46`

- [ ] **Step 1: Delete the `_ensure_workspace_role` function and its unused import**

Delete lines 34-46 (the entire function). Also remove the unused import of `WorkspaceMemberRepository` at line 24 if it's no longer used elsewhere in the file.

- [ ] **Step 2: Verify no callers remain**

```bash
grep -n "_ensure_workspace_role" backend/app/api/v1/environment.py
```

Expected: Zero matches after deletion.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/environment.py
git commit -m "fix: environment workspace role check now handles superuser and owner-not-in-members"
```

---

## Phase 3: Frontend Bug Fixes

### Task 9: Fix invitation accept page — wrong `/auth/signin` redirect

The actual signin route is `/signin` (Next.js route group `(auth)/signin`), not `/auth/signin`.

**Files:**
- Modify: `frontend/app/workspace/invitations/accept/page.tsx:94,119`

- [ ] **Step 1: Replace `/auth/signin` with `/signin`**

Line 94:
```typescript
router.push(`/signin?callbackUrl=${encodeURIComponent(`/workspace/invitations/accept?token=${token}`)}`)
```

Line 119:
```typescript
router.push(`/signin?callbackUrl=${encodeURIComponent(`/workspace/invitations/accept?token=${token}`)}`)
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/workspace/invitations/accept/page.tsx
git commit -m "fix: correct signin redirect path in invitation accept page (/signin not /auth/signin)"
```

---

### Task 10: Fix `acceptInvitation` in workspaceService — token vs ID inconsistency

The accept page uses `token` but calls `acceptInvitation(token)` which hits `/invitations/{token}/accept`. The backend has TWO accept endpoints: `/invitations/{invitation_id}/accept` (by ID) and `/invitations/token/{token}/accept` (by token). The frontend service should use the token-specific endpoint when passing a token.

**Files:**
- Modify: `frontend/services/workspaceService.ts:215-219`

- [ ] **Step 1: Add separate methods for accept-by-ID and accept-by-token**

```typescript
/**
 * Accept invitation by ID (for notification banner)
 */
async acceptInvitationById(invitationId: string): Promise<AcceptInvitationResponse> {
  return apiPost<AcceptInvitationResponse>(
    `${API_ENDPOINTS.workspaces}/invitations/${invitationId}/accept`
  )
},

/**
 * Accept invitation by token (for email link)
 */
async acceptInvitationByToken(token: string): Promise<AcceptInvitationResponse> {
  return apiPost<AcceptInvitationResponse>(
    `${API_ENDPOINTS.workspaces}/invitations/token/${token}/accept`
  )
},
```

Keep the old `acceptInvitation` as an alias for `acceptInvitationById` for backward compat:

```typescript
async acceptInvitation(invitationId: string): Promise<AcceptInvitationResponse> {
  return this.acceptInvitationById(invitationId)
},
```

- [ ] **Step 2: Update the accept page to use `acceptInvitationByToken`**

In `frontend/app/workspace/invitations/accept/page.tsx`, change the mutation:

```typescript
mutationFn: async () => {
  if (!token) throw new Error('Token is required')
  return workspaceService.acceptInvitationByToken(token)
},
```

- [ ] **Step 3: Verify notification banner uses `acceptInvitationById` with `invitation.id`**

Search for `acceptInvitation` calls in notification components and ensure they pass `invitation.id` and call `acceptInvitationById` (or the existing `acceptInvitation` alias).

- [ ] **Step 4: Commit**

```bash
git add frontend/services/workspaceService.ts frontend/app/workspace/invitations/accept/page.tsx
git commit -m "fix: distinguish acceptInvitationById vs acceptInvitationByToken to fix token/ID mismatch"
```

---

### Task 11: Fix workspace switcher menu — hide admin-only items from non-admin users

The workspace context menu in the header shows "Members Management" and "API Keys" to all roles, including viewers.

**Files:**
- Modify: `frontend/components/sidebar/components/workspace-header/workspace-header.tsx`

**Context:** This component does NOT currently import `useWorkspacePermissions` or `useUserPermissions`. However, each workspace object in the `workspaces` list already carries a `role` field (serialized by the backend's `_serialize_workspace`). Use this existing `role` field directly instead of adding new hook calls.

- [ ] **Step 1: Find the context menu rendering (around lines 740-803)**

Read the file to locate the exact menu items for "Members Management" and "API Keys", and confirm the workspace object structure includes `role`.

- [ ] **Step 2: Gate admin-only menu items using the workspace's `role` field**

Check the role of the active workspace and conditionally render:

```tsx
{(activeWorkspace.role === 'owner' || activeWorkspace.role === 'admin') && (
  <>
    <DropdownMenuItem onClick={...}>Members Management</DropdownMenuItem>
    <DropdownMenuItem onClick={...}>API Keys</DropdownMenuItem>
  </>
)}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/sidebar/components/workspace-header/workspace-header.tsx
git commit -m "fix: hide admin-only menu items (Members, API Keys) from non-admin users in workspace switcher"
```

---

## Phase 4: Resource Access Control Gaps

### Task 12: Add workspace membership check to Traces API

Currently any authenticated user can query any workspace's traces by passing an arbitrary `workspace_id`. Add workspace membership validation.

**Files:**
- Modify: `backend/app/api/v1/traces.py:162-198`

- [ ] **Step 1: Add workspace membership check when `workspace_id` is provided**

In `list_traces`, after the service is created and before querying:

```python
# 如果指定了 workspace_id，校验当前用户是否有权限访问该工作空间
if workspace_id:
    from app.services.workspace_permission import check_workspace_access
    from app.models.workspace import WorkspaceMemberRole
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)
    if not has_access:
        raise ForbiddenException("No access to workspace traces")
```

Add the import at the top:
```python
from app.common.exceptions import ForbiddenException
```

- [ ] **Step 2: Same check in `get_trace_detail` — validate workspace ownership of the trace**

After fetching the trace, if `trace.workspace_id` is set, check membership:

```python
if trace.workspace_id:
    from app.services.workspace_permission import check_workspace_access
    from app.models.workspace import WorkspaceMemberRole
    has_access = await check_workspace_access(db, trace.workspace_id, current_user, WorkspaceMemberRole.viewer)
    if not has_access:
        raise ForbiddenException("No access to workspace traces")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/traces.py
git commit -m "fix: add workspace membership check to traces API endpoints"
```

---

### Task 13: Add workspace access check to Copilot endpoints

The copilot history/messages endpoints under `/graphs/{graph_id}/copilot/*` never check graph or workspace access.

**Files:**
- Modify: `backend/app/api/v1/graphs.py` (copilot endpoints)

- [ ] **Step 1: Identify the copilot endpoints in graphs.py**

Search for `copilot` in the file to find exact line numbers.

- [ ] **Step 2: Add workspace access check to each copilot endpoint**

The copilot endpoints use `CopilotService`, not the graph service. To look up the graph's workspace, you need to query the graph separately. The existing `_ensure_workspace_member` helper in `graphs.py` calls `check_workspace_access` and raises `ForbiddenException` — reuse it.

For each copilot endpoint (`GET /{graph_id}/copilot/history`, `DELETE /{graph_id}/copilot/history`, `POST /{graph_id}/copilot/messages`):

1. Import and instantiate the graph repository to look up the graph
2. Use the existing `_ensure_workspace_member` helper

```python
from app.repositories.graph import GraphRepository

# At the start of the copilot endpoint:
graph_repo = GraphRepository(db)
graph = await graph_repo.get(graph_id)
if graph and graph.workspace_id:
    await _ensure_workspace_member(db, graph.workspace_id, current_user, WorkspaceMemberRole.viewer)
```

For write operations (POST messages, DELETE history), use `WorkspaceMemberRole.member` instead of `viewer`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/graphs.py
git commit -m "fix: add workspace access check to copilot history and messages endpoints"
```

---

### Task 14: Add workspace membership check to graph schema import

`POST /schema/import` passes `workspace_id` from the request body to create a graph without checking membership.

**Files:**
- Modify: `backend/app/api/v1/graph_schemas.py`

- [ ] **Step 1: Read the file to find the import endpoint**

```bash
grep -n "import" backend/app/api/v1/graph_schemas.py
```

- [ ] **Step 2: Add workspace membership check before creating the graph**

```python
if workspace_id:
    from app.services.workspace_permission import check_workspace_access
    from app.models.workspace import WorkspaceMemberRole
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to import into this workspace")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/graph_schemas.py
git commit -m "fix: add workspace membership check to graph schema import endpoint"
```

---

## Summary of All Changes

| # | File | Change | Severity | Deps |
|---|------|--------|----------|------|
| 1 | `workspaces.py` | Reorder invitation routes before `/{workspace_id}` | CRITICAL | — |
| 2 | `dependencies.py` | Delete unused `require_roles` (broken no-op) | CRITICAL | — |
| 3 | `workspace_service.py` | Prevent owner removal in `remove_member` | CRITICAL | — |
| 4 | `repositories/workspace.py` | `flush()` instead of `commit()` in `update_status` | HIGH | — |
| 5 | `workspace_service.py` | Accept-invitation idempotent for existing members | HIGH | Task 4 |
| 6 | `workspace_service.py` | Duplicate invitation check + email normalization | HIGH | — |
| 7 | `workspace_service.py` | Remove dead code (datetime call + deprecated method) | LOW | — |
| 8 | `environment.py` | Delete unused `_ensure_workspace_role` helper | MEDIUM | — |
| 9 | `accept/page.tsx` | Fix `/auth/signin` → `/signin` | CRITICAL | — |
| 10 | `workspaceService.ts` + `accept/page.tsx` | Token vs ID accept distinction | HIGH | Task 1 |
| 11 | `workspace-header.tsx` | Hide admin-only menu items via `workspace.role` | HIGH | — |
| 12 | `traces.py` | Add workspace membership check | CRITICAL | — |
| 13 | `graphs.py` (copilot) | Add workspace access check via graph lookup | HIGH | — |
| 14 | `graph_schemas.py` | Add workspace membership check to import | HIGH | — |
