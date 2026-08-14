"""CredentialGroupService (P0 refactor, Task 6).

Owns the mcp credential-group resource (CRUD + lifecycle) and the group's
membership model. An mcp credential is BORN INTO a group (``group_id`` NOT
NULL), so "membership" is simply an mcp credential row whose ``group_id`` is this
group — there is no separate cred↔group join. ``add_credential`` creates a
kind=mcp credential in the group; ``remove_credential`` soft-deletes it.

Two uniqueness/conflict guarantees are enforced here:

- WITHIN a group, ``(group_id, normalized_mcp_server_url)`` is unique for live
  mcp members (DB partial unique index) → ``CREDENTIAL_GROUP_URL_CONFLICT``.
- ACROSS the groups a session binds, the same normalized url must not appear in
  two different groups (``check_url_conflict_for_session``): the runtime resolves
  credentials by normalized url into a single map, so a cross-group duplicate
  would be nondeterministic and is rejected at bind time.

Member changes (add/remove) and group archive/delete are atomic: the mutation
and ``mark_live_sandboxes_pending`` commit together in one transaction, so there
is no window where the DB holds the new membership while a live limited-
networking sandbox is never flagged for policy re-push.

Out of scope here (owned by later tasks): cross-consumer in-use rejection on
archive/delete (Task 9), the HTTP routes + audit event emission (Task 8), and
error-catalog registration (Task 11). Audit placement: the service performs the
atomic ``mark_pending``; emitting the HTTP audit event is left to the Task-8
route (matching how ``api/v1/secrets.py`` audits at the route layer).
"""

from __future__ import annotations

