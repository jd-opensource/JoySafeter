"""Episode cascade handler — md → LanceDB ``episode`` table.

Inherits :class:`BaseDailyLogHandler` for the diff / dispatch loop and
overrides :meth:`_build_row` to map an Episode entry's structured
body into the typed LanceDB row. Documented md contract (callers /
writers must match):

``inline`` block:

- ``owner_id``: ``user_id`` or ``agent_id`` — duplicates the
  frontmatter scope so the cascade can derive it without re-reading
  the frontmatter.
- ``session_id``: conversation scope.
- ``timestamp``: ISO-8601 string (``to_iso_format`` output).
- ``parent_type``: source kind label (currently always ``"memcell"``
  — :class:`ParentType` enum; explicit in md so future kinds plug in
  without a schema change).
- ``parent_id``: source memcell id.
- ``sender_ids``: ``[u_a, u_b]`` rendered shape from
  ``_render_value`` (optional; defaults to empty list).

``sections``:

- ``Subject`` (optional): one-line topic.
- ``Summary`` (optional): condensed narrative.
- ``Content``: full episode narrative — fed to the embedder AND the
  tokenizer for the ``episode_tokens`` BM25 field.
"""

from __future__ import annotations

from app.everos.infra.persistence.lancedb import Episode, ParentType, episode_repo

from ..vector_embedding import embed_text_for_index
from ._common import parse_inline_list, require_iso_timestamp
from ._daily_log_base import BaseDailyLogHandler, ParsedEntry, daily_log_row_id


class EpisodeHandler(BaseDailyLogHandler):
    """Cascade handler for ``users/<u>/episodes/episode-*.md``."""

    kind = "episode"
    lance_repo = episode_repo
    content_change_keys = (
        "section:Subject",
        "section:Summary",
        "section:Content",
    )
    """Subject / Summary / Content all participate in the digest:

    - Editing Content rewrites the embedding (correct).
    - Editing Subject / Summary doesn't change the embed text but still
      bumps the digest so the LanceDB ``subject`` / ``summary`` columns
      stay in sync with md. The slight overshoot (one wasted embed
      call on Subject edits) is accepted under the single-hash design
      (cascade Q2 discussion)."""

    async def _build_row(
        self,
        *,
        owner_id: str,
        owner_type: str,
        app_id: str = "default",
        project_id: str = "default",
        md_path: str,
        entry: ParsedEntry,
    ) -> Episode:
        s = entry.structured
        text = s.sections.get("Content", "").strip()
        tokens = self._deps.tokenizer.tokenize(text)
        indexed = await embed_text_for_index(
            self._deps.embedder,
            text,
            embedding_model=getattr(self._deps.embedder, "_model", None),
        )
        return Episode(
            id=daily_log_row_id(md_path, entry.entry_id),
            entry_id=entry.entry_id,
            owner_id=owner_id,
            owner_type=owner_type,
            app_id=app_id,
            project_id=project_id,
            session_id=s.inline.get("session_id"),
            timestamp=require_iso_timestamp(s.inline.get("timestamp")),
            parent_type=s.inline.get("parent_type") or ParentType.MEMCELL.value,
            parent_id=s.inline.get("parent_id", ""),
            sender_ids=parse_inline_list(s.inline.get("sender_ids", "")),
            source_entry_ids=parse_inline_list(s.inline.get("source_entry_ids", "")),
            source_session_ids=parse_inline_list(s.inline.get("source_session_ids", "")),
            source_agent_ids=parse_inline_list(s.inline.get("source_agent_ids", "")),
            subject=s.sections.get("Subject") or None,
            summary=s.sections.get("Summary") or None,
            episode=text,
            episode_tokens=" ".join(tokens),
            md_path=md_path,
            content_sha256=entry.content_sha256,
            vector=indexed.vector,
            vector_status=indexed.vector_status,
            vector_updated_at=indexed.vector_updated_at,
            embedding_model=indexed.embedding_model,
        )
