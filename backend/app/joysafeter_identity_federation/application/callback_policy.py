import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes, urlsplit

from ..domain.errors import FederationError

_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ENCODED_PATH_SEPARATOR = re.compile(r"%(?:2[fF]|5[cC])")
_ENCODED_PERCENT = re.compile(r"%25", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CallbackUrlPolicy:
    default_redirect_url: str

    def resolve(self, callback_url: str | None) -> str:
        resolved = self.default_redirect_url if callback_url is None else callback_url
        if not self._is_valid(resolved):
            raise FederationError(
                code="FEDERATION_CALLBACK_URL_INVALID",
                message="Federation callback URL is invalid",
            )
        return resolved

    @classmethod
    def _is_valid(cls, value: str) -> bool:
        if (
            not value
            or value != value.strip()
            or not value.startswith("/")
            or value.startswith("//")
            or cls._contains_unsafe_character(value)
            or _INVALID_PERCENT_ESCAPE.search(value) is not None
        ):
            return False

        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
            return False
        if _ENCODED_PATH_SEPARATOR.search(parsed.path) is not None or _ENCODED_PERCENT.search(parsed.path) is not None:
            return False

        try:
            decoded_path = unquote_to_bytes(parsed.path).decode("utf-8")
        except UnicodeError:
            return False
        if (
            not decoded_path.startswith("/")
            or decoded_path.startswith("//")
            or cls._contains_unsafe_character(decoded_path)
        ):
            return False
        return all(segment not in {".", ".."} for segment in decoded_path.split("/"))

    @staticmethod
    def _contains_unsafe_character(value: str) -> bool:
        return any(
            character == "\\" or character.isspace() or unicodedata.category(character) in {"Cc", "Cf"}
            for character in value
        )
