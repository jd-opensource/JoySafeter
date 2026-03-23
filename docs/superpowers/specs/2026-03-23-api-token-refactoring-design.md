# API Token System Refactoring Design

**Date:** 2026-03-23
**Status:** Draft
**Author:** System Architecture Team

## Executive Summary

Refactor the API token system to unify two parallel token mechanisms (PlatformToken and ApiKey) into a single, secure, scalable system with high cohesion, low coupling, and intuitive user management UI.

## Current State Analysis

### Problems

1. **Dual Token Systems** — PlatformToken (SHA-256 hashed, user-scoped) and ApiKey (plaintext stored, workspace-scoped) coexist with overlapping responsibilities
2. **Inconsistent Scopes** — Global tokens use `skills:*` prefix, skill-specific tokens use `skill:execute` (singular vs plural)
3. **Fragmented UI** — Token management scattered across 3 locations (Settings, SkillApiAccessDialog, ApiAccessDialog) with different interaction patterns
4. **Client-Side Filtering** — Frontend fetches all tokens then filters by resource, inefficient
5. **Security Risk** — ApiKey stores plaintext tokens in database

### Existing Architecture

**PlatformToken System (newer):**
- Backend: `platform_tokens` table, SHA-256 hashed storage, scope-based permissions
- Frontend: Settings TokensPage + Skill ApiTokensTab
- Scopes: `skills:read/write/execute/publish/admin`, `skill:execute`

**ApiKey System (legacy):**
- Backend: `api_keys` table, plaintext storage, workspace-level access
- Frontend: Workspace ApiAccessDialog
- No scope system

## Design Goals

1. **Unify** — Single token system for all resources (skills, graphs, tools)
2. **Secure** — SHA-256 hashed storage everywhere, no plaintext
3. **Scalable** — Extensible scope system for future resource types
4. **Intuitive** — Each context (Settings/Skill/Workspace) has complete CRUD, filtered to relevant tokens
5. **Performant** — Backend filters by resource, no client-side filtering

## Architecture Design

### 1. Unified Scope System

**Three-tier resource types:**
```
skill | graph | tool
```

**Unified actions:**
```
read | write | execute | publish | admin
```

**Scope format:** `{resource}:{action}`

**Defined scopes:**
```typescript
type Scope =
  | 'skills:read' | 'skills:write' | 'skills:execute' | 'skills:publish' | 'skills:admin'
  | 'graphs:read' | 'graphs:execute'
  | 'tools:read' | 'tools:execute';
```

**Permission hierarchy:**
```
admin > publish > execute > write > read
```

**Resource binding:**
- **Global token:** `resource_type = NULL, resource_id = NULL` — applies to all resources of that type
- **Resource-bound token:** `resource_type = 'skill', resource_id = 'skill_123'` — applies only to that specific resource

**Examples:**
- Token A: `scopes=['skills:read']`, `resource_type=NULL` → can read all skills
- Token B: `scopes=['skills:admin']`, `resource_type='skill', resource_id='skill_123'` → admin access only to skill_123

### 2. Backend Architecture

#### Data Model

**Reuse existing `platform_tokens` table** — no schema changes needed:
```sql
-- Existing columns already support the design:
-- scopes: JSONB array
-- resource_type: VARCHAR(50) | NULL
-- resource_id: VARCHAR(255) | NULL
```

#### Repository Layer

```python
# backend/app/repositories/platform_token.py
class PlatformTokenRepository:
    async def list_by_user_and_resource(
        self,
        user_id: int,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None
    ) -> List[PlatformToken]:
        """Query tokens with optional resource filtering"""
        query = select(PlatformToken).where(
            PlatformToken.user_id == user_id,
            PlatformToken.is_active == True
        )
        if resource_type is not None:
            query = query.where(PlatformToken.resource_type == resource_type)
        if resource_id is not None:
            query = query.where(PlatformToken.resource_id == resource_id)
        query = query.order_by(PlatformToken.created_at.desc())
        result = await self.db.execute(query)
        return result.scalars().all()
```

#### Service Layer

