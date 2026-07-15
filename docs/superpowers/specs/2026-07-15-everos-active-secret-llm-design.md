# EverOS Active Secret LLM Design

## Context

JoySafeter already lets each project manage multiple model secrets in the
managed secrets UI. A user can create secrets such as A, B, and C and mark one
as the default/current secret. Agent execution already resolves user secrets
through `SecretService` and injects the selected credential into the runtime.

EverOS currently builds its LLM client from process-level configuration:
`EVEROS_LLM__MODEL`, `EVEROS_LLM__API_KEY`, and `EVEROS_LLM__BASE_URL`. That
makes EverOS behave like it has its own model configuration even though the
product model expects the user's selected JoySafeter secret to be the source of
truth.

## Goal

When a user selects secret A, B, or C in the JoySafeter secrets UI, JoySafeter
agent execution and EverOS LLM-backed memory work both use that same selected
secret.

The first implementation focuses on EverOS LLM credentials. Embedding and
rerank remain independently configured for now unless a later design extends
the same active-secret model to those capabilities.

## Non-Goals

- Do not redesign the whole secrets UI.
- Do not add dynamic embedding or rerank credential resolution in this change.
- Do not remove `EVEROS_LLM__*`; keep it as a fallback for local development
  and deployments that have not configured project secrets yet.
- Do not add Anthropic-native EverOS LLM support in the first version.

## Terminology

- **Active secret**: the project-scoped JoySafeter secret with `is_default=true`.
  This is the user's current model credential selection.
- **EverOS LLM credential**: the model, API key, and base URL used by EverOS
  when it calls an LLM for boundary detection, extraction, reflection, and
  agentic search.
- **OpenAI-compatible secret**: a secret containing `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, and `OPENAI_MODEL`, or equivalent generic keys supported
  by the resolver.

## Proposed Behavior

For every EverOS operation that needs an LLM and has a `project_id`, resolve the
LLM credential in this order:

1. Load the active JoySafeter secret for that `project_id`.
2. If the active secret is OpenAI-compatible, build/use an EverOS LLM client
   from that secret.
3. If there is no active secret, fall back to existing `EVEROS_LLM__*`
   settings.
4. If there is an active secret but it is not OpenAI-compatible, return a clear
   configuration error instead of silently falling back to another key.

The explicit error on incompatible active secrets is intentional. If the user
selected B, EverOS must not quietly use A or a server `.env` key.

## Data Flow

```text
Secrets UI
  user marks A/B/C as default
        |
        v
joysafeter_secrets.is_default = true for project_id
        |
        +--> JoySafeter agent runtime resolves active/project secret
        |
        +--> EverOS request includes project_id
                  |
                  v
             EverOS LLM resolver loads active project secret
                  |
                  v
             per-project OpenAI-compatible LLM client
```

## Backend Design

Add a small JoySafeter-side credential resolver that can return an EverOS LLM
credential for a project:

```text
resolve_project_llm_credential(project_id) -> model, api_key, base_url, secret_id, updated_at
```

The resolver should:

- Use `SecretService.get_default_secret(project_id=...)`.
- Decrypt with `SecretService.get_secret_data(...)`.
- Accept OpenAI-compatible keys:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
- Optionally accept generic fallbacks for imported/custom secrets:
  - `API_KEY`
  - `BASE_URL`
  - `MODEL`
- Reject Anthropic-only secrets for EverOS LLM until an Anthropic EverOS adapter
  exists.

Because EverOS lives in the same backend package but runs as a separate service
container/process, the implementation should avoid coupling EverOS to browser
auth. The EverOS route already receives `project_id`; the resolver can use the
backend database directly in the EverOS process if database settings are
available there. If database access is not available in a deployment, keep the
existing `EVEROS_LLM__*` fallback path.

## EverOS Client Lifecycle

Replace the current single process-wide LLM singleton as the only path with a
project-aware resolver:

```text
get_project_llm_client(project_id) -> LLMClient
```

Cache clients by:

```text
(project_id, secret_id, secret_updated_at)
```

This makes switching from A to B invalidate naturally because the active secret
id changes. Updating A invalidates naturally because `updated_at` changes.

Existing call sites that do not know a project can keep using the current
settings-based fallback. Call sites handling project-scoped memory operations
should use the project-aware client.

## Request Scope

EverOS memory APIs already carry `project_id` for JoySafeter usage. LLM-backed
operations must thread that `project_id` into the LLM resolver instead of
calling the global `get_llm_client()` directly.

Expected affected areas include:

- `memorize` service and extraction pipelines
- OME/cascade strategies that call LLM extractors
- agentic search paths that call an LLM
- knowledge extraction if it is project-scoped and LLM-backed

If an offline background job processes records for a project, it must derive
the project id from the record or memory root path before resolving the client.

## Error Handling

- No active secret and no `EVEROS_LLM__*`: return the existing not-configured
  error.
- Active secret exists but lacks OpenAI-compatible fields: return a clear
  error telling the user to choose an OpenAI-compatible secret for EverOS.
- Active secret decrypt fails: fail the operation and log a redacted error.
- Provider request fails: preserve existing LLM provider error behavior.

Never log API keys or decrypted secret values.

## UI Impact

The existing default/current secret action can remain the source of truth.

The UI should eventually make this clearer by labeling the default secret as
the shared model credential for JoySafeter execution and EverOS memory. If an
Anthropic-only secret is selected, the UI can warn that EverOS LLM requires an
OpenAI-compatible secret until Anthropic support is added.

## Tests

Add focused backend tests for:

- Resolving an OpenAI-compatible active secret.
- Switching active secret from A to B changes the resolved credential.
- Updating an active secret changes the cache key.
- Anthropic-only active secret returns an explicit incompatibility error.
- Missing active secret falls back to `EVEROS_LLM__*`.
- No active secret and no fallback returns not-configured.

Add service-level tests for at least one EverOS LLM-backed path to prove the
project id is threaded into the resolver.

## Rollout

Keep `EVEROS_LLM__*` in `backend/env.example` as fallback/development config,
but document that JoySafeter active project secrets are the preferred runtime
source.

No migration is required because the current secrets table already has
`is_default`, provider, protocol, and encrypted data fields.
