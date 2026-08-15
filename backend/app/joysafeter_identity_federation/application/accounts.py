from collections.abc import Awaitable, Callable

from ..domain.models import FederatedAccountView, ProviderId
from ..domain.ports import FederatedAccountGateway


class FederatedAccountService:
    def __init__(
        self,
        gateway: FederatedAccountGateway,
        commit: Callable[[], Awaitable[None]],
    ) -> None:
        self._gateway = gateway
        self._commit = commit

    async def list_accounts(self, user_id: str) -> tuple[FederatedAccountView, ...]:
        return await self._gateway.list_accounts(user_id)

    async def unlink(self, user_id: str, provider_id: ProviderId) -> bool:
        removed = await self._gateway.unlink(user_id, provider_id)
        if removed:
            await self._commit()
        return removed