```python
# backend/app/services/platform_token_service.py
class PlatformTokenService:
    MAX_ACTIVE_TOKENS_PER_USER = 50  # Configurable constant

    VALID_SCOPES = {
        'skills:read', 'skills:write', 'skills:execute', 'skills:publish', 'skills:admin',
        'graphs:read', 'graphs:execute',
        'tools:read', 'tools:execute'
    }

    async def list_tokens(
        self,
        user_id: int,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None
    ) -> List[PlatformToken]:
        return await self.repo.list_by_user_and_resource(
            user_id, resource_type, resource_id
        )

    async def create_token(self, ..., scopes: List[str], ...) -> TokenCreateResponse:
        # Validate scopes
        invalid = set(scopes) - self.VALID_SCOPES
        if invalid:
            raise ValidationException(f"Invalid scopes: {invalid}")
        # ... rest unchanged

    async def revoke_by_resource(self, resource_type: str, resource_id: str) -> int:
        """Soft-delete all tokens bound to a resource (called on resource deletion)"""
        count = await self.repo.deactivate_by_resource(resource_type, resource_id)
        return count
```

#### API Layer

```python
# backend/app/api/v1/tokens.py
@router.get("/v1/tokens")
async def list_tokens(
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List tokens with optional resource filtering"""
    tokens = await token_service.list_tokens(
        current_user.id, resource_type, resource_id
    )
    return [TokenSchema.from_orm(t) for t in tokens]
```

#### Unified Permission Check

```python
# backend/app/common/permissions.py

# Permission hierarchy: higher levels include all lower levels
SCOPE_HIERARCHY = {
    'skills': ['admin', 'publish', 'execute', 'write', 'read'],
    'graphs': ['execute', 'read'],
    'tools': ['execute', 'read']
}

def _scope_satisfies(token_scope: str, required_scope: str) -> bool:
    """Check if token_scope satisfies required_scope via hierarchy"""
    if token_scope == required_scope:
        return True

    # Parse resource:action
    try:
        token_resource, token_action = token_scope.split(':')
        required_resource, required_action = required_scope.split(':')
    except ValueError:
        return False

    if token_resource != required_resource:
        return False

    hierarchy = SCOPE_HIERARCHY.get(token_resource, [])
    try:
        token_level = hierarchy.index(token_action)
        required_level = hierarchy.index(required_action)
        return token_level <= required_level  # Lower index = higher permission
    except ValueError:
        return False

def check_token_permission(
    token_scopes: List[str],
    required_scope: str,
    resource_type: str,
    resource_id: str,
    token_resource_type: Optional[str],
    token_resource_id: Optional[str]
) -> bool:
    """Unified permission check with hierarchical scope matching"""
    # 1. Check scope presence (with hierarchy)
    has_scope = any(_scope_satisfies(ts, required_scope) for ts in token_scopes)
    if not has_scope:
        return False

    # 2. Check resource binding
    if token_resource_type is None:
        # Global token, pass
        return True

    if token_resource_type == resource_type and token_resource_id == resource_id:
        # Bound to target resource, pass
        return True

    return False
```

### 3. Frontend Architecture

#### Service Layer

```typescript
// frontend/services/platformTokenService.ts
export interface TokenListParams {
  resourceType?: 'skill' | 'graph' | 'tool';
  resourceId?: string;
}

export const platformTokenService = {
  listTokens: async (params?: TokenListParams): Promise<PlatformToken[]> => {
    const queryParams = new URLSearchParams();
    if (params?.resourceType) queryParams.set('resource_type', params.resourceType);
    if (params?.resourceId) queryParams.set('resource_id', params.resourceId);

    const url = `/api/v1/tokens${queryParams.toString() ? `?${queryParams}` : ''}`;
    const response = await fetch(url);
    return normalizeToCamelCase(await response.json());
  },
  // createToken, revokeToken unchanged
};
```

#### Hooks Layer

```typescript
// frontend/hooks/queries/platformTokens.ts
export function usePlatformTokens(params?: TokenListParams) {
  return useQuery({
    queryKey: ['platform-tokens', params?.resourceType, params?.resourceId],
    queryFn: () => platformTokenService.listTokens(params),
    staleTime: STALE_TIME.LONG
  });
}

export function useRevokeToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: platformTokenService.revokeToken,
    onSuccess: (_, tokenId) => {
      // Granular invalidation: invalidate all token queries
      // (we don't know which resources this token was bound to)
      queryClient.invalidateQueries({ queryKey: ['platform-tokens'] });
    }
  });
}
```

#### Component Architecture

**Three independent entry points sharing base components:**

```
TokensPage (Settings global management)
  └─> TokenList (shared)
       └─> TokenItem (shared)

SkillApiTokensTab (Skill-specific management)
  └─> TokenList (shared)
       └─> TokenItem (shared)

WorkspaceApiTokensDialog (Workspace-specific management)
  └─> TokenList (shared)
       └─> TokenItem (shared)
```

**Shared component design:**

