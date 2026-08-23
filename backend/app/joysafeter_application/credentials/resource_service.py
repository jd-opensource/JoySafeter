from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from app.joysafeter_domain.credentials.types import CredentialId

from .ports import (
    CredentialAuditEntry,
    CredentialUnitOfWork,
    MutationOutcome,
    combine_credential_impacts,
)

T = TypeVar("T")
logger = logging.getLogger(__name__)
credential_nudge_failures: Counter[str] = Counter()


class CredentialResourceService:
    def __init__(
        self,
        uow: CredentialUnitOfWork,
        *,
        manage_transaction: bool = True,
    ) -> None:
        self._uow = uow
        self._manage_transaction = manage_transaction

    def _clear_pending(self) -> None:
        clear_pending_impacts = getattr(self._uow.credentials, "clear_pending_impacts", None)
        if clear_pending_impacts is not None:
            clear_pending_impacts()
        clear_pending = getattr(self._uow.impacts, "clear_pending", None)
        if clear_pending is not None:
            clear_pending()

    async def rollback_pending(self) -> None:
        self._clear_pending()
        await self._uow.rollback()

    async def _nudge_after_commit(self) -> None:
        try:
            await self._uow.impacts.nudge_after_commit()
        except Exception:
            credential_nudge_failures["after_commit"] += 1
            logger.warning("credential impact nudge failed after commit", exc_info=True)

    async def commit_pending(self) -> None:
        await self._uow.commit()
        await self._nudge_after_commit()

    def begin_batch(self) -> None:
        """Reset the per-session generation-advance dedup window once for a batch.

        Managed single mutations reset the window inside `_mutate`. A
        `manage_transaction=False` batch shares one commit across many
        mutations, so the window must be reset exactly once at the start —
        `_mutate` deliberately skips the per-mutation reset there. Doing it here
        makes the batch's transaction start explicit instead of relying on the
        impact adapter happening to be freshly composed.
        """
        begin_mutation = getattr(self._uow.impacts, "begin_mutation", None)
        if begin_mutation is not None:
            begin_mutation()

    async def _mutate(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        action: str,
        project_id: str,
        target_id: str | None = None,
        target_type: str = "credential",
        details: Mapping[str, object] | None = None,
    ) -> T:
        try:
            raw_result = await operation()
            outcome = raw_result if isinstance(raw_result, MutationOutcome) else MutationOutcome(raw_result, True)
            result = outcome.value
            if not outcome.changed:
                if self._manage_transaction:
                    await self._uow.commit()
                return result
            resolved_target_id = target_id or str(getattr(result, "id", "")) or None
            await self._uow.audit.append(
                CredentialAuditEntry(
                    action=action,
                    project_id=project_id,
                    target_type=target_type,
                    target_id=resolved_target_id,
                    details=details or {},
                )
            )
            take_pending_impacts = getattr(self._uow.credentials, "take_pending_impacts", None)
            pending_impacts = () if take_pending_impacts is None else take_pending_impacts()
            combined_impact = combine_credential_impacts(pending_impacts)
            if combined_impact is not None:
                # Reset the per-session generation-advance dedup only when this
                # _mutate owns its transaction. In a batch (manage_transaction=
                # False), multiple mutations share one commit, so the dedup set
                # must span the whole batch — the adapter already clears it at
                # the transaction boundary (nudge_after_commit / clear_pending).
                if self._manage_transaction:
                    begin_mutation = getattr(self._uow.impacts, "begin_mutation", None)
                    if begin_mutation is not None:
                        begin_mutation()
                await self._uow.impacts.mark_pending(combined_impact)
            if self._manage_transaction:
                await self._uow.commit()
        except Exception:
            self._clear_pending()
            if self._manage_transaction:
                await self._uow.rollback()
            raise
        if self._manage_transaction:
            await self._nudge_after_commit()
        return result

    async def create(self, request: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.create(request, project_id),
            action="credential.created",
            project_id=project_id,
        )

    async def update(self, credential_id: CredentialId, request: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.update(credential_id, request, project_id),
            action="credential.updated",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def set_default(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.set_default(credential_id, project_id),
            action="credential.default_set",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def clear_default(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.clear_default(credential_id, project_id),
            action="credential.default_cleared",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def archive(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.archive(credential_id, project_id),
            action="credential.archived",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def restore(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.restore(credential_id, project_id),
            action="credential.restored",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def soft_delete(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.soft_delete(credential_id, project_id),
            action="credential.deleted",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def get(self, credential_id: CredentialId, project_id: str) -> Any | None:
        return await self._uow.credentials.get(credential_id, project_id)

    async def get_or_raise(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._uow.credentials._get_or_raise(credential_id, project_id)

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.list(*args, **kwargs)

    async def dependencies(self, credential_id: CredentialId, project_id: str) -> Any:
        return await self._uow.credentials.dependencies(credential_id, project_id)

    def get_credential_data(self, credential: Any | None) -> dict[str, str]:
        return self._uow.credentials.get_credential_data(credential)

    def get_masked(self, credential: Any | None) -> dict[str, str]:
        return self._uow.credentials.get_masked(credential)
