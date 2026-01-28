"""Agent subpackage (core agent runtime components).

This file exists to make `app.core.agent` a regular Python package so that
static analyzers (e.g. Pylance/Pyright) can reliably resolve imports like:
`app.core.agent.memory.strategies`.

Keep this module side-effect free: avoid importing heavy dependencies here.
"""

__all__: list[str] = []
