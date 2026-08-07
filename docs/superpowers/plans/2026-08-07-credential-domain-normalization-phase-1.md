# Credential Domain Normalization Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct credential references and lifecycle behavior, pause incomplete MCP OAuth creation, and present one consistent credential vocabulary without changing database tables, public routes, resource IDs, or established JSON field names.

**Architecture:** Backend validation is centralized at domain boundaries: Webhook Trigger validation reuses the runtime resolver, Environment reference extraction is a single pure function shared by API validation and Secret lifecycle scans, and Secret mutations trigger the existing network-policy refresh mechanism. Frontend adds a paginated Generic Secret query plus a resource-level Service Credential selector, keeps credential values out of the browser, removes the incomplete OAuth creation branch, and changes only user-visible copy while preserving internal route/type names.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL, pytest; TypeScript, React 19, Next.js 16, TanStack Query, Radix Select, Vitest, Testing Library, i18next.

## Global Constraints

- Preserve `/api/v1/secrets`, `/api/v1/vaults`, `/api/v1/auth/api-keys`, `/managed/secrets`, `/managed/vaults`, and `/managed/api-keys`.
- Preserve `Secret.kind = llm | generic`, `secret_ref`, `secret_key`, `credential_ref`, `vault_ids`, and existing resource ID formats.
- Do not add a database migration or rename ORM models, tables, API fields, routes, query parameters, or internal TypeScript entity types.
- New Webhook Trigger and Environment service-credential references must resolve only `kind=generic` Secrets in the current project.
- Secret list responses remain metadata-only: selectors may use `id`, `name`, `kind`, `keys`, and non-secret metadata, but must never request or cache plaintext values.
- Existing `mcp_oauth` and `oauth` Vault Credential rows remain readable, listable, archivable, deletable, and usable as stored Bearer tokens; only new creation is rejected.
- Do not implement OAuth authorization, callback, refresh, or token exchange in this phase.
- Backend tests run from `backend/`: `uv run pytest ...`.
- Frontend tests run from `frontend/`: `bun run test -- ...`; static checks use `bun run type-check` and `bun run lint`.
- The working tree already contains unrelated uncommitted edits, including adjacent edits in `frontend/app/managed/quickstart/page.tsx`, both locale files, and Secret pages. Preserve those edits and patch only the lines named in this plan.
- Do not touch `.deps/SkillSpector`.
- Do not create commits unless the user explicitly requests them.

---

## File Structure

### New Files

- `frontend/hooks/managed/use-service-credentials.ts` — fetch every `kind=generic` Secret page and expose a scoped TanStack Query.
- `frontend/hooks/managed/use-service-credentials.test.tsx` — prove pagination, project scoping, parsing, and invalid-cursor protection.
- `frontend/components/managed/shared/service-credential-select.tsx` — render Secret resources by name, including an explicit unavailable historical value.
- `frontend/components/managed/shared/service-credential-select.test.tsx` — verify resource-name values and unavailable historical option rendering.
- `frontend/lib/i18n/credential-terminology.test.ts` — pin the bilingual user vocabulary at the key paths used by navigation and credential workflows.

### Existing Files With Focused Changes

- `backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py` — one resolver for create, update, and runtime Webhook secret checks.
- `backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py` — carry the effective Secret name and field when either changes.
- `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py` — call the shared resolver before persistence.
- `backend/app/joysafeter_domain/schemas/joysafeter_environment.py` — pure, typed extraction of direct and Egress Secret references.
- `backend/app/joysafeter_api/api/v1/environments.py` — validate every extracted reference for existence and `kind=generic`.
- `backend/app/joysafeter_domain/services/joysafeter_secret_service.py` — reuse Environment extraction and include Trigger references.
- `backend/app/joysafeter_api/api/v1/secrets.py` — block Trigger-referenced deletion and refresh live limited sandboxes after mutations.
- `backend/app/joysafeter_domain/services/joysafeter_vault_service.py` — reject new unsupported credential types and blank static Bearer tokens at the service boundary.
- `backend/app/joysafeter_api/api/v1/vaults.py` — preserve the service error contract and continue normal audit/refresh behavior only after valid creation.
- `frontend/components/managed/triggers/create-trigger-dialog.tsx` — replace the field-name-as-resource bug with two-stage resource/field selection.
- `frontend/app/managed/vaults/components/create-credential-dialog.tsx` — fixed `static_bearer` creation with a required token.
- `frontend/lib/i18n/locales/en.ts` and `frontend/lib/i18n/locales/zh.ts` — user-visible terminology only.
- `frontend/app/managed/quickstart/page.tsx` and `frontend/app/managed/sessions/components/create-session-dialog.tsx` — remove two hard-coded old Vault labels.

---

