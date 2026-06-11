# JoySafeter Shared Layer

`app.joysafeter_shared` contains cross-service infrastructure that is not owned
by a single API, runner, or worker service.

Current packages:

- `joysafeter_shared.runtime`: shared FastAPI app factory and common lifecycle helpers.
- `joysafeter_shared.common`: common errors, auth dependencies, logging, and responses.
- `joysafeter_shared.utils`: cross-service utility helpers.
- `joysafeter_shared.storage`: storage abstraction and backend factories.
- `joysafeter_shared.config`: service settings and service-role helpers.
- `joysafeter_shared.database`: SQLAlchemy database/session helpers.
- `joysafeter_shared.cache`: Redis/cache helpers.
- `joysafeter_shared.model`: model provider/factory helpers.
- `joysafeter_shared.observation`: tracing/observation helpers.
- `joysafeter_shared.oauth`: OAuth protocol helpers.
- `joysafeter_shared.skill`: skill parsing/validation utilities.
- `joysafeter_shared.tools`: cross-service tool helpers.
- `joysafeter_shared.templates`: shared template assets such as email templates.

Old top-level packages remain for backward compatibility. New cross-service code
should prefer `app.joysafeter_shared.*` paths. `app.shared.*` remains as a
compatibility alias.
