"""Framework-independent same-origin checks for the loopback administration UI."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def mutation_source_is_same_origin(
    request_url: str,
    *,
    origin: str | None,
    referer: str | None,
    fetch_site: str | None,
) -> bool:
    """Require browser mutation requests to prove an exact same origin."""

    if fetch_site and fetch_site.casefold() not in {"same-origin", "none"}:
        return False
    source = (origin or referer or "").strip()
    if not source or source.casefold() == "null":
        return False
    request_origin = _origin(request_url)
    source_origin = _origin(source)
    return (
        request_origin is not None
        and source_origin is not None
        and request_origin == source_origin
    )


def request_host_is_loopback(host_header: str | None) -> bool:
    """Accept only a syntactically valid localhost or loopback-IP authority."""

    if not isinstance(host_header, str):
        return False
    authority = host_header.strip()
    if not authority or any(character.isspace() for character in authority):
        return False
    try:
        parsed = urlsplit(f"//{authority}")
        # Accessing ``port`` validates malformed or out-of-range values.
        parsed.port
    except ValueError:
        return False
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return False
    hostname = (parsed.hostname or "").casefold()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
