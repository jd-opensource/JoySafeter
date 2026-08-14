# Repository guidance for Claude Code

## Third-party dependencies

Don't read or modify `.deps/SkillSpector` unless a task specifically requires it.

Why: it's a vendored third-party library, not part of this repo's codebase.

## Backend tests

Run from `backend/`, never bare `pytest` at the repo root:

```bash
cd backend && uv run pytest
```

Why: pytest config lives only in `backend/pyproject.toml` and pytest searches
*upward* for it. From the root it finds no config and falls back to
`asyncio_mode=strict`, so every `auto` async test fails with
`async def functions are not natively supported.` — a cwd artifact, not a code bug.
