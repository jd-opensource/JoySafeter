"""Shared retry-with-feedback for LLM extractors that accept a ``prompt`` override.

The everalgo extractors (episode / foresight / atomic_fact / …) each issue a
single LLM call and raise ``ValueError`` when the response fails schema
validation or JSON parsing. On its own that means one bad response drops the
whole extraction. This helper retries such failures and — crucially — appends
the *previous failure reason* to the prompt on each retry so the model can
self-correct instead of blindly repeating the same mistake.

It only handles ``ValueError`` (schema / JSON). Transient upstream failures
(HTTP 5xx / connection resets) are retried one layer down in the LLM provider
and surface as ``LLMError``; those are intentionally not caught here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.everos.core.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def build_correction(err: Exception, must_return: str) -> str:
    """Corrective instruction carrying the previous failure reason.

    ``must_return`` names the exact shape the model must produce (e.g.
    ``'a JSON object with the keys "title" and "content"'``).
    """
    reason = str(err)[:300]
    return (
        "\n\n---\n"
        f"RETRY — your previous response was REJECTED. Reason: {reason}\n"
        f"You MUST return ONLY {must_return}. Do NOT return a different schema, "
        "extra keys, or any prose outside the JSON. Output the JSON and nothing "
        "else."
    )


async def aextract_with_feedback(
    run: Callable[[str | None], Awaitable[T]],
    *,
    base_prompt: str | None,
    default_prompt: str | None,
    max_attempts: int,
    must_return: str,
    log_event: str,
) -> T:
    """Run ``run(prompt)`` with ValueError-retry that feeds the reason back.

    Args:
        run: Performs one extractor call with the given (possibly augmented)
            prompt override, e.g. ``lambda p: extractor.aextract(cell,
            sender_id=sid, prompt=p)``.
        base_prompt: The caller's prompt override, or ``None`` to use the algo
            default on the first attempt.
        default_prompt: The algo default prompt used to *anchor* a corrective
            retry when ``base_prompt`` is ``None``. If both are ``None`` the
            retry simply re-runs with the original prompt (no feedback).
        max_attempts: Total attempts (>= 1).
        must_return: Human-readable description of the required output shape,
            injected into the correction.
        log_event: Structured log event name for retry warnings.
    """
    anchor = base_prompt if base_prompt is not None else default_prompt
    effective = base_prompt
    last_err: ValueError | None = None
    for attempt in range(max_attempts):
        try:
            return await run(effective)
        except ValueError as err:
            last_err = err
            logger.warning(
                log_event,
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "error": str(err)[:200],
                },
            )
            if anchor is not None:
                effective = anchor + build_correction(err, must_return)
    assert last_err is not None  # loop ran >= 1 time and never returned
    raise last_err
