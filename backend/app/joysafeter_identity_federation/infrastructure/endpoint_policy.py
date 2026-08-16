import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressResolver = Callable[[str, int], tuple[str, ...]]

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def normalize_endpoint_hostname(hostname: str) -> str | None:
    if not hostname.isascii():
        return None
    normalized = (hostname[:-1] if hostname.endswith(".") else hostname).lower()
    if not normalized:
        return None
    try:
        return str(ipaddress.ip_address(normalized))
    except ValueError:
        pass
    if len(normalized) > 253:
        return None
    labels = normalized.split(".")
    if any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        return None
    return normalized


def parse_http_endpoint(value: str) -> tuple[str, str, int] | None:
    if (
        not value
        or value != value.strip()
        or "${" in value
        or any(char == "\\" or char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or hostname is None or not parsed.netloc:
        return None
    normalized_hostname = normalize_endpoint_hostname(hostname)
    if normalized_hostname is None:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if port < 1:
        return None
    return parsed.scheme, normalized_hostname, port


def resolve_endpoint_addresses(hostname: str, port: int) -> tuple[str, ...]:
    address_info = socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(dict.fromkeys(str(sockaddr[0]) for *_, sockaddr in address_info))


def endpoint_addresses(
    hostname: str,
    port: int,
    *,
    resolver: AddressResolver = resolve_endpoint_addresses,
) -> tuple[IPAddress, ...] | None:
    try:
        return (ipaddress.ip_address(hostname),)
    except ValueError:
        pass
    try:
        resolved = resolver(hostname, port)
    except (OSError, UnicodeError):
        return None
    if not resolved:
        return None
    addresses: list[IPAddress] = []
    for value in resolved:
        try:
            addresses.append(ipaddress.ip_address(value))
        except ValueError:
            return None
    return tuple(addresses)


def is_trusted_private_address(address: IPAddress) -> bool:
    """Return True for a private/internal address safe to reach when a provider opts in.

    Permits RFC1918-style private networks and loopback, but never link-local
    (169.254.0.0/16 and fe80::/10, where cloud metadata lives), multicast,
    reserved, or unspecified addresses.
    """
    return address.is_private and not (
        address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified
    )
