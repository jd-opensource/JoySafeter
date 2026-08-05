"""
Protocol handler factory.

Return a handler instance by protocol name.

Usage:
    from app.joysafeter_shared.oauth.factory import get_protocol_handler

    handler = get_protocol_handler("oauth2")  # or "jd_sso"
    user_info = await handler.get_user_info(request, provider_config, code)
"""

from typing import Dict, Type

from loguru import logger

from app.joysafeter_shared.oauth.protocols.base import BaseProtocolHandler
from app.joysafeter_shared.oauth.protocols.jd_sso import JDSSOHandler
from app.joysafeter_shared.oauth.protocols.oauth2 import OAuth2Handler

LOG_PREFIX = "[OAuthFactory]"

# Protocol handler registry
# Register new protocols here
_PROTOCOL_HANDLERS: Dict[str, Type[BaseProtocolHandler]] = {
    "oauth2": OAuth2Handler,
    "jd_sso": JDSSOHandler,
}

# Handler instance cache (singleton-like)
_handler_instances: Dict[str, BaseProtocolHandler] = {}


def get_protocol_handler(protocol: str) -> BaseProtocolHandler:
    """
    Get protocol handler instance.

    Args:
        protocol: Protocol name (e.g. "oauth2", "jd_sso")

    Returns:
        BaseProtocolHandler: Handler instance

    Raises:
        ValueError: Unknown protocol
    """
    # Prefer cache
    if protocol in _handler_instances:
        return _handler_instances[protocol]

    # Find handler class
    handler_class = _PROTOCOL_HANDLERS.get(protocol)
    if handler_class is None:
        # Fallback to default OAuth2 handler
        logger.warning(f"{LOG_PREFIX} Unknown protocol '{protocol}', falling back to oauth2")
        handler_class = OAuth2Handler

    # Create instance and cache
    handler = handler_class()
    _handler_instances[protocol] = handler

    logger.debug(f"{LOG_PREFIX} Created handler for protocol: {protocol}")
    return handler


def register_protocol_handler(protocol: str, handler_class: Type[BaseProtocolHandler]) -> None:
    """
    Register a new protocol handler.

    Use this to extend supported protocols.

    Args:
        protocol: Protocol name
        handler_class: Handler class

    Example:
        register_protocol_handler("custom_sso", CustomSSOHandler)
    """
    _PROTOCOL_HANDLERS[protocol] = handler_class
    # Clear cache to recreate on next request
    if protocol in _handler_instances:
        del _handler_instances[protocol]
    logger.info(f"{LOG_PREFIX} Registered protocol handler: {protocol}")


def list_supported_protocols() -> list[str]:
    """
    List all supported protocols.

    Returns:
        Protocol list
    """
    return list(_PROTOCOL_HANDLERS.keys())
