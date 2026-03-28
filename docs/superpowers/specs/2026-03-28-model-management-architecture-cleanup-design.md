# Model Management Architecture Cleanup Design

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Backend only — no frontend or database schema changes

## Background

The model management module has three concrete architectural problems:

1. **Custom model creation logic is misplaced.** `ModelCredentialService._add_one_custom_model` orchestrates provider + credential + instance creation, which is not a credential concern.
2. **Dead code accumulation.** `_sync_credentials` is a no-op stub, `sync_all` still returns a `credentials` field that is always 0, and `ModelProviderService.__init__` holds commented-out references to unused repos.
3. **N+1 query in `get_available_models`.** Each provider triggers a separate DB query to fetch credentials, making performance degrade linearly with provider count.

Additionally, `ModelProviderService.get_all_providers` and `get_provider` each contain duplicated logic for merging Factory and DB provider data, with no shared abstraction.

## Goals

- Introduce `ProviderResolver` as a pure data-merging layer between Factory and DB
- Move custom model orchestration from `ModelCredentialService` to `ModelProviderService`
- Fix the N+1 credential query in `get_available_models`
- Delete all dead code

## Non-Goals

- No frontend changes
- No database schema or migration changes
- No new API endpoints
- No multi-tenancy changes (user_id/workspace_id scoping remains as-is)
- No caching layer

---

## Architecture

### Layer Diagram (Target State)

```
API Layer
  ↓
Service Layer
  ModelProviderService   ← provider CRUD + custom model creation (orchestration)
  ModelCredentialService ← credential CRUD only (no custom special-casing)
  ModelService           ← model instance queries + runtime model resolution
  ↓
ProviderResolver  (new: core/model/provider_resolver.py)
  ← pure functions, merges Factory + DB data
  ← no DB dependency, independently testable
  ↓
Repository Layer / ModelFactory
```

---

## Component Designs

### 1. ProviderResolver

**File:** `backend/app/core/model/provider_resolver.py`

A module of pure functions with no DB or async dependencies. Centralizes the logic for merging Factory-sourced and DB-sourced provider data, which is currently duplicated across `get_all_providers` and `get_provider`.

**Data structure:**

```python
@dataclass
class ResolvedProvider:
    provider_name: str
    display_name: str
    supported_model_types: list[str]
    credential_schema: dict
    config_schemas: dict
    model_count: int
    is_template: bool
    provider_type: str          # "system" | "custom"
    template_name: str | None
    is_enabled: bool
    id: str | None              # DB row UUID; None for factory-only providers
    icon: str | None
    description: str | None
```

**Public interface:**

```python
def resolve_all_providers(
    factory_providers: list[dict],
    db_providers: list[ModelProvider],
) -> list[ResolvedProvider]:
    """Merge factory and DB sources into a sorted unified list."""

def resolve_one_provider(
    provider_name: str,
    factory_provider: BaseProvider | None,
    db_provider: ModelProvider | None,
) -> ResolvedProvider | None:
    """Merge a single provider. Returns None if both sources are absent."""
```

**Merge rules:**

| Scenario | Behavior |
|----------|----------|
| Factory only (template provider) | Use factory data; `id`, `icon`, `description` are None; `is_enabled` defaults to True |
| Factory + DB | Factory data is authoritative; DB supplements `id`, `icon`, `description`, `is_enabled` |
| DB only (custom provider) | DB data is authoritative; attempt to resolve `credential_schema` / `supported_model_types` from `template_name` via factory |
| Neither | Return None |

Sorting follows the existing `BUILTIN_PROVIDER_ORDER` constant, moved into this module.

---

### 2. Custom Model Creation Migration

**Problem:** `ModelCredentialService._add_one_custom_model` creates a provider row, a credential row, and a model instance row — three concerns in one method inside the wrong service.

**Target:** Move orchestration to `ModelProviderService`.

**New method on `ModelProviderService`:**

```python
async def add_custom_model(
    self,
    user_id: str,
    model_name: str,
    credentials: dict,
    model_parameters: dict | None,
    display_name: str | None,
    validate: bool,
) -> dict:
    """
    Create a custom-{ts} provider + credential + model instance in one transaction.
    Returns the credential summary dict (same shape as before).
    """
```

**Change to `ModelCredentialService.create_or_update_credential`:**

```python
# Before
if provider_name == "custom" and model_name and model_name.strip():
    return await self._add_one_custom_model(...)

# After
if provider_name == "custom" and model_name and model_name.strip():
    from app.services.model_provider_service import ModelProviderService
    return await ModelProviderService(self.db).add_custom_model(...)
```

