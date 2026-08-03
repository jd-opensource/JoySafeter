# Deploy topology cleanup & egress config reconciliation

Date: 2026-08-03
Branch: joysafeter-v2

## Goal

Make the deploy configuration cleanly and consistently express the intended
two-plane topology:

1. **Sandbox plane** — the sandbox and its egress dependencies come in **two
   deployment types**:
   - **Docker** (`JOYSAFETER_SANDBOX_PROVIDER=docker`): orchestrator-rs +
     Docker Envoy + Go egress-controller, driving per-sandbox containers via the
     host Docker socket.
   - **Kubernetes** (`JOYSAFETER_SANDBOX_PROVIDER=k8s`): orchestrator-rs +
     egress Envoy + egress-controller in-cluster, driving sandbox Pods and
     NetworkPolicies via the Kubernetes API.
2. **Business services** — Frontend, Backend API, Worker, PostgreSQL, Redis
   (+ Skillspector): run by the **company production environment** in prod;
   run locally via **docker-compose only for testing**.

The Rust providers `daytona` and `e2b` remain in code (out of scope for
deletion) but are documented as experimental remote providers; only `docker`
and `k8s` are supported deployment types.

## Decisions (confirmed with user)

- **Scope**: topology **and** egress control-plane are both reworked (incl.
  the unfinished `mock-upstream` change and the `.env`/compose egress-default
  and mTLS drift).
- **K8s production overlay**: `overlays/sandbox-plane` becomes the single
  canonical production overlay. The old full-stack `overlays/production`
  (business services in-cluster, external DB/Redis) matches no shape in the
  goal — `overlays/local` already covers full-stack in-cluster testing — and is
  wired into zero automation, so it is removed.
- **Egress defaults**: `deploy/.env.example` is aligned to the unified control
  plane (`controller` / `postgres` / authority `true`) to match the
  `docker-compose.yml` x-anchor defaults and `EGRESS_MIGRATION.md`. The legacy
  `filesystem` / `file` path survives only as a documented rollback comment.

## Overlay taxonomy (after)

| Overlay | Shape | Use |
|---|---|---|
| `local` | full stack in-cluster incl. PG/Redis | local k3s testing |
| `sandbox-plane` | sandbox plane only; PG/Redis/business external | **production** |
| `egress-tls-smoke` | replica/PDB/HPA patches | egress TLS smoke test |

## Compose profile model (after)

| Profile | Services | Meaning |
|---|---|---|
| _(default)_ | postgres, skillspector, api, worker, frontend | business local-test stack |
| `local-redis` | redis | local Redis (prod uses company Redis) |
| `sandbox` | orchestrator-rs, joysafeter-envoy, joysafeter-egress-controller | Docker sandbox plane + egress deps |
| `init` | db-init | one-shot migrations |

`docker compose up` = business-only local test. Full local stack =
`--profile local-redis --profile sandbox up`. The `rust-orchestrator` profile
is renamed to `sandbox` (describes the role, not the impl) everywhere it is
referenced.

## File-by-file change set

### Phase 1 — env consistency
- `deploy/.env.example`: add two-plane topology header; set
  `JOYSAFETER_ENVOY_XDS_MODE=controller`,
  `JOYSAFETER_EGRESS_CONTROLLER_SOURCE=postgres`,
  `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true`; set docker-bridge mTLS
  (`JOYSAFETER_EGRESS_XDS_MTLS`, `JOYSAFETER_EGRESS_AUTHZ_MTLS`) to `false`
  with a note that production K8s keeps mTLS on (see k8s base `01-config`).
  Keep legacy values as rollback comments.
- `backend/env.example`: clarify provider list — `docker | k8s` supported,
  `daytona | e2b` experimental remote; keep the vars.

### Phase 2 — compose profile separation
- `deploy/docker-compose.yml`: rename profile `rust-orchestrator` → `sandbox`;
  add `sandbox` profile to `joysafeter-envoy` and
  `joysafeter-egress-controller`; add "business services (local testing only)"
  vs "sandbox plane (Docker)" section headers.
- `deploy/deploy.sh`: `--profile rust-orchestrator` → `--profile sandbox`
  (lines 668, 736, 752, 757, 817, 842) + comment on 837.
- `deploy/egress-compose-smoke.sh`: line 96 profile rename.

### Phase 3 — egress smoke upstream (mock-upstream removal finished)
- `deploy/docker-compose.egress-smoke.yml`: replace the `build: ./mock-upstream`
  Go service with an inline Python echo on `${BACKEND_FULL_IMAGE}` (no new
  build dir → keeps `offline-architecture-guard` green). Echo emits JSON of
  method/path/headers/body with header values as lists (matches the
  `egress-compose-smoke.sh` `x-request-id` parser) and logs each request's
  `x-request-id`.
- `deploy/egress-compose-isolation.sh`: align mock-upstream reference.

### Phase 4 — k8s overlay restructure
- Remove `deploy/k8s/overlays/production/`.
- `deploy/PRODUCTION_CHECKLIST.md`: drop the "production overlay is a full-stack
  template" line; sandbox-plane is the sole prod entry.

### Phase 5 — docs
- `deploy/k8s/README.md`: remove stale `local-smoke.sh` wrapper claim.
- `deploy/README.md`: add a two-plane topology section.

## Test plan (evidence)
- `docker compose -f deploy/docker-compose.yml config` parses.
- `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.egress-smoke.yml config` parses; the mock upstream resolves to the backend image with the inline echo command.
- `docker compose --profile local-redis --profile sandbox config` lists the sandbox-plane services; `docker compose config` (no profiles) lists only business services.
- `kubectl kustomize deploy/k8s/base` and overlays `local`, `sandbox-plane`, `egress-tls-smoke` all build; `overlays/production` no longer exists.
- `rg -n 'rust-orchestrator|overlays/production|mock-upstream' deploy` returns only intended (comment/rollback) hits.
- `deploy/k8s/offline-architecture-guard.sh` static assertions pass (mock-upstream stays deleted).