import builtins
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_api.api.v1.network_policy_refresh import (
    mark_live_sandboxes_pending,
    nudge_sandbox_network_policy_refreshes,
)
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CredentialKind,
    UpdateCredentialGroupRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_group_invariants import (
    credential_group_url_conflict,
    is_credential_group_url_integrity_error,
    reject_member_url_conflict_for_bound_sessions,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_shared.common.app_errors import NotFoundError, ResourceConflictError
from app.joysafeter_shared.ids import CredentialGroupId, CredentialId, SandboxId
from app.joysafeter_shared.mcp_url import normalize_mcp_url
from app.joysafeter_shared.utils.datetime import utc_now


class CredentialGroupService:
    def __init__(self, db: AsyncSession, *, auto_commit: bool = True):
        self.db = db
        self._auto_commit = auto_commit
        self._pending_network_policy_refreshes: list[
            tuple[list[SandboxId], str, str, str, str]
        ] = []
        # Reused for the flat-``data`` contract validation + encrypt-on-write and
        # kind validation when materializing an mcp member.
        self._credentials = CredentialService(db)

    async def _finish_write(self) -> None:
        if self._auto_commit:
            await self.db.commit()
            await self.nudge_pending_network_policy_refreshes()
        else:
            await self.db.flush()

    def _queue_network_policy_refresh(
        self,
        sandbox_ids: list[SandboxId],
        *,
        project_id: str,
        reason: str,
        source_type: str,
        source_id: str,
    ) -> None:
        if sandbox_ids:
            self._pending_network_policy_refreshes.append(
                (sandbox_ids, project_id, reason, source_type, source_id)
            )

    async def nudge_pending_network_policy_refreshes(self) -> None:
        pending, self._pending_network_policy_refreshes = (
            self._pending_network_policy_refreshes,
            [],
        )
        for sandbox_ids, project_id, reason, source_type, source_id in pending:
            await nudge_sandbox_network_policy_refreshes(
                sandbox_ids,
                project_id=project_id,
                reason=reason,
                source_type=source_type,
                source_id=source_id,
            )

    # --- conflict helpers --------------------------------------------------------

    @staticmethod
    def _name_conflict(name: str) -> ResourceConflictError:
        return ResourceConflictError(
            code="CREDENTIAL_GROUP_NAME_EXISTS",
            message=f"A credential group named '{name}' already exists in this project",
            data={"name": name},
            user_action="fix_input",
        )

    @staticmethod
    def _url_conflict(normalized_url: str) -> ResourceConflictError:
        return credential_group_url_conflict(normalized_url)

    @staticmethod
    def _is_group_name_integrity_error(exc: IntegrityError) -> bool:
        message = str(getattr(exc, "orig", None) or exc).lower()
        return "uq_credential_groups_project_name" in message

    @staticmethod
    def _is_group_url_integrity_error(exc: IntegrityError) -> bool:
        return is_credential_group_url_integrity_error(exc)

    async def _group_name_exists(self, project_id: str, name: str) -> bool:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup.id).where(
                JoySafeterCredentialGroup.project_id == project_id,
                JoySafeterCredentialGroup.name == name,
                JoySafeterCredentialGroup.deleted_at.is_(None),
            )
        )
        return result.first() is not None

    # --- group CRUD --------------------------------------------------------------

    async def create(
        self, req: CreateCredentialGroupRequest, project_id: str
    ) -> JoySafeterCredentialGroup:
        group = JoySafeterCredentialGroup(
            project_id=project_id,
            name=req.name,
            description=req.description,
            metadata_=req.metadata,
        )
        self.db.add(group)
        try:
            await self._finish_write()
        except IntegrityError as exc:
            await self.db.rollback()
            if self._is_group_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(group)
        return group

    async def get(
        self, group_id: CredentialGroupId, project_id: str
    ) -> Optional[JoySafeterCredentialGroup]:
        result = await self.db.execute(
            select(JoySafeterCredentialGroup).where(
                and_(
                    JoySafeterCredentialGroup.id == group_id,
                    JoySafeterCredentialGroup.project_id == project_id,
                    JoySafeterCredentialGroup.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_or_raise(
        self, group_id: CredentialGroupId, project_id: str
    ) -> JoySafeterCredentialGroup:
        group = await self.get(group_id, project_id=project_id)
        if group is None:
            raise NotFoundError(
                code="CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
                data={"credential_group_id": str(group_id)},
            )
        return group

    async def lock_groups(
        self,
        group_ids: list[CredentialGroupId],
        *,
        project_id: str | None = None,
    ) -> list[CredentialGroupId]:
        """Lock credential groups in stable id order within the transaction."""
        ordered_ids = sorted(set(group_ids), key=str)
        if not ordered_ids:
            return []
        conditions: list[ColumnElement[bool]] = [
            JoySafeterCredentialGroup.id.in_(ordered_ids)
        ]
        if project_id is not None:
            conditions.append(JoySafeterCredentialGroup.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterCredentialGroup.id)
            .where(and_(*conditions))
            .order_by(JoySafeterCredentialGroup.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def lock_group(
        self,
        group_id: CredentialGroupId,
        *,
        project_id: str | None = None,
    ) -> None:
        await self.lock_groups([group_id], project_id=project_id)

    async def list(
        self,
        project_id: str,
        limit: int = 20,
        after_id: Optional[CredentialGroupId] = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterCredentialGroup], bool]:
        q = select(JoySafeterCredentialGroup).where(
            JoySafeterCredentialGroup.project_id == project_id,
            JoySafeterCredentialGroup.deleted_at.is_(None),
        )
        if not include_archived:
            q = q.where(JoySafeterCredentialGroup.archived_at.is_(None))
        if after_id:
            cursor_created_at = (
                select(JoySafeterCredentialGroup.created_at)
                .where(JoySafeterCredentialGroup.id == after_id)
                .scalar_subquery()
            )
            q = q.where(
                or_(
                    JoySafeterCredentialGroup.created_at < cursor_created_at,
                    and_(
                        JoySafeterCredentialGroup.created_at == cursor_created_at,
                        JoySafeterCredentialGroup.id < after_id,
                    ),
                )
            )
        q = q.order_by(
            JoySafeterCredentialGroup.created_at.desc(),
            JoySafeterCredentialGroup.id.desc(),
        ).limit(limit + 1)
        result = await self.db.execute(q)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def update(
        self,
        group_id: CredentialGroupId,
        req: UpdateCredentialGroupRequest,
        project_id: str,
    ) -> JoySafeterCredentialGroup:
        await self.lock_group(group_id, project_id=project_id)
        group = await self.get_or_raise(group_id, project_id=project_id)

        if req.name is not None and req.name != group.name:
            if await self._group_name_exists(project_id, req.name):
                raise self._name_conflict(req.name)
            group.name = req.name
        if req.description is not None:
            group.description = req.description
        if req.metadata is not None:
            group.metadata_ = req.metadata

        group.updated_at = utc_now()
        try:
            await self._finish_write()
        except IntegrityError as exc:
            await self.db.rollback()
            if req.name is not None and self._is_group_name_integrity_error(exc):
                raise self._name_conflict(req.name) from exc
            raise
        await self.db.refresh(group)
        return group

    # --- lifecycle ---------------------------------------------------------------
    # archive/soft_delete reject when an active session still binds the group
    # (dynamic authz set: a live session's mcp access must not vanish underneath
    # it). Otherwise we set the timestamps + mark_pending, atomically in one
    # commit. Member add/remove stays allowed — that only reshapes the set.

    async def _reject_if_bound_to_active_session(
        self, group_id: CredentialGroupId, project_id: str
    ) -> None:
        from app.joysafeter_domain.models.joysafeter_credential import (
            JoySafeterSessionCredentialGroup,
        )
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

        rows = await self.db.execute(
            select(JoySafeterSessionCredentialGroup.session_id)
            .join(
                JoySafeterSession,
                JoySafeterSession.id == JoySafeterSessionCredentialGroup.session_id,
            )
            .where(
                JoySafeterSessionCredentialGroup.credential_group_id == group_id,
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
            )
        )
        bound = list(rows.scalars().all())
        if bound:
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message="Credential group is bound to an active session and cannot be archived or deleted",
                data={
                    "credential_group_id": str(group_id),
                    "sessions": [str(s) for s in bound],
                },
                user_action="fix_input",
            )

    async def archive(
        self, group_id: CredentialGroupId, project_id: str
    ) -> JoySafeterCredentialGroup:
        await self.lock_group(group_id, project_id=project_id)
        group = await self.get_or_raise(group_id, project_id=project_id)
        await self._reject_if_bound_to_active_session(group_id, project_id)
        group.archived_at = utc_now()
        group.updated_at = utc_now()
        await self._mark_pending(
            project_id=project_id,
            group_id=group.id,
            reason="credential_group_archived",
        )
        await self._finish_write()
        await self.db.refresh(group)
        return group

    async def soft_delete(
        self, group_id: CredentialGroupId, project_id: str
    ) -> JoySafeterCredentialGroup:
        await self.lock_group(group_id, project_id=project_id)
        group = await self.get_or_raise(group_id, project_id=project_id)
        await self._reject_if_bound_to_active_session(group_id, project_id)
        group.deleted_at = utc_now()
        group.updated_at = utc_now()
        await self._mark_pending(
            project_id=project_id,
            group_id=group.id,
            reason="credential_group_deleted",
        )
        await self._finish_write()
        await self.db.refresh(group)
        return group

    # --- membership --------------------------------------------------------------

    async def add_credential(
        self,
        group_id: CredentialGroupId,
        mcp_fields: AddGroupCredentialRequest,
        project_id: str,
    ) -> JoySafeterCredential:
        """Create a kind=mcp credential born into ``group_id``.

        The group must exist in the SAME project. The DB partial unique index
        ``(group_id, normalized_mcp_server_url) WHERE kind='mcp'`` enforces
        within-group url uniqueness; a violation surfaces as
        ``CREDENTIAL_GROUP_URL_CONFLICT``. The insert + ``mark_pending`` commit
        together atomically.
        """
        await self.lock_group(group_id, project_id=project_id)
        await self.get_or_raise(group_id, project_id=project_id)

        plaintext = self._credentials._validate_data_contract(mcp_fields.data)
        plaintext = self._credentials._validate_mcp_static_bearer_data(plaintext)
        normalized_url = normalize_mcp_url(mcp_fields.mcp_server_url)
        await reject_member_url_conflict_for_bound_sessions(
            self.db,
            group_id=group_id,
            normalized_url=normalized_url,
            project_id=project_id,
        )

        cred = JoySafeterCredential(
            project_id=project_id,
            kind=CredentialKind.MCP.value,
            name=mcp_fields.name,
            data=self._credentials.encrypt_data_for_storage(plaintext),
            mcp_server_url=mcp_fields.mcp_server_url,
            normalized_mcp_server_url=normalized_url,
            credential_type="static_bearer",
            group_id=group_id,
        )
        self.db.add(cred)
        try:
            # Flush the insert first so a uniqueness violation surfaces HERE (not
            # via an incidental autoflush inside the mark_pending query), letting
            # us map it to the right conflict code before rolling back.
            await self.db.flush()
            await self._mark_pending(
                project_id=project_id,
                group_id=group_id,
                reason="credential_group_member_added",
            )
            await self._finish_write()
        except IntegrityError as exc:
            await self.db.rollback()
            if self._is_group_url_integrity_error(exc):
                raise self._url_conflict(normalized_url) from exc
            if self._credentials._is_name_integrity_error(exc):
                raise self._credentials._name_conflict(mcp_fields.name) from exc
            raise
        await self.db.refresh(cred)
        return cred

    async def remove_credential(
        self,
        group_id: CredentialGroupId,
        cred_id: CredentialId,
        project_id: str,
    ) -> JoySafeterCredential:
        """Soft-delete an mcp member of the group; atomic with ``mark_pending``."""
        await self.lock_group(group_id, project_id=project_id)
        await self._credentials.lock_credential(cred_id, project_id=project_id)
        cred = await self._get_member_or_raise(group_id, cred_id, project_id=project_id)
        cred.deleted_at = utc_now()
        cred.updated_at = utc_now()
        await self._mark_pending(
            project_id=project_id,
            group_id=group_id,
            reason="credential_group_member_removed",
        )
        await self._finish_write()
        await self.db.refresh(cred)
        return cred

    async def archive_credential(
        self,
        group_id: CredentialGroupId,
        cred_id: CredentialId,
        project_id: str,
    ) -> JoySafeterCredential:
        await self.lock_group(group_id, project_id=project_id)
        await self._credentials.lock_credential(cred_id, project_id=project_id)
        cred = await self._get_member_or_raise(group_id, cred_id, project_id=project_id)
        if cred.archived_at is None:
            cred.archived_at = utc_now()
            cred.updated_at = utc_now()
            await self._mark_pending(
                project_id=project_id,
                group_id=group_id,
                reason="credential_group_member_archived",
            )
            await self._finish_write()
            await self.db.refresh(cred)
        return cred

    async def list_members(
        self,
        group_id: CredentialGroupId,
        project_id: str,
        *,
        include_archived: bool = True,
    ) -> builtins.list[JoySafeterCredential]:
        query = select(JoySafeterCredential).where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.group_id == group_id,
            JoySafeterCredential.kind == CredentialKind.MCP.value,
            JoySafeterCredential.deleted_at.is_(None),
        )
        if not include_archived:
            query = query.where(JoySafeterCredential.archived_at.is_(None))
        result = await self.db.execute(
            query.order_by(
                JoySafeterCredential.created_at.desc(),
                JoySafeterCredential.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def _get_member_or_raise(
        self,
        group_id: CredentialGroupId,
        cred_id: CredentialId,
        project_id: str,
    ) -> JoySafeterCredential:
        result = await self.db.execute(
            select(JoySafeterCredential).where(
                JoySafeterCredential.id == cred_id,
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.group_id == group_id,
                JoySafeterCredential.kind == CredentialKind.MCP.value,
                JoySafeterCredential.deleted_at.is_(None),
            )
        )
        cred = result.scalar_one_or_none()
        if cred is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found in group",
                data={"credential_id": str(cred_id), "credential_group_id": str(group_id)},
            )
        return cred

    # --- cross-group url conflict (session bind) ---------------------------------

    async def check_url_conflict_for_session(
        self, group_ids: builtins.list[CredentialGroupId], project_id: str
    ) -> None:
        """Reject a session binding that would map one normalized url to two groups.

        Given the groups a session wants to bind, gather the normalized mcp urls of
        every live member. If the SAME normalized url lives in two DIFFERENT groups
        the runtime's url→credential resolution would be nondeterministic, so we
        reject at bind time with ``CREDENTIAL_GROUP_URL_CONFLICT``. Called by Task
        9's session-bind path.
        """
        unique_ids: builtins.list[CredentialGroupId] = builtins.list(dict.fromkeys(group_ids))
        if len(unique_ids) < 2:
            return

        result = await self.db.execute(
            select(
                JoySafeterCredential.normalized_mcp_server_url,
                JoySafeterCredential.group_id,
            ).where(
                JoySafeterCredential.project_id == project_id,
                JoySafeterCredential.group_id.in_(unique_ids),
                JoySafeterCredential.kind == CredentialKind.MCP.value,
                JoySafeterCredential.archived_at.is_(None),
                JoySafeterCredential.deleted_at.is_(None),
            )
        )
        seen: dict[str, CredentialGroupId] = {}
        for normalized_url, member_group_id in result.all():
            if normalized_url is None:
                continue
            prior = seen.get(normalized_url)
            if prior is not None and prior != member_group_id:
                raise self._url_conflict(normalized_url)
            seen[normalized_url] = member_group_id

    # --- atomic refresh primitive ------------------------------------------------

    async def _mark_pending(
        self,
        *,
        project_id: str,
        group_id: CredentialGroupId,
        reason: str,
    ) -> None:
        """Flag live limited-networking sandboxes ``pending`` in THIS transaction.

        No commit here: the caller commits, so the membership/group mutation and
        the pending mark land together. The durable ``pending`` reconcile loop
        converges regardless of any push.
        """
        sandbox_ids = await mark_live_sandboxes_pending(
            self.db,
            project_id=project_id,
            source_type="credential_group",
            source_id=str(group_id),
        )
        self._queue_network_policy_refresh(
            sandbox_ids,
            project_id=project_id,
            reason=reason,
            source_type="credential_group",
            source_id=str(group_id),
        )
