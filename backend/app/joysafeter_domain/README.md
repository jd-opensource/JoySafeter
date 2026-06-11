# JoySafeter Domain Layer

`app.joysafeter_domain` is the target package for business-domain code shared by
the API, runner, and worker services.

Current migration status:

- `app.joysafeter_domain.models.*`: ORM models.
- `app.joysafeter_domain.repositories.*`: data access layer.
- `app.joysafeter_domain.schemas.*`: Pydantic schemas.
- `app.joysafeter_domain.services.*`: shared domain services.
- `app.joysafeter_domain.contracts.*`, `app.joysafeter_domain.ports.*`, and `app.joysafeter_domain.state_machines.*`: domain abstractions.
- `app.joysafeter_domain.agent.*`: domain-facing agent runtime entrypoints.
- Service packages access shared service implementations through local facades:
  - `app.joysafeter_api.services`
  - `app.joysafeter_orchestrator.services`
  - `app.joysafeter_worker.services`

Future migration guidance:

1. Move one bounded context at a time, for example `agents`, `sessions`, `skills`, or `auth`.
2. Keep compatibility exports in the old top-level package until all imports are updated.
3. Prefer service-package facades importing from `app.joysafeter_domain.*`, not from legacy top-level packages.
4. Run import and route-exposure checks after each bounded-context migration.

`app.domain.*` remains as a compatibility alias for older imports.
