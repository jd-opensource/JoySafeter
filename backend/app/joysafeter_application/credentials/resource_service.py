from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .ports import CredentialAuditEntry, CredentialUnitOfWork, MutationOutcome

T = TypeVar("T")
logger = logging.getLogger(__name__)
credential_nudge_failures: Counter[str] = Counter()


class CredentialResourceService:
    def __init__(
        self,
        uow: CredentialUnitOfWork,
        *,
        manage_transaction: bool = True,
        unconditional_rollback: bool = True,
    ) -> None:
        self._uow = uow
        self._manage_transaction = manage_transaction
        self._unconditional_rollback = unconditional_rollback

    def __getattr__(self, name: str) -> Any:
        return getattr(self._uow.credentials, name)

    async def _mutate(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        action: str,
        project_id: str,
        target_id: str | None = None,
        target_type: str = "credential",
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
                )
            )
            take_pending_impacts = getattr(self._uow.credentials, "take_pending_impacts", None)
            pending_impacts = () if take_pending_impacts is None else take_pending_impacts()
            for impact in pending_impacts:
                await self._uow.impacts.mark_pending(impact)
            if self._manage_transaction:
                await self._uow.commit()
        except Exception:
            clear_pending_impacts = getattr(self._uow.credentials, "clear_pending_impacts", None)
            if clear_pending_impacts is not None:
                clear_pending_impacts()
            clear_pending = getattr(self._uow.impacts, "clear_pending", None)
            if clear_pending is not None:
                clear_pending()
            rollback_required = self._unconditional_rollback
            if not rollback_required:
                requires_rollback = getattr(self._uow, "rollback_required", None)
                rollback_required = requires_rollback is None or requires_rollback()
            if rollback_required:
                await self._uow.rollback()
            raise
        if self._manage_transaction:
            try:
                await self._uow.impacts.nudge_after_commit()
            except Exception:
                credential_nudge_failures["after_commit"] += 1
                logger.warning("credential impact nudge failed after commit", exc_info=True)
        return result

    async def create(self, request: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.create(request, project_id),
            action="credential.created",
            project_id=project_id,
        )

    async def update(self, credential_id: Any, request: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.update(credential_id, request, project_id),
            action="credential.updated",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def set_default(self, credential_id: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.set_default(credential_id, project_id),
            action="credential.default_set",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def clear_default(self, credential_id: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.clear_default(credential_id, project_id),
            action="credential.default_cleared",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def archive(self, credential_id: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.archive(credential_id, project_id),
            action="credential.archived",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def restore(self, credential_id: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.restore(credential_id, project_id),
            action="credential.restored",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def soft_delete(self, credential_id: Any, project_id: str) -> Any:
        return await self._mutate(
            lambda: self._uow.credentials.soft_delete(credential_id, project_id),
            action="credential.deleted",
            project_id=project_id,
            target_id=str(credential_id),
        )

    async def get(self, credential_id: Any, project_id: str) -> Any | None:
        return await self._uow.credentials.get(credential_id, project_id)

    async def _get_or_raise(self, credential_id: Any, project_id: str) -> Any:
        return await self._uow.credentials._get_or_raise(credential_id, project_id)

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.list(*args, **kwargs)

    async def dependencies(self, credential_id: Any, project_id: str) -> Any:
        return await self._uow.credentials.dependencies(credential_id, project_id)

    async def lock_credentials(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.lock_credentials(*args, **kwargs)

    async def lock_credential_group(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.lock_credential_group(*args, **kwargs)

    async def lock_credential_scope(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.lock_credential_scope(*args, **kwargs)

    async def lock_credential(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.credentials.lock_credential(*args, **kwargs)

    async def nudge_pending_network_policy_refreshes(self) -> None:
        try:
            await self._uow.impacts.nudge_after_commit()
        except Exception:
            credential_nudge_failures["compatibility_after_commit"] += 1
            logger.warning("credential impact nudge failed after compatibility commit", exc_info=True)

    def encrypt_data_for_storage(self, data: dict[str, str] | None) -> dict[str, str]:
        return self._uow.credentials.encrypt_data_for_storage(data)

    def decrypt_data(self, data: dict | None) -> dict[str, str]:
        return self._uow.credentials.decrypt_data(data)

    def get_credential_data(self, credential: Any | None) -> dict[str, str]:
        return self._uow.credentials.get_credential_data(credential)

    def mask_data(self, data: dict[str, str]) -> dict[str, str]:
        return self._uow.credentials.mask_data(data)

    def get_masked(self, credential: Any | None) -> dict[str, str]:
        return self._uow.credentials.get_masked(credential)

    def merge_update_plaintext(
        self,
        current_data: dict | None,
        requested_data: dict[str, str] | None,
    ) -> dict[str, str]:
        return self._uow.credentials.merge_update_plaintext(current_data, requested_data)
