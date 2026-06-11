"""Agent subpackage (core agent runtime components).

This file exists to make `app.joysafeter_domain.agent` a regular Python package so that
static analyzers (e.g. Pylance/Pyright) can reliably resolve imports like:
`app.joysafeter_domain.agent.memory.strategies`.

Keep this module side-effect free: avoid importing heavy dependencies here.
"""

__all__: list[str] = []
