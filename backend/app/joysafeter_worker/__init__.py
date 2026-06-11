"""JoySafeter worker service package.

Owns background worker loops, execution reapers, Redis Stream consumers, batched
JoySafeter event persistence, and worker-facing service adapters. The ASGI
entrypoint is `app.joysafeter_worker.main:app`.
"""

__all__ = []