```typescript
// frontend/components/tokens/TokenList.tsx
interface TokenListProps {
  resourceType?: 'skill' | 'graph' | 'tool';
  resourceId?: string;
  showCreateButton?: boolean;
  createButtonScopes?: string[];
}

export function TokenList({
  resourceType,
  resourceId,
  showCreateButton,
  createButtonScopes
}: TokenListProps) {
  const { data: tokens } = usePlatformTokens({ resourceType, resourceId });
  const { mutate: revoke } = useRevokeToken();

  return (
    <div>
      {showCreateButton && <CreateTokenButton defaultScopes={createButtonScopes} />}
      {tokens?.map(token => <TokenItem key={token.id} token={token} onRevoke={revoke} />)}
    </div>
  );
}
```

**Three entry point implementations:**

```typescript
// 1. Settings global management
// frontend/components/settings/tokens-page.tsx
export function TokensPage() {
  return <TokenList showCreateButton createButtonScopes={[]} />;
}

// 2. Skill-specific management
// frontend/app/skills/[skillId]/components/ApiTokensTab.tsx
export function ApiTokensTab({ skillId }: { skillId: string }) {
  return (
    <TokenList
      resourceType="skill"
      resourceId={skillId}
      showCreateButton
      createButtonScopes={['skills:execute']}
    />
  );
}

// 3. Workspace-specific management
// frontend/app/workspace/[workspaceId]/components/WorkspaceApiTokensDialog.tsx
export function WorkspaceApiTokensDialog({ workspaceId }: { workspaceId: string }) {
  return (
    <TokenList
      resourceType="graph"
      resourceId={workspaceId}
      showCreateButton
      createButtonScopes={['graphs:execute']}
    />
  );
}
```

### 4. Migration Strategy

#### Data Migration

```python
# backend/alembic/versions/20260323_migrate_apikey_to_platform_token.py
async def upgrade():
    # 1. Migrate active ApiKeys to PlatformTokens
    # Note: ApiKey stores plaintext tokens, we hash them directly
    api_keys = await db.execute(
        select(ApiKey).where(ApiKey.is_active == True)
    )

    for api_key in api_keys.scalars():
        # Hash the existing plaintext token from ApiKey
        # Prefix with 'sk_' if not already present
        existing_token = api_key.key
        if not existing_token.startswith('sk_'):
            existing_token = f"sk_{existing_token}"

        token_hash = hashlib.sha256(existing_token.encode()).hexdigest()

        platform_token = PlatformToken(
            user_id=api_key.user_id,
            name=f"Migrated: {api_key.name}",
            token_hash=token_hash,
            token_prefix=existing_token[:12],
            scopes=['graphs:execute'],
            resource_type='graph',
            resource_id=str(api_key.workspace_id),  # workspace_id maps to graph resource_id
            expires_at=api_key.expires_at,
            is_active=True
        )
        db.add(platform_token)

    await db.commit()

    # 2. Rename api_keys table for 30-day verification period
    op.rename_table('api_keys', 'api_keys_deprecated')
    op.execute("COMMENT ON TABLE api_keys_deprecated IS 'Deprecated, safe to drop after 2026-04-23'")

async def downgrade():
    # Rollback: restore api_keys table
    op.rename_table('api_keys_deprecated', 'api_keys')
    # Delete migrated PlatformTokens
    await db.execute(
        delete(PlatformToken).where(PlatformToken.name.like('Migrated:%'))
    )
    await db.commit()
```

#### Code Removal

**Backend:**
- Delete `models/api_key.py`
- Delete `services/api_key_service.py`
- Delete `repositories/api_key_repository.py`
- Delete `api/v1/api_keys.py`

**Frontend:**
- Delete `components/workspace/ApiAccessDialog.tsx`
- Delete `services/apiKeyService.ts`
- Delete `hooks/queries/apiKeys.ts`

### 5. Error Handling

#### Backend Validation

```python
# 1. Invalid scopes
if invalid_scopes:
    raise ValidationException(f"Invalid scopes: {invalid_scopes}")

# 2. Resource not found
if resource_type == 'skill':
    skill = await skill_repo.get(resource_id)
    if not skill:
        raise NotFoundException(f"Skill {resource_id} not found")

# 3. No permission to bind resource
if resource_type == 'skill':
    has_access = await check_skill_access(user_id, resource_id, 'admin')
    if not has_access:
        raise ForbiddenException("No permission to create token for this skill")

# 4. Token limit exceeded
if await token_repo.count_active_by_user(user_id) >= 50:
    raise ValidationException("Maximum 50 active tokens per user")
```

#### Frontend Error Handling

