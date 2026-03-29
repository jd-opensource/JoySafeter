"""DSL parser package — parse Python DSL code into GraphSchema."""

from app.core.dsl.dsl_models import ParseError, ParseResult

__all__ = ["ParseError", "ParseResult"]


def __getattr__(name: str):
    """Lazy import to avoid pulling in heavy graph_schema dependencies at package load."""
    if name == "DSLParser":
        from app.core.dsl.dsl_parser import DSLParser
        return DSLParser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
