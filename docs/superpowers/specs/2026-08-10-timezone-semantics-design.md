# JoySafeter Timezone Semantics

## Goals

- Keep machine timestamps unambiguous and comparable.
- Show human-facing times in the correct user or platform timezone.
- Give every sandbox provider the same runtime timezone behavior.
- Avoid deriving human-readable labels directly from UTC timestamps.

## Time Layers

1. **Persistence and scheduling**
   - Database timestamps, task leases, events, durations, and cron comparisons use timezone-aware UTC.
   - API timestamps remain ISO 8601 values with an explicit offset.

2. **Browser presentation**
   - General timestamps render in the browser locale and browser timezone.
   - Trigger previews use the trigger's explicitly selected IANA timezone.

3. **Server-generated human labels**
   - Labels such as automatic session titles use `JOYSAFETER_TIMEZONE`.
   - `TZ` is the compatibility fallback; invalid or missing values fall back to UTC.

4. **Sandbox process time**
   - New sandboxes receive `TZ` through the shared `SandboxCreateConfig.env` path.
   - `JOYSAFETER_SANDBOX_TIMEZONE` overrides `JOYSAFETER_TIMEZONE`, then `TZ`, then UTC.
   - Docker, Kubernetes, Daytona, and E2B providers must all forward the resolved environment.

5. **Operational logs**
   - Structured logs may remain UTC and must retain an explicit `Z` or offset.
   - UTC log timestamps are not converted into user-facing labels.

## Compatibility

- Existing persisted session titles are not rewritten automatically because custom titles and generated titles cannot be distinguished with complete certainty.
- Existing sandbox processes keep the environment they were created with. Stop or recreate them to pick up a new timezone.
- Newly created titles and sandboxes use the unified timezone configuration immediately after service deployment.