### Task 1: Centralize Webhook Trigger Secret Validation

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py:75`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:19`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py:188`
- Test: `backend/tests/test_trigger_http_e2e_contract.py`
- Test: `backend/tests/test_trigger_update_validation.py`

**Interfaces:**
- Consumes: `SecretService.get_secret_by_name`, `SecretService.get_secret_data`, `SecretKind.GENERIC`, `TriggerUpdatePlan`.
- Produces: `WebhookAuthService.resolve_secret_value(*, secret_ref: str, secret_key: str, project_id: str | None, trigger_id: str | None = None) -> str`.
- Produces: `TriggerUpdatePlan.secret_key_to_verify: str | None`; `secret_ref_to_verify` and `secret_key_to_verify` are both populated when either Webhook field changes.
- Error contract: `TRIGGER_SECRET_NOT_FOUND`, `TRIGGER_SECRET_KIND_INVALID`, `TRIGGER_SECRET_KEY_NOT_FOUND`; errors include names and field names, never values.

- [ ] **Step 1: Add failing create and update contract tests**

Append tests to `backend/tests/test_trigger_http_e2e_contract.py` using its existing FastAPI test app and project/agent seeding helpers. Seed one LLM Secret and one Generic Secret lacking the requested field:

```python
@pytest.mark.asyncio
async def test_webhook_trigger_create_rejects_llm_secret(db_session):
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    llm_secret = JoySafeterSecret(
        name="model-only",
        project_id=project.id,
        kind="llm",
        provider="openai",
        protocol="openai_chat_completions",
        data=encrypted_secret_data({"OPENAI_API_KEY": "model-token", "MODEL": "gpt-5"}),
    )
    db_session.add(llm_secret)
    await db_session.commit()

    app = _app(db_session, _ctx(project.id, org.id))
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/triggers",
            json={
                "name": "invalid-llm-webhook",
                "type": "webhook",
                "agent_id": str(agent.id),
                "prompt_template": "run",
                "secret_ref": "model-only",
                "secret_key": "OPENAI_API_KEY",
                "auth_methods": ["hmac"],
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "TRIGGER_SECRET_KIND_INVALID"
    assert response.json()["data"] == {"secret_ref": "model-only", "kind": "llm"}
```

```python
@pytest.mark.asyncio
async def test_webhook_trigger_create_rejects_missing_credential_field(db_session):
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    app = _app(db_session, _ctx(project.id, org.id))

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/triggers",
            json={
                "name": "missing-field-webhook",
                "type": "webhook",
                "agent_id": str(agent.id),
                "prompt_template": "run",
                "secret_ref": "hook-secret",
                "secret_key": "MISSING_FIELD",
                "auth_methods": ["hmac"],
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "TRIGGER_SECRET_KEY_NOT_FOUND"
    assert response.json()["data"] == {
        "secret_ref": "hook-secret",
        "secret_key": "MISSING_FIELD",
    }
```

Add this update regression after creating a valid Trigger through the API:

```python
response = await client.patch(
    f"/api/v1/triggers/{trigger_id}",
    json={"secret_key": "MISSING_FIELD"},
)
assert response.status_code == 422
assert response.json()["code"] == "TRIGGER_SECRET_KEY_NOT_FOUND"
stored = await db_session.get(JoySafeterTrigger, TriggerId.from_public(trigger_id))
assert stored is not None
assert stored.secret_key == "WEBHOOK_SECRET"
```

- [ ] **Step 2: Run the focused tests and confirm the current gap**

Run:

```bash
cd backend
uv run pytest tests/test_trigger_http_e2e_contract.py tests/test_trigger_update_validation.py -q
```

Expected before implementation: the LLM Secret is accepted because only existence is checked, the missing field is accepted until runtime, and changing only `secret_key` does not request Secret verification.

- [ ] **Step 3: Add the shared Webhook Secret resolver**

In `joysafeter_trigger_webhook_auth_service.py`, import `SecretKind` and add this method before `resolve_webhook_secret`:

```python
async def resolve_secret_value(
    self,
    *,
    secret_ref: str,
    secret_key: str,
    project_id: Optional[str],
    trigger_id: Optional[str] = None,
) -> str:
    secret_svc = SecretService(self.db)
    secret = await secret_svc.get_secret_by_name(secret_ref, project_id=project_id)
    context = {"secret_ref": secret_ref}
    if trigger_id is not None:
        context["trigger_id"] = trigger_id
    if secret is None:
        raise NotFoundError(
            code="TRIGGER_SECRET_NOT_FOUND",
            message=f"Secret not found: {secret_ref}",
            data=context,
            user_action="fix_input",
        )
    if secret.kind != SecretKind.GENERIC.value:
        raise RequestValidationAppError(
            code="TRIGGER_SECRET_KIND_INVALID",
            message="Webhook triggers require a generic Secret",
            data={**context, "kind": secret.kind},
            user_action="fix_input",
        )
    secret_data = secret_svc.get_secret_data(secret)
    if secret_key not in secret_data:
        raise RequestValidationAppError(
            code="TRIGGER_SECRET_KEY_NOT_FOUND",
            message=f"Secret key not found: {secret_key}",
            data={**context, "secret_key": secret_key},
            user_action="fix_input",
        )
    return secret_data[secret_key]
```

Rewrite `resolve_webhook_secret(trigger)` to retain its `TRIGGER_SECRET_REF_REQUIRED` guard and delegate to `resolve_secret_value`, passing the effective field `trigger.secret_key or "WEBHOOK_SECRET"` and `str(trigger.id)`.

- [ ] **Step 4: Carry the effective field through update planning**

Extend `TriggerUpdatePlan`:

```python
@dataclass(frozen=True)
class TriggerUpdatePlan:
    fields: dict[str, Any]
    next_environment_ref: Optional[str]
    should_resolve_target: bool
    secret_ref_to_verify: Optional[str]
    secret_key_to_verify: Optional[str]
    recompute_next_run: bool
    is_reenable: bool
```

In `plan_update`, compute effective values after `_validate_webhook_fields`:

```python
verify_secret = trigger.type == "webhook" and bool({"secret_ref", "secret_key"} & fields.keys())
effective_secret_ref = fields.get("secret_ref", trigger.secret_ref)
effective_secret_key = fields.get("secret_key", trigger.secret_key)
```

Populate both plan fields only when `verify_secret` is true. Update `test_update_plan_captures_runtime_and_secret_dependency_checks` to assert both the effective name and field, and add a unit case proving a `secret_key`-only update carries the existing `secret_ref`.

- [ ] **Step 5: Validate before Trigger persistence**

In `JoySafeterTriggerService.create`, replace the existence-only `SecretService` lookup with:

```python
if type == "webhook" and secret_ref and secret_key:
    await WebhookAuthService(self.db).resolve_secret_value(
        secret_ref=secret_ref,
        secret_key=secret_key,
        project_id=project_id,
    )
```

In `update`, replace the existence-only lookup with:

```python
if plan.secret_ref_to_verify is not None and plan.secret_key_to_verify is not None:
    await WebhookAuthService(self.db).resolve_secret_value(
        secret_ref=plan.secret_ref_to_verify,
        secret_key=plan.secret_key_to_verify,
        project_id=trigger.project_id,
        trigger_id=str(trigger.id),
    )
```

This call remains before `plan.apply_to(trigger)` and before commit, so failed validation cannot mutate the row.

- [ ] **Step 6: Run focused Trigger tests**

Run:

```bash
cd backend
uv run pytest \
  tests/test_trigger_http_e2e_contract.py \
  tests/test_trigger_http_error_contract.py \
  tests/test_trigger_update_validation.py \
  tests/test_trigger_webhook_route_contract.py \
  tests/test_webhook_sample_curl.py -q
```

Expected: PASS; valid Generic Secret behavior and Webhook runtime authentication remain unchanged.

---

### Task 2: Unify Environment Secret Reference Extraction and Validation

**Files:**
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_environment.py:290`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py:181`
- Test: `backend/tests/test_environment_egress_service_schema.py`
- Test: `backend/tests/test_environment_lifecycle_active_sessions.py`

**Interfaces:**
- Produces: `EnvironmentSecretReference(name: str, source: Literal["secret_refs", "egress_services"])`.
- Produces: `extract_environment_secret_references(config: EnvironmentConfig | dict[str, Any] | None) -> list[EnvironmentSecretReference]`.
- The extractor trims names, ignores empty legacy values, deduplicates by Secret name while preserving first-seen order, and never inspects Secret values.
- Error contract: `ENVIRONMENT_SECRET_NOT_FOUND` and `ENVIRONMENT_SECRET_KIND_INVALID`, each with `data.secret_ref` and `data.source`.

- [ ] **Step 1: Write failing pure extraction tests**

Add to `test_environment_egress_service_schema.py`:

```python
def test_extract_environment_secret_references_unifies_direct_and_egress_refs():
    config = EnvironmentConfig(
        secret_refs=["shared", " direct-only ", "shared"],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": "egress-only",
            },
            {
                "name": "shared-service",
                "base_url": "https://shared.example.com",
                "credential_ref": "shared",
            },
        ],
    )

    assert extract_environment_secret_references(config) == [
        EnvironmentSecretReference("shared", "secret_refs"),
        EnvironmentSecretReference("direct-only", "secret_refs"),
        EnvironmentSecretReference("egress-only", "egress_services"),
    ]