```typescript
const { mutate: createToken, error } = useCreateToken();

if (error?.message.includes('Invalid scopes')) {
  toast.error('Invalid scope selection');
} else if (error?.message.includes('Maximum 50')) {
  toast.error('Token limit reached (50 tokens max)');
}
```

#### Edge Cases

1. **Global vs resource token conflict** — Both allowed, permission check prioritizes resource-bound tokens
2. **Resource deletion** — Cascade soft-delete bound tokens (`is_active=False`) via service layer hooks:
   - `SkillService.delete()` calls `TokenService.revoke_by_resource('skill', skill_id)`
   - `WorkspaceService.delete()` calls `TokenService.revoke_by_resource('graph', workspace_id)`
3. **Expired tokens** — Auth checks `expires_at`, auto-reject if expired; list shows but marks as "Expired"
4. **Workspace-to-Graph mapping** — In this system, workspace ID directly maps to graph resource_id (1:1 relationship). Migration uses `str(api_key.workspace_id)` as `resource_id`.

## Implementation Plan

### Phase 1: Backend Foundation
1. Add database indexes on `resource_type` and `resource_id` columns
2. Add `list_by_user_and_resource()` to repository
3. Update service layer with scope validation and hierarchy
4. Add query parameters to API endpoint
5. Implement unified permission check function with hierarchy
6. Write unit tests for hierarchical permission checking

### Phase 2: Frontend Refactoring
1. Update service layer with `TokenListParams`
2. Adjust hooks to support filtering with granular invalidation
3. Create shared `TokenList` and `TokenItem` components
4. Refactor Settings TokensPage
5. Refactor Skill ApiTokensTab
6. Create Workspace WorkspaceApiTokensDialog

### Phase 3: Migration & Cleanup
1. Write and test migration script (preserves existing tokens)
2. Run migration in staging, verify existing integrations still work
3. Keep `api_keys_deprecated` table for 30 days
4. Delete ApiKey backend code (keep models for migration reference)
5. Delete ApiKey frontend code
6. Update API documentation
7. After 30-day verification: drop `api_keys_deprecated` table

### Phase 4: Testing & Deployment
1. Integration tests for all three entry points
2. E2E tests for token creation/revocation flows
3. Security audit
4. Deploy to production
5. Monitor for issues

## File Change Summary

### Backend Changes

**Modified:**
- `repositories/platform_token.py` — Add `list_by_user_and_resource()`
- `services/platform_token_service.py` — Add scope validation, update `list_tokens()`
- `api/v1/tokens.py` — Add query parameters

**Added:**
- `common/permissions.py` — Unified permission check
- `alembic/versions/xxx_migrate_apikey.py` — Migration script

**Deleted:**
- `models/api_key.py`
- `services/api_key_service.py`
- `repositories/api_key_repository.py`
- `api/v1/api_keys.py`

### Frontend Changes

**Modified:**
- `services/platformTokenService.ts` — Add `TokenListParams`
- `hooks/queries/platformTokens.ts` — Support filtering
- `components/settings/tokens-page.tsx` — Use shared components
- `app/skills/[skillId]/components/ApiTokensTab.tsx` — Refactor with shared components

**Added:**
- `components/tokens/TokenList.tsx` — Shared list component
- `components/tokens/TokenItem.tsx` — Shared item component
- `app/workspace/[workspaceId]/components/WorkspaceApiTokensDialog.tsx` — New workspace token management

**Deleted:**
- `components/workspace/ApiAccessDialog.tsx`
- `services/apiKeyService.ts`
- `hooks/queries/apiKeys.ts`

## Success Metrics

1. **Unification** — Zero ApiKey references in codebase
2. **Security** — 100% tokens stored as SHA-256 hashes
3. **Performance** — Token list queries filtered server-side, <100ms response time
4. **Usability** — Each context (Settings/Skill/Workspace) shows only relevant tokens
5. **Extensibility** — New resource types (memory, chat) can add scopes without refactoring

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Migration data loss | Preserve existing token values by hashing them; test migration script thoroughly in staging; keep `api_keys_deprecated` table for 30 days before hard delete |
| Breaking existing integrations | Migration preserves existing token values, no integration changes needed |
| Performance regression | Add database indexes on `resource_type` and `resource_id` columns in Phase 1 |
| Scope confusion | Clear UI labels, inline help text explaining each scope |
| Rate limiting attacks | Add rate limiting to token endpoints (100 req/min per user) |

## Conclusion

This refactoring unifies two parallel token systems into a single, secure, scalable architecture with intuitive UI. The design achieves high cohesion (single token system), low coupling (shared components, filtered queries), and extensibility (scope system supports future resource types).
