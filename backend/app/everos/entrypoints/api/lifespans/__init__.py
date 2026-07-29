"""HTTP API lifespan providers.

Concrete :class:`everos.core.lifespan.LifespanProvider` implementations
for the storage + chassis backends this entrypoint composes. They live next to
``app.py`` because they are *application-bootstrap* details, not
generic chassis: a different deployment mode (CLI, embedded, batch
worker) may compose a different set of providers.

Putting these here also keeps ``core.lifespan`` free of concrete-
backend imports — the chassis stays portable.

External usage::

    from app.everos.entrypoints.api.lifespans import (
        LLMLifespanProvider,
        SqliteLifespanProvider,
        LanceDBLifespanProvider,
        CascadeLifespanProvider,
        VectorRebuildLifespanProvider,
        OmeLifespanProvider,
    )
"""

from .cascade import CascadeLifespanProvider as CascadeLifespanProvider
from .lancedb import LanceDBLifespanProvider as LanceDBLifespanProvider
from .llm import LLMLifespanProvider as LLMLifespanProvider
from .ome import OmeLifespanProvider as OmeLifespanProvider
from .sqlite import SqliteLifespanProvider as SqliteLifespanProvider
from .vector_rebuild import (
    VectorRebuildLifespanProvider as VectorRebuildLifespanProvider,
)

__all__ = [
    "CascadeLifespanProvider",
    "LLMLifespanProvider",
    "LanceDBLifespanProvider",
    "OmeLifespanProvider",
    "SqliteLifespanProvider",
    "VectorRebuildLifespanProvider",
]