```

Add this legacy dictionary case:

```python
def test_extract_environment_secret_references_tolerates_legacy_malformed_config():
    assert extract_environment_secret_references(
        {
            "secret_refs": ["", None, " direct "],
            "egress_services": [None, "invalid", {"credential_ref": " egress "}, {}],
        }
    ) == [
        EnvironmentSecretReference("direct", "secret_refs"),
        EnvironmentSecretReference("egress", "egress_services"),
    ]
```

- [ ] **Step 2: Add failing API validation tests**

In `test_environment_lifecycle_active_sessions.py`, add:

```python
@pytest.mark.asyncio
async def test_create_environment_rejects_missing_egress_credential(db_session):
    missing_ref = f"missing-egress-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(
        name=f"egress-env-{uuid.uuid4()}",
        config=EnvironmentConfig(
            egress_services=[
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": missing_ref,
                }
            ]
        ),
    )

    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ENVIRONMENT_SECRET_NOT_FOUND",
        "message": f"Secret not found: {missing_ref}",
        "data": {"secret_ref": missing_ref, "source": "egress_services"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
```

Add a parameterized kind test that exercises both sources:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["secret_refs", "egress_services"])
async def test_create_environment_rejects_llm_secret_for_service_credentials(db_session, source):
    llm_secret = await _project_secret(db_session, kind="llm")
    config = (
        EnvironmentConfig(secret_refs=[llm_secret.name])
        if source == "secret_refs"
        else EnvironmentConfig(
            egress_services=[
                {
                    "name": "model-api",
                    "base_url": "https://model.example.com",
                    "credential_ref": llm_secret.name,
                }
            ]
        )
    )
    req = CreateEnvironmentRequest(name=f"invalid-kind-{uuid.uuid4()}", config=config)

    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "ENVIRONMENT_SECRET_KIND_INVALID"
    assert payload["data"] == {
        "secret_ref": llm_secret.name,
        "source": source,
        "kind": "llm",
    }
```

Add this local helper to the test module:

```python
async def _project_secret(db_session, *, kind: str) -> JoySafeterSecret:
    secret = JoySafeterSecret(
        name=f"{kind}-secret-{uuid.uuid4()}",
        kind=kind,
        provider="openai" if kind == "llm" else None,
        protocol="openai_chat_completions" if kind == "llm" else None,
        data=encrypted_secret_data({"TOKEN": "value", "MODEL": "gpt-5"}),
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)
    return secret
```

- [ ] **Step 3: Run the focused Environment tests and confirm failures**

Run:

```bash
cd backend
uv run pytest tests/test_environment_egress_service_schema.py tests/test_environment_lifecycle_active_sessions.py -q
```

Expected before implementation: extraction symbols are absent, Egress references are not looked up, and existing direct references do not reject LLM Secrets.

- [ ] **Step 4: Implement the typed extractor**

After `EnvironmentConfig`, add:

```python
EnvironmentSecretReferenceSource = Literal["secret_refs", "egress_services"]


class EnvironmentSecretReference(NamedTuple):
    name: str
    source: EnvironmentSecretReferenceSource


def extract_environment_secret_references(
    config: EnvironmentConfig | dict[str, Any] | None,
) -> list[EnvironmentSecretReference]:
    raw = config.model_dump() if isinstance(config, EnvironmentConfig) else config
    if not isinstance(raw, dict):
        return []

    references: list[EnvironmentSecretReference] = []
    seen: set[str] = set()

    def append(value: object, source: EnvironmentSecretReferenceSource) -> None:
        name = str(value).strip() if value is not None else ""
        if not name or name in seen:
            return
        seen.add(name)
        references.append(EnvironmentSecretReference(name, source))

    direct_refs = raw.get("secret_refs")
    if isinstance(direct_refs, list):
        for value in direct_refs:
            append(value, "secret_refs")

    services = raw.get("egress_services")
    if isinstance(services, list):
        for service in services:
            if isinstance(service, dict):
                append(service.get("credential_ref"), "egress_services")

    return references
```

Add required imports: `Any`, `Literal`, and `NamedTuple`.

- [ ] **Step 5: Replace API validation with config-wide validation**

Change the helper signature in `environments.py`:

```python
async def _validate_secret_refs(
    db: AsyncSession,
    config: EnvironmentConfig,
    project_id: Optional[str],
) -> None:
```

Loop over `extract_environment_secret_references(config)`. For each reference:

```python
secret = await secret_svc.get_secret_by_name(reference.name, project_id=project_id)
if secret is None:
    raise InvalidRequestError(
        code="ENVIRONMENT_SECRET_NOT_FOUND",
        message=f"Secret not found: {reference.name}",
        data={"secret_ref": reference.name, "source": reference.source},
        user_action="fix_input",
    )
if secret.kind != SecretKind.GENERIC.value:
    raise InvalidRequestError(
        code="ENVIRONMENT_SECRET_KIND_INVALID",
        message="Environment credentials require a generic Secret",
        data={
            "secret_ref": reference.name,
            "source": reference.source,
            "kind": secret.kind,
        },
        user_action="fix_input",
    )
```

Update create and update calls to pass `req.config`, not `req.config.secret_refs`.

- [ ] **Step 6: Run focused Environment tests**

Run:

```bash
cd backend
uv run pytest \
  tests/test_environment_egress_service_schema.py \
  tests/test_environment_lifecycle_active_sessions.py \
  tests/test_environment_ref_boundary.py -q
```

Expected: PASS; package/image and mount validation remain unchanged.

---

### Task 3: Extend Secret Lifecycle Protection and Network Refresh

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_secret_service.py:74`
- Modify: `backend/app/joysafeter_api/api/v1/secrets.py:1`
- Test: `backend/tests/test_secret_lifecycle_active_dependencies.py`

**Interfaces:**
- Consumes: `extract_environment_secret_references` from Task 2.
- Produces: `SecretService.secret_is_referenced_by_trigger(name: str, project_id: str | None = None) -> str | None` returning the first live Trigger name.
- Existing active-task dependency logic gains Egress references through the shared Environment extractor; Trigger references do not enter active-task scanning.
- Successful Secret update/delete calls `refresh_live_limited_sandbox_network_policies` with `source_type="secret"` and the Secret ID.

- [ ] **Step 1: Write failing lifecycle reference tests**

In `test_secret_lifecycle_active_dependencies.py`, add an Egress Environment reference test:

```python
@pytest.mark.asyncio
async def test_delete_secret_rejects_egress_environment_reference_without_force(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"egress-secret-env-{uuid.uuid4()}",
        description="",
        config={
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": secret.name,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ]
        },
    )
    db_session.add(env)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    payload = await handled_app_error_payload(exc_info.value, status_code=409)
    assert payload["code"] == "SECRET_ENVIRONMENT_REFERENCE"
    assert payload["data"]["environment_name"] == env.name
```

Add an active task whose Agent references that Environment and assert update/force-delete returns `SECRET_ACTIVE_TASK_DEPENDENCY` with source `agent environment_ref`.

Add a Trigger reference test:

```python
trigger = JoySafeterTrigger(
    name=f"secret-trigger-{uuid.uuid4()}",
    type="webhook",
    agent_id=agent.id,
    prompt_template="run",
    secret_ref=secret.name,
    secret_key="TOKEN",
    config={"auth_methods": ["hmac"]},
    filter={},
    last_payload={},
)
```

Ordinary delete must return `SECRET_TRIGGER_REFERENCE` with `trigger_name`; force delete remains allowed when there is no active task.

- [ ] **Step 2: Write failing network refresh tests**

Import `AsyncMock` and the Secret API module. Monkeypatch the imported refresh function:

```python
refresh = AsyncMock(return_value=0)
monkeypatch.setattr(
    "app.joysafeter_api.api.v1.secrets.refresh_live_limited_sandbox_network_policies",
    refresh,
)
```

Create these three exact test cases:

1. Successful update awaits:

```python
refresh.assert_awaited_once_with(
    db_session,
    project_id=None,
    reason="secret.updated",
    source_type="secret",
    source_id=str(secret.id),
)
```

2. Successful ordinary delete awaits the same call with `reason="secret.deleted"`.
3. Successful force delete awaits the same delete call; failed dependency validation leaves `refresh.await_count == 0`.

- [ ] **Step 3: Run the lifecycle tests and confirm failures**

Run:

```bash
cd backend
uv run pytest tests/test_secret_lifecycle_active_dependencies.py -q
```

Expected before implementation: Egress and Trigger references are invisible and Secret mutations never call the network refresh helper.

- [ ] **Step 4: Reuse Environment extraction inside SecretService**

Delete the private `_environment_secret_refs` parser. Import `extract_environment_secret_references` and use:

```python
references = extract_environment_secret_references(config)
if any(_secret_ref_matches(reference.name, name) for reference in references):
```

Apply this in both `secret_is_referenced_by_environment` and `_environment_refs_for_secret`. This automatically extends active-task protection to `egress_services[].credential_ref` without changing task-source labels.

- [ ] **Step 5: Add Trigger reference lookup**

Import `JoySafeterTrigger` and add:

```python
async def secret_is_referenced_by_trigger(
    self,
    name: str,
    project_id: Optional[str] = None,
) -> Optional[str]:
    conditions = [
        JoySafeterTrigger.secret_ref == name,
        JoySafeterTrigger.deleted_at.is_(None),
    ]
    if project_id is not None:
        conditions.append(JoySafeterTrigger.project_id == project_id)
    result = await self.db.execute(
        select(JoySafeterTrigger.name).where(and_(*conditions)).limit(1)
    )
    return result.scalar_one_or_none()
```

Include it in `secret_is_referenced`, after Agent and Environment checks.

- [ ] **Step 6: Protect ordinary delete and refresh successful mutations**

In `secrets.py`, import `refresh_live_limited_sandbox_network_policies`.

After the Environment reference check, add:

```python
trigger_name = await svc.secret_is_referenced_by_trigger(secret.name, project_id=auth_ctx.project_id)
if trigger_name:
    raise _secret_reference_error(
        secret_id=secret_id,
        secret_name=secret.name,
        code="SECRET_TRIGGER_REFERENCE",
        message=f"Secret is referenced by trigger '{trigger_name}'. Use ?force=true to force delete.",
        reference_key="trigger_name",
        reference_value=trigger_name,
    )
```

After a successful update and before returning the response, call:

```python
await refresh_live_limited_sandbox_network_policies(
    db,
    project_id=auth_ctx.project_id,
    reason="secret.updated",
    source_type="secret",
    source_id=str(secret.id),
)
```

After either successful delete branch and before auditing, call the helper with `reason="secret.deleted"` and `source_id=str(secret_id)`.

- [ ] **Step 7: Run focused Secret lifecycle and masking tests**

Run:

```bash
cd backend
uv run pytest \
  tests/test_secret_lifecycle_active_dependencies.py \
  tests/test_credential_masking_default_deny.py \
  tests/test_llm_secret_catalog.py \
  tests/test_agent_environment_ref_validation.py -q
```

Expected: PASS; plaintext masking and LLM Secret behavior remain unchanged.

---

### Task 4: Reject New MCP OAuth Credentials While Preserving Historical Rows

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_vault_service.py:1`
- Modify: `backend/app/joysafeter_api/api/v1/vaults.py:259`
- Test: `backend/tests/test_vault_error_contract.py`

**Interfaces:**
- `VaultService.create_credential` accepts only `credential_type="static_bearer"` and a non-blank token for new rows.
- Unsupported values `mcp_oauth`, `oauth`, and arbitrary strings raise `InvalidRequestError(code="VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED")`.
- Blank static Bearer tokens raise `InvalidRequestError(code="VAULT_CREDENTIAL_TOKEN_REQUIRED")`.
- Read/list/archive/delete/update behavior for existing OAuth rows is unchanged.

- [ ] **Step 1: Add failing parameterized creation tests**

In `test_vault_error_contract.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type", ["mcp_oauth", "oauth", "custom"])
async def test_create_credential_rejects_unsupported_type(db_session, credential_type):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name="Unsupported",
                credential_type=credential_type,
                mcp_server_url="https://mcp.example.com",
                token_value="token",
            ),
            _request(),
            vault.id,
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED"
    assert payload["data"] == {"credential_type": credential_type, "supported": ["static_bearer"]}
```

Add this blank-token case and verify no credential row was inserted:

```python
@pytest.mark.asyncio
async def test_create_credential_rejects_blank_static_bearer_token(db_session):
    vault = JoySafeterVault(name=f"vault-{uuid.uuid4()}", description="")
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    with pytest.raises(AppError) as exc_info:
        await create_credential(
            CreateCredentialRequest(
                name="Blank token",
                credential_type="static_bearer",
                mcp_server_url="https://mcp.example.com",
                token_value="   ",
            ),
            _request(),
            vault.id,
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "VAULT_CREDENTIAL_TOKEN_REQUIRED"
    assert payload["data"] == {"credential_type": "static_bearer"}
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterVaultCredential)
            .where(JoySafeterVaultCredential.vault_id == vault.id)
        )
    ).scalar_one()
    assert count == 0
```

- [ ] **Step 2: Add historical-row compatibility coverage**

Create an OAuth row directly through the ORM to represent pre-phase data, then call existing API/service functions to prove it can be fetched, archived, and deleted. Do not use `create_credential` to manufacture historical data after creation is restricted:

```python
historical = JoySafeterVaultCredential(
    vault_id=vault.id,
    name="Historical OAuth",
    credential_type="mcp_oauth",
    mcp_server_url="https://historical.example.com",
    token_value=encrypted_credential_value("historical-token"),
    oauth_config=None,
)
db_session.add(historical)
await db_session.commit()
await db_session.refresh(historical)
```

Assert `get_credential` returns a redacted token, `archive_credential` succeeds, and `delete_credential` succeeds after restoring `archived_at` only if the existing delete path requires a live row.

- [ ] **Step 3: Run Vault tests and confirm unsupported creation currently passes**

Run:

```bash
cd backend
uv run pytest tests/test_vault_error_contract.py tests/test_credential_masking_default_deny.py -q
```

Expected before implementation: unsupported types are stored.

- [ ] **Step 4: Enforce creation policy in VaultService**

Import `CredentialType` and `InvalidRequestError`. At the start of `create_credential`, after confirming the parent Vault exists and is mutable, normalize the type and token:

```python
normalized_type = str(credential_type or "").strip().lower()
if normalized_type != CredentialType.STATIC_BEARER.value:
    raise InvalidRequestError(
        code="VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED",
        message=f"Unsupported credential type: {credential_type}",
        data={
            "credential_type": credential_type,
            "supported": [CredentialType.STATIC_BEARER.value],
        },
        user_action="fix_input",
    )
normalized_token = token_value.strip()
if not normalized_token:
    raise InvalidRequestError(
        code="VAULT_CREDENTIAL_TOKEN_REQUIRED",
        message="A Bearer token is required",
        data={"credential_type": CredentialType.STATIC_BEARER.value},
        user_action="fix_input",
    )
```

Persist `credential_type=normalized_type`, `token_value=self._encrypt_token_value(normalized_token)`, and `oauth_config=None`. This prevents the new static path from storing unused OAuth configuration.

- [ ] **Step 5: Keep the API path thin and success-only side effects**

No route or response shape changes are required. Confirm `create_credential` in `vaults.py` lets the structured `InvalidRequestError` propagate and reaches audit/network refresh only after `svc.create_credential` succeeds.

Update the encryption compatibility test that currently calls `svc.create_credential(... credential_type="mcp_oauth")` to insert a historical ORM row directly while using the existing cipher helper for encrypted fields.

- [ ] **Step 6: Run focused Vault tests**

Run:

```bash
cd backend
uv run pytest \
  tests/test_vault_error_contract.py \
  tests/test_credential_masking_default_deny.py \
  tests/test_secret_vault_name_soft_delete_index.py -q
```

Expected: PASS; new OAuth creation is blocked and historical-row operations remain compatible.

---

### Task 5: Add a Paginated Service Credential Selector and Fix Trigger Submission

**Files:**
- Create: `frontend/hooks/managed/use-service-credentials.ts`
- Create: `frontend/hooks/managed/use-service-credentials.test.tsx`
- Create: `frontend/components/managed/shared/service-credential-select.tsx`
- Create: `frontend/components/managed/shared/service-credential-select.test.tsx`
- Modify: `frontend/components/managed/shared/index.ts`
- Modify: `frontend/components/managed/triggers/create-trigger-dialog.tsx:1`
- Modify: `frontend/components/managed/triggers/create-trigger-dialog.test.tsx`

**Interfaces:**
- Produces: `serviceCredentialsQueryKey(scopeKey: string) -> readonly ["service-credentials", string]`.
- Produces: `fetchAllServiceCredentials(scope: ManagedRequestScope) -> Promise<Secret[]>`.
- Produces: `useServiceCredentials({ enabled?: boolean }) -> UseQueryResult<Secret[]>`.
- Produces: `ServiceCredentialSelect({ value, onChange, credentials, loading, disabled, ariaLabel })` whose wire value is the Secret resource `name`, never a field name.
- Trigger uses `Secret.keys`; it never fetches `secret_data`.

- [ ] **Step 1: Write the failing paginated query test**

Model `use-service-credentials.test.tsx` after `use-compatible-secrets.test.tsx`. Mock two pages:

```typescript
managedGetMock
  .mockResolvedValueOnce({
    data: [genericSecret('service-a', SECRET_ID_A, ['TOKEN'])],
    has_more: true,
    last_id: SECRET_ID_A,
  })
  .mockResolvedValueOnce({
    data: [genericSecret('service-b', SECRET_ID_B, ['API_KEY'])],
    has_more: false,
    last_id: SECRET_ID_B,
  })
```

Assert the first request is `/secrets?limit=100&kind=generic`, the second includes `after_id=<SECRET_ID_A>`, and the result preserves both parsed Secret IDs and `keys` arrays. Add this invalid-cursor assertion:

```typescript
managedGetMock.mockResolvedValue({ data: [], has_more: true, last_id: SECRET_ID_A })
await expect(fetchAllServiceCredentials(scope)).rejects.toThrow(
  'Service Credential pagination returned an invalid cursor',
)
expect(managedGetMock).toHaveBeenCalledTimes(2)
```

- [ ] **Step 2: Implement the Generic Secret query**

Create `use-service-credentials.ts`:

```typescript
'use client'

import { useQuery } from '@tanstack/react-query'

import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseSecretListResponse } from '@/lib/managed/secret-response-parsers'
import type { Secret } from '@/types/managed'

interface SecretPage {
  data: unknown[]
  has_more: boolean
  last_id?: string | null
}

const PAGE_SIZE = 100

export function serviceCredentialsQueryKey(scopeKey: string) {
  return ['service-credentials', scopeKey] as const
}

export async function fetchAllServiceCredentials(scope: ManagedRequestScope): Promise<Secret[]> {
  const credentials: Secret[] = []
  let afterId: string | undefined
  for (;;) {
    const page = await managedGet<SecretPage>(
      apiCollectionPath('secrets', { limit: PAGE_SIZE, kind: 'generic', after_id: afterId }),
      managedRequestOptions(scope),
    )
    credentials.push(...parseSecretListResponse(page.data))
    if (!page.has_more) return credentials
    if (!page.last_id || page.last_id === afterId) {
      throw new Error('Service Credential pagination returned an invalid cursor')
    }
    afterId = page.last_id
  }
}

export function useServiceCredentials({ enabled = true }: { enabled?: boolean } = {}) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: serviceCredentialsQueryKey(scope.key),
    queryFn: () => fetchAllServiceCredentials(scope),
    enabled: enabled && hasManagedRequestScope(scope),
    staleTime: 30_000,
  })
}
```

- [ ] **Step 3: Write and implement the resource selector**

The component test must prove option values are Secret names and that an unavailable current value remains visible with an unavailable label.

Implement props:

```typescript
interface ServiceCredentialSelectProps {
  value: string
  onChange: (value: string) => void
  credentials: Secret[]
  loading?: boolean
  disabled?: boolean
  ariaLabel: string
}
```

Render each option as:

```tsx
<SelectItem key={credential.id} value={credential.name}>
  <span>{credential.name}</span>
  <span className="text-xs text-muted-foreground">
    {t('managed.triggers.credentialFieldCount', { count: credential.keys?.length ?? 0 })}
  </span>
</SelectItem>
```

If `value` is non-empty and no credential has that name, render one `SelectItem value={value}` labeled with `managed.triggers.serviceCredentialUnavailable`. Export the component from `shared/index.ts`.

- [ ] **Step 4: Add failing Trigger dialog tests**

Extend the API mock in `create-trigger-dialog.test.tsx` so `/secrets?` returns a cursor response with:

```typescript
{
  data: [
    {
      id: 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
      name: 'hook-prod',
      kind: 'generic',
      provider: null,
      protocol: null,
      model: null,
      compatible_engine_ids: [],
      is_default: false,
      keys: ['WEBHOOK_SECRET', 'ALT_TOKEN'],
      created_at: '2030-01-01T00:00:00Z',
      updated_at: '2030-01-01T00:00:00Z',
    },
  ],
  has_more: false,
  last_id: 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
}
```

Create the following five test cases with the stated inputs and assertions:

1. Select `hook-prod`, select `ALT_TOKEN`, save, and assert the mutation body contains `secret_ref: 'hook-prod'` and `secret_key: 'ALT_TOKEN'`.
2. Edit a historical Trigger with `secret_ref='deleted-hook'`; because it is absent from results, assert the unavailable message is visible and Save is disabled.
3. Edit a Trigger with `secret_ref='hook-prod'` and `secret_key='REMOVED_FIELD'`; assert the missing-field message is visible and Save is disabled.
4. Return a Secret with `keys: []`; assert the empty-field message is visible and Save is disabled.
5. Reject the Secret query; assert the load-failed message is visible and Save is disabled.

- [ ] **Step 5: Replace the Trigger Webhook controls**

In `create-trigger-dialog.tsx`:

- Replace `SecretKeySelect` import with `ServiceCredentialSelect`.
- Call `useServiceCredentials({ enabled: open && type === 'webhook' })`.
- Derive `serviceCredentials`, `selectedCredential`, `credentialFields`, `missingCredential`, and `missingCredentialField` with `useMemo`.
- When the resource changes, reset the field to `WEBHOOK_SECRET` if present, otherwise the first available key, otherwise `''`.
- Do not auto-repair an edit form merely because query data arrives; historical missing values must remain visible and invalid until the user changes them.

Use this submit condition for Webhook forms:

```typescript
const webhookCredentialValid =
  !serviceCredentialsQuery.isLoading &&
  !serviceCredentialsQuery.isError &&
  Boolean(selectedCredential) &&
  Boolean(secretKey) &&
  credentialFields.includes(secretKey)
```

Require `webhookCredentialValid`, at least one auth method, and valid filter rows in `canSubmit`.

Replace the current two controls with:

```tsx
<ServiceCredentialSelect
  value={secretRef}
  onChange={handleServiceCredentialChange}
  credentials={serviceCredentials}
  loading={serviceCredentialsQuery.isLoading}
  ariaLabel={t('managed.triggers.serviceCredential')}
/>
```

and a Radix `Select` whose options come only from `credentialFields`, with `aria-label={t('managed.triggers.credentialField')}`. Render explicit inline messages for load failure, unavailable resource, no fields, and unavailable historical field.

- [ ] **Step 6: Run focused frontend tests**

Run:

```bash
cd frontend
bun run test -- \
  hooks/managed/use-service-credentials.test.tsx \
  components/managed/shared/service-credential-select.test.tsx \
  components/managed/triggers/create-trigger-dialog.test.tsx
```

Expected: PASS; mutation payloads carry Secret resource names and valid field names only.

---

### Task 6: Simplify Vault Credential Creation to Static Bearer

**Files:**
- Modify: `frontend/app/managed/vaults/components/create-credential-dialog.tsx:38`
- Modify: `frontend/app/managed/vaults/components/create-credential-dialog.test.tsx`

**Interfaces:**
- Creation payload is always `{ credential_type: "static_bearer", mcp_server_url: string, token_value: string, name?: string }`.
- The form always requires a non-blank token and never displays OAuth controls or OAuth promises.
- Existing scope-staleness and query invalidation guards remain unchanged.

- [ ] **Step 1: Rewrite failing tests around the intended payload**

In these existing tests, fill `managed.vaults.cred.tokenPlaceholder` before clicking submit:

- `does not submit credential draft data to a different vault after vault id changes`
- `does not invalidate credentials from a create completion after vault id changes`
- `does not invalidate credentials from a create completion after the dialog unmounts`

Add this explicit contract test:

```typescript
it('creates only a static bearer credential with a required token', async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(renderDialog('vault-a', queryClient))

  expect(view.queryByText('OAuth')).toBeNull()
  const submit = view.getByText('managed.vaults.cred.add').closest('button')!
  expect(submit.disabled).toBe(true)

  fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
    target: { value: 'https://mcp-a.example.com' },
  })
  fireEvent.input(view.getByPlaceholderText('managed.vaults.cred.tokenPlaceholder'), {
    target: { value: ' bearer-token ' },
  })
  fireEvent.click(submit)

  expect(managedPostMock).toHaveBeenCalledWith(
    '/vaults/vault-a/credentials',
    {
      name: undefined,
      credential_type: 'static_bearer',
      mcp_server_url: 'https://mcp-a.example.com',
      token_value: 'bearer-token',
    },
    managedOptions(),
  )
})
```

Change the existing stale-completion expectation from `mcp_oauth` to `static_bearer` and include the token.

- [ ] **Step 2: Run the dialog tests and confirm current OAuth behavior fails the new assertions**

Run:

```bash
cd frontend
bun run test -- app/managed/vaults/components/create-credential-dialog.test.tsx
```

- [ ] **Step 3: Remove the OAuth branch**

In `create-credential-dialog.tsx`:

- Delete `CredType`, `credentialType` state, `setCredentialType`, `isOAuth`, and the two-button type selector.
- Reset only `name`, `mcpServerUrl`, and `tokenValue`.
- Require both trimmed URL and token before mutation.
- Submit fixed `credential_type: 'static_bearer'` and trimmed URL/token values.
- Always render the password input.
- Use `managed.vaults.cred.add` / `adding` labels rather than `connect` / `connecting`.

The mutation variable type becomes:

```typescript
payload: {
  name?: string
  credential_type: 'static_bearer'
  mcp_server_url: string
  token_value: string
}
```

- [ ] **Step 4: Run the focused Vault dialog test**

Run:

```bash
cd frontend
bun run test -- app/managed/vaults/components/create-credential-dialog.test.tsx
```

Expected: PASS; scope-change and unmount guards continue to pass.

---

### Task 7: Normalize User-Facing Credential Terminology

**Files:**
- Create: `frontend/lib/i18n/credential-terminology.test.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/app/managed/quickstart/page.tsx:1488`
- Modify: `frontend/app/managed/sessions/components/create-session-dialog.tsx:689`

**Interfaces:**
- Internal i18n key names, routes, query parameters, API fields, and TypeScript types remain unchanged.
- User vocabulary is fixed to:
  - Project Access Token / 项目访问令牌
  - Model Connection / 模型连接
  - Service Credential / 服务凭据
  - MCP Credential Set / MCP 凭据组
  - Credential Field / 凭据字段
  - Authentication Method / 认证方式
  - Connections & Credentials / 连接与凭据

- [ ] **Step 1: Add a failing bilingual terminology contract**

Create `credential-terminology.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import en from './locales/en'
import zh from './locales/zh'

describe('credential domain terminology', () => {
  it('uses the normalized English vocabulary', () => {
    const text = en.translation
    expect(text.nav.secrets).toBe('Connections & Credentials')
    expect(text.nav.vaults).toBe('MCP Credential Sets')
    expect(text.nav.apiKeys).toBe('Project Access Tokens')
    expect(text.managed.secrets.title).toBe('Connections & Credentials')
    expect(text.managed.llm.modelConfiguration).toBe('Model Connection')
    expect(text.managed.llm.genericSecret).toBe('Service Credential')
    expect(text.managed.vaults.title).toBe('MCP Credential Sets')
    expect(text.managed.apiKeys.title).toBe('Project Access Tokens')
    expect(text.managed.triggers.serviceCredential).toBe('Service Credential')
    expect(text.managed.triggers.credentialField).toBe('Credential Field')
  })

  it('uses the normalized Chinese vocabulary', () => {
    const text = zh.translation
    expect(text.nav.secrets).toBe('连接与凭据')
    expect(text.nav.vaults).toBe('MCP 凭据组')
    expect(text.nav.apiKeys).toBe('项目访问令牌')
    expect(text.managed.secrets.title).toBe('连接与凭据')
    expect(text.managed.llm.modelConfiguration).toBe('模型连接')
    expect(text.managed.llm.genericSecret).toBe('服务凭据')
    expect(text.managed.vaults.title).toBe('MCP 凭据组')
    expect(text.managed.apiKeys.title).toBe('项目访问令牌')
    expect(text.managed.triggers.serviceCredential).toBe('服务凭据')
    expect(text.managed.triggers.credentialField).toBe('凭据字段')
  })
})
```

- [ ] **Step 2: Pin the exact navigation and page copy**

Update these values while keeping their key paths:

| Key | English | 中文 |
|---|---|---|
| `nav.secrets` | `Connections & Credentials` | `连接与凭据` |
| `nav.vaults` | `MCP Credential Sets` | `MCP 凭据组` |
| `nav.apiKeys` | `Project Access Tokens` | `项目访问令牌` |
| `managed.secrets.title` | `Connections & Credentials` | `连接与凭据` |
| `managed.secrets.subtitle` | `Manage model connections and service credentials for this project.` | `管理当前项目的模型连接与服务凭据。` |
| `managed.secrets.new` | `New Connection or Credential` | `新建连接或凭据` |
| `managed.secrets.dataLabel` | `Credential Fields` | `凭据字段` |
| `managed.secrets.backToList` | `Back to Connections & Credentials` | `返回连接与凭据` |
| `managed.llm.modelConfiguration` | `Model Connection` | `模型连接` |
| `managed.llm.genericSecret` | `Service Credential` | `服务凭据` |
| `managed.vaults.title` | `MCP Credential Sets` | `MCP 凭据组` |
| `managed.vaults.new` | `New MCP Credential Set` | `新建 MCP 凭据组` |
| `managed.vaults.credentials` | `MCP Credentials` | `MCP 凭据` |
| `managed.vaults.addCredential` | `Add MCP Bearer Credential` | `添加 MCP Bearer 凭据` |
| `managed.apiKeys.title` | `Project Access Tokens` | `项目访问令牌` |
| `managed.apiKeys.subtitle` | `Manage tokens used by external programs to call this project.` | `管理外部程序调用当前项目所使用的令牌。` |
| `managed.apiKeys.create` | `Create Token` | `创建令牌` |
| `managed.apiKeys.revokeTitle` | `Revoke Project Access Token` | `撤销项目访问令牌` |

Also set these exact values without renaming keys:

| Key | English | 中文 |
|---|---|---|
| `managed.secrets.empty` | `No model connections or service credentials yet.` | `暂无模型连接或服务凭据。` |
| `managed.secrets.deleteTitle` | `Delete Connection or Credential` | `删除连接或凭据` |
| `managed.search.secrets` | `Search connections and credentials by name or ID` | `按名称或 ID 搜索连接与凭据` |
| `managed.vaults.empty` | `No MCP credential sets yet.` | `暂无 MCP 凭据组。` |
| `managed.vaults.archiveVault` | `Archive MCP Credential Set` | `归档 MCP 凭据组` |
| `managed.vaults.archiveTitle` | `Archive MCP Credential Set` | `归档 MCP 凭据组` |
| `managed.vaults.deleteTitle` | `Delete MCP Credential Set` | `删除 MCP 凭据组` |
| `managed.vaults.backToVaults` | `Back to MCP Credential Sets` | `返回 MCP 凭据组` |
| `managed.search.vaults` | `Search MCP credential sets by name, ID, or status` | `按名称、ID 或状态搜索 MCP 凭据组` |
| `managed.apiKeys.empty` | `No project access tokens yet.` | `暂无项目访问令牌。` |
| `managed.apiKeys.revoke` | `Revoke Token` | `撤销令牌` |
| `managed.search.apiKeys` | `Search project access tokens by name, prefix, or role` | `按名称、前缀或角色搜索项目访问令牌` |

- [ ] **Step 3: Add exact Trigger and Environment field copy**

Add/update these Trigger keys:

| Key | English | 中文 |
|---|---|---|
| `managed.triggers.serviceCredential` | `Service Credential` | `服务凭据` |
| `managed.triggers.serviceCredentialPlaceholder` | `Select a service credential` | `选择服务凭据` |
| `managed.triggers.serviceCredentialUnavailable` | `This service credential no longer exists. Select another one.` | `该服务凭据已不存在，请重新选择。` |
| `managed.triggers.serviceCredentialLoadFailed` | `Service credentials could not be loaded. Retry before saving.` | `服务凭据加载失败，请重试后再保存。` |
| `managed.triggers.credentialField` | `Credential Field` | `凭据字段` |
| `managed.triggers.credentialFieldPlaceholder` | `Select a credential field` | `选择凭据字段` |
| `managed.triggers.credentialFieldUnavailable` | `This credential field no longer exists. Select another one.` | `该凭据字段已不存在，请重新选择。` |
| `managed.triggers.credentialFieldEmpty` | `This service credential has no fields.` | `该服务凭据没有可用字段。` |
| `managed.triggers.credentialFieldCount` | `{{count}} fields` | `{{count}} 个字段` |
| `managed.triggers.authMethods` | `Authentication Methods` | `认证方式` |

Update `managed.environments.egressCredential` to `Service Credential / 服务凭据`, `egressSecretKey` to `Credential Field / 凭据字段`, and their tooltip/hint text to use the same nouns.

Also set:

| Key | English | 中文 |
|---|---|---|
| `managed.environments.egressAuthType` | `Authentication Method` | `认证方式` |
| `managed.environments.egressAuthHint` | `How the platform uses a credential field to authenticate the outbound request.` | `平台如何使用凭据字段为出站请求生成认证信息。` |
| `managed.environments.egressSelectCredential` | `Select service credential` | `选择服务凭据` |
| `managed.environments.egressSearchCredential` | `Search service credentials` | `搜索服务凭据` |
| `managed.environments.egressNoCredentialFound` | `No matching service credentials` | `没有匹配的服务凭据` |
| `managed.environments.egressSelectSecretKey` | `Select credential field` | `选择凭据字段` |

- [ ] **Step 4: Normalize Session and Quickstart MCP wording**

Update Session creation values:

| Key | English | 中文 |
|---|---|---|
| `managed.sessions.create.vaults` | `MCP Credential Sets` | `MCP 凭据组` |
| `managed.sessions.create.manageVaults` | `Manage MCP Credential Sets` | `管理 MCP 凭据组` |
| `managed.sessions.create.createVault` | `Create MCP credential set…` | `新建 MCP 凭据组…` |
| `managed.sessions.create.searchVault` | `Search MCP credential sets by name or ID` | `按名称或 ID 搜索 MCP 凭据组` |
| `managed.sessions.goToVault` | `Go to MCP Credential Set` | `前往 MCP 凭据组` |

Update Quickstart model text from “model configuration / 模型配置” to “Model Connection / 模型连接”, and Vault text from “Vault / 凭证库” to “MCP Credential Set / MCP 凭据组”. Preserve the already-modified Step 1/Step 2 guidance around `engineHint` and `secretHint`; change only the credential nouns inside those current strings.

Replace the hard-coded Quickstart editor label with a translated key:

```typescript
const label =
  currentStep === 4
    ? t('managed.quickstart.resourceKindEnvironment')
    : currentStep === 5
      ? t('managed.quickstart.resourceKindMcpCredentialSet')
      : t('managed.quickstart.resourceKindAgent')
```

Add English values `Environment`, `MCP Credential Set`, `Agent` and Chinese values `环境`, `MCP 凭据组`, `智能体`.

Change the Session advanced-summary fallback literal to `运行环境、MCP 凭据组、文件资源、Memory、Git` so the fallback matches the translated value.

- [ ] **Step 5: Normalize the Vault creation dialog copy**

Set:

| Key | English | 中文 |
|---|---|---|
| `managed.vaults.cred.createTitle` | `Add MCP Bearer Credential` | `添加 MCP Bearer 凭据` |
| `managed.vaults.cred.createDescription` | `Store a Bearer token for one MCP server in this credential set.` | `在当前 MCP 凭据组中保存一个 MCP Server 的 Bearer Token。` |
| `managed.vaults.cred.token` | `Bearer Token` | `Bearer Token` |
| `managed.vaults.cred.tokenPlaceholder` | `Enter Bearer token` | `输入 Bearer Token` |
| `managed.vaults.cred.adding` | `Adding…` | `添加中…` |
| `managed.vaults.cred.add` | `Add Credential` | `添加凭据` |

Remove or leave unused the old `type`, `connect`, and `connecting` keys only if no production component references them; key removal is optional, but their values must not be presented by this workflow.

- [ ] **Step 6: Run terminology and affected UI tests**

Run:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/triggers/create-trigger-dialog.test.tsx \
  app/managed/vaults/components/create-credential-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx \
  hooks/managed/use-quickstart-chat.test.tsx
```

Expected: PASS; current unrelated Quickstart guidance edits remain present.

---

### Task 8: Full Regression and Compatibility Verification

**Files:**
- Verify only; make no scope-expanding refactors.

**Interfaces:**
- Confirms no schema migration, route rename, JSON-field rename, plaintext exposure, or OAuth runtime implementation entered the phase.

- [ ] **Step 1: Run the complete credential-focused backend suite**

Run:

```bash
cd backend
uv run pytest \
  tests/test_trigger_http_e2e_contract.py \
  tests/test_trigger_http_error_contract.py \
  tests/test_trigger_update_validation.py \
  tests/test_trigger_webhook_route_contract.py \
  tests/test_webhook_sample_curl.py \
  tests/test_environment_egress_service_schema.py \
  tests/test_environment_lifecycle_active_sessions.py \
  tests/test_environment_ref_boundary.py \
  tests/test_secret_lifecycle_active_dependencies.py \
  tests/test_credential_masking_default_deny.py \
  tests/test_llm_secret_catalog.py \
  tests/test_agent_environment_ref_validation.py \
  tests/test_vault_error_contract.py \
  tests/test_secret_vault_name_soft_delete_index.py \
  tests/test_api_key_creator_access.py \
  tests/test_api_key_capability_cap.py -q
```

Expected: all pass.

- [ ] **Step 2: Run the complete affected frontend suite**

Run:

```bash
cd frontend
bun run test -- \
  hooks/managed/use-service-credentials.test.tsx \
  components/managed/shared/service-credential-select.test.tsx \
  components/managed/triggers/create-trigger-dialog.test.tsx \
  app/managed/vaults/components/create-credential-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx \
  hooks/managed/use-compatible-secrets.test.tsx \
  hooks/managed/use-quickstart-chat.test.tsx \
  lib/managed/secret-response-parsers.test.ts \
  lib/managed/vault-response-parsers.test.ts \
  lib/i18n/credential-terminology.test.ts
```

Expected: all pass.

- [ ] **Step 3: Run static checks**

Run:

```bash
cd frontend
bun run type-check
bun run lint
```

Then from the repository root:

```bash
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 4: Verify compatibility boundaries by inspection**

Run:

```bash
git diff --name-only
test -z "$(git diff --name-only -- backend/alembic)"
! rg -n "secret_data" frontend/hooks/managed/use-service-credentials.ts frontend/components/managed/shared/service-credential-select.tsx frontend/components/managed/triggers/create-trigger-dialog.tsx
! rg -n "mcp_oauth|oauth" frontend/app/managed/vaults/components/create-credential-dialog.tsx
```

Expected:

- No Alembic version file is added or changed for this phase.
- The new selector path contains no `secret_data` access.
- The create-credential dialog contains no OAuth branch.
- Existing route paths and wire field names remain unchanged.

- [ ] **Step 5: Review the final diff against the design acceptance criteria**

Confirm each statement with a test or changed call site:

1. Webhook Trigger `secret_ref` is a Generic Secret resource name.
2. Webhook `secret_key` exists in that resource before persistence.
3. Environment direct and Egress references share extraction, existence, kind, and lifecycle rules.
4. Ordinary Secret deletion is blocked by Agent, Environment, Egress, and Trigger references.
5. Secret update and both delete modes refresh live limited-network sandbox policies.
6. New Vault Credential creation accepts only non-empty static Bearer tokens.
7. Historical OAuth rows retain read/archive/delete compatibility.
8. Navigation and credential workflows use the approved bilingual vocabulary.
9. Database schema, public routes, and major JSON contracts are unchanged.