**New internal method on `ModelCredentialService`:**

```python
async def _create_credential_for_provider(
    self,
    user_id: str,
    provider_id: uuid.UUID,
    credentials: dict,
    is_valid: bool,
    validation_error: str | None,
) -> ModelCredential:
    """Write a single credential row. No orchestration."""
```

`ModelProviderService.add_custom_model` calls this method for the credential step, keeping `ModelCredentialService` as the single writer of credential rows.

After this change, `ModelCredentialService._add_one_custom_model` is deleted.

---

### 3. N+1 Fix in `get_available_models`

**Problem:** Current loop calls `get_decrypted_credentials(pname)` per provider — one DB query each.

**Fix:** Add a batch method to `ModelCredentialService`:

```python
async def get_all_decrypted_credentials_map(
    self,
    user_id: str | None = None,
) -> dict[str, dict]:
    """
    Single query for all valid credentials.
    Returns {provider_name: decrypted_credentials_dict}.
    For providers with multiple credentials, prefer user-scoped over global,
    valid over invalid (same priority logic as get_decrypted_credentials).
    """
```

**Change to `ModelService.get_available_models`:**

```python
# Before
for pname in relevant_providers:
    decrypted = await self.credential_service.get_decrypted_credentials(pname, user_id=user_id)
    if decrypted:
        credentials_dict[pname] = decrypted

# After
credentials_dict = await self.credential_service.get_all_decrypted_credentials_map(user_id=user_id)
```

The rest of the method is unchanged.

---

### 4. Dead Code Removal

| Location | Action |
|----------|--------|
| `ModelProviderService._sync_credentials` | Delete method |
| `ModelProviderService.sync_all` return value | Remove `credentials` key from result dict and docstring |
| `ModelProviderService.__init__` | Remove commented-out `credential_repo` and `credential_service` references |
| `ModelProviderService.get_all_providers` merge logic | Replace with `resolve_all_providers(factory_providers, db_providers)` |
| `ModelProviderService.get_provider` merge logic | Replace with `resolve_one_provider(provider_name, factory_provider, db_provider)` |
| `ModelCredentialService._add_one_custom_model` | Delete after migration to `ModelProviderService.add_custom_model` |

---

## Data Flow (Target State)

### Adding a custom model

```
POST /api/v1/model-credentials  {provider_name: "custom", model_name: "..."}
  → ModelCredentialService.create_or_update_credential
  → ModelProviderService.add_custom_model          ← orchestration here
      → provider_repo.create(custom-{ts})
      → ModelCredentialService._create_credential_for_provider
      → instance_repo.create(model_instance)
      → commit
  → return credential summary
```

### Getting available models

```
GET /api/v1/models?model_type=chat
  → ModelService.get_available_models
  → credential_service.get_all_decrypted_credentials_map()  ← single DB query
  → instance_repo.list_all()                                ← single DB query
  → in-memory join + factory lookup
  → return model list
```

### Getting provider list

```
GET /api/v1/model-providers
  → ModelProviderService.get_all_providers
  → factory.get_all_providers()          ← in-memory
  → provider_repo.find()                 ← single DB query
  → ProviderResolver.resolve_all_providers(factory_data, db_data)  ← pure function
  → return sorted ResolvedProvider list
```

---

## File Changes Summary

| File | Change |
|------|--------|
| `backend/app/core/model/provider_resolver.py` | **New** — `ResolvedProvider` dataclass + `resolve_all_providers` + `resolve_one_provider` |
| `backend/app/services/model_provider_service.py` | Add `add_custom_model`; replace merge logic with resolver calls; delete `_sync_credentials`; clean `sync_all`; clean `__init__` |
| `backend/app/services/model_credential_service.py` | Add `get_all_decrypted_credentials_map` + `_create_credential_for_provider`; redirect custom branch to `ModelProviderService`; delete `_add_one_custom_model` |
| `backend/app/services/model_service.py` | Replace N+1 loop with `get_all_decrypted_credentials_map` call |

No changes to: API layer, repository layer, ORM models, frontend, database migrations.

---

## Testing Approach

- `ProviderResolver` functions are pure — unit test with mock dicts, no DB needed
- `ModelProviderService.add_custom_model` — integration test: verify provider + credential + instance all created in one transaction
- `get_all_decrypted_credentials_map` — unit test priority logic (user-scoped vs global, valid vs invalid)
- `get_available_models` — verify result is identical before/after N+1 fix with same fixture data
