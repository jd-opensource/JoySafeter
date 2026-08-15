from dataclasses import dataclass

from .errors import FederationError


@dataclass(frozen=True, slots=True)
class AccountLinkPolicy:
    allow_registration: bool
    auto_link_by_email: bool

    def require_auto_link_allowed(
        self,
        principal_email: str | None,
        principal_email_verified: bool,
        existing_user_email: str | None,
        existing_user_active: bool,
    ) -> None:
        if (
            not self.auto_link_by_email
            or not principal_email_verified
            or not existing_user_active
            or self._normalize_email(principal_email) != self._normalize_email(existing_user_email)
            or self._normalize_email(principal_email) is None
        ):
            raise FederationError(
                code="FEDERATION_ACCOUNT_LINK_REQUIRED",
                message="Federated account requires explicit account linking",
            )

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        return email.strip().lower() if email is not None else None
