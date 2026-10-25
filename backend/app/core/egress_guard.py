"""Shared egress guard for every user-influenced outbound HTTP request.

One implementation is shared by the job scraper, URL import and the fixed-origin
provider clients (GitHub, Crossref, Zotero). Three distinct problems are covered:

1. **Arbitrary-destination requests.** ``SSRFGuardTransport`` validates and
   DNS-pins every request target, including redirect hops, so a private,
   loopback, link-local or carrier-grade-NAT destination is refused and a
   rebinding answer cannot be swapped in after validation.
2. **Fixed-provider requests.** ``assert_within_origin`` proves a constructed URL
   still points at the provider origin it was meant for, even if a value that
   reached the path contained a scheme, authority or traversal sequence.
3. **Segment injection.** ``validate_path_segment`` restricts a caller-supplied
   value to a conservative charset before it is interpolated into a path.

The guard is deliberately a transport, not a pre-flight check: validation
followed by a plain hostname request has a time-of-check/time-of-use race, and a
redirect can leave the validated host entirely.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx


class SSRFError(Exception):
    """Raised when a requested URL resolves to a non-public address."""


class OriginMismatchError(SSRFError):
    """Raised when a constructed URL left its intended provider origin."""


# Conservative allowlist for a value interpolated into a URL path segment.
# Deliberately excludes ``/``, ``\\``, ``%``, ``@``, ``:``, ``?``, ``#`` and all
# whitespace so a caller cannot introduce a new authority, a traversal sequence,
# a query delimiter or a second encoding round.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,255}$")


def validate_path_segment(value: object, *, field: str = "identifier") -> str:
    """Return a path-safe segment or raise ``ValueError``.

    This is intentionally stricter than percent-encoding: an encoded slash is
    still a slash to many upstreams, and double-encoding is a recurring source
    of bypasses. Only characters that are inert in a path segment are accepted.
    """
    text = "" if value is None else str(value)
    if not _SAFE_SEGMENT.fullmatch(text):
        raise ValueError(f"Unsupported {field} for an outbound request")
    return text


def _origin_of(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise OriginMismatchError("Outbound URL has an invalid port") from exc
    return scheme, host, port


def assert_within_origin(url: str, origin: str) -> None:
    """Require ``url`` to target exactly the fixed ``origin``.

    Guards every fixed-provider call site: the provider origin is a constant, so
    a request that resolves anywhere else is a defect or an attack, not a
    supported configuration.
    """
    expected = _origin_of(origin)
    actual = _origin_of(url)
    if actual != expected:
        raise OriginMismatchError("Outbound request left its configured provider origin")


def ip_is_public(ip_str: str) -> bool:
    """True only for a globally routable unicast address."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # Shared address space (100.64.0.0/10) is neither private nor global.
    # Negating only the private/reserved flags admits carrier or VPN-local
    # destinations, including their IPv4-mapped IPv6 representations.
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def host_is_public(host: str) -> bool:
    """Resolve host and require every resolved address to be public."""
    return bool(resolve_public_addresses(host))


def resolve_public_addresses(host: str) -> tuple[str, ...]:
    """Resolve once, reject mixed/private answers, and return normalized IPs."""
    if not host:
        return ()
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return ()
    addresses = tuple(sorted({str(ipaddress.ip_address(info[4][0])) for info in infos}))
    return addresses if addresses and all(ip_is_public(ip) for ip in addresses) else ()


def assert_public_url(url: str) -> None:
    """Reject a non-http(s) scheme or a host with any non-public address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Blocked non-http(s) URL scheme: {parsed.scheme!r}")
    if not host_is_public(parsed.hostname or ""):
        raise SSRFError(f"Blocked request to non-public host: {parsed.hostname!r}")


class SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """Validate and DNS-pin every request target, including redirect hops.

    Validation followed by an ordinary hostname request has a DNS-rebinding
    race: an attacker can return a public address for validation and a private
    one for the transport's second lookup. Rewriting the connection URL to the
    already-validated IP removes that second lookup. The original Host header
    and TLS SNI name are preserved for virtual hosting and certificate checks.
    """

    def __init__(self, **transport_options: Any) -> None:
        super().__init__(**transport_options)
        self._transport_options = transport_options
        self._host_transports: dict[str, httpx.AsyncHTTPTransport] = {}
        self._transport_lock = asyncio.Lock()

    async def _transport_for(self, host: str) -> httpx.AsyncHTTPTransport:
        async with self._transport_lock:
            transport = self._host_transports.get(host)
            if transport is None:
                transport = httpx.AsyncHTTPTransport(**self._transport_options)
                self._host_transports[host] = transport
            return transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme not in ("http", "https"):
            raise httpx.UnsupportedProtocol(
                f"Blocked non-http(s) scheme: {request.url.scheme!r}", request=request
            )
        original_host = request.url.host
        addresses = await asyncio.to_thread(resolve_public_addresses, original_host)
        if not addresses:
            raise httpx.ConnectError(
                f"Blocked request to non-public host: {original_host!r}", request=request
            )
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = original_host
        pinned_request = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        # Keep pools separated by the original host. Two unrelated TLS hosts can
        # legitimately share an IP; pooling solely by the pinned IP could reuse a
        # connection authenticated for the wrong hostname.
        transport = await self._transport_for(original_host)
        response = await transport.handle_async_request(pinned_request)
        # Redirect resolution and caller-visible diagnostics must retain the
        # public hostname, not expose or resolve relative to the pinned IP.
        response.request = request
        return response

    async def aclose(self) -> None:
        async with self._transport_lock:
            transports = list(self._host_transports.values())
            self._host_transports.clear()
        for transport in transports:
            await transport.aclose()
        await super().aclose()


def guarded_async_client(**options: Any) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` whose egress is always guarded.

    Callers supply only descriptive options (headers, timeout, redirects). The
    transport is never caller-selectable, so a guarded call site cannot silently
    lose its guard during a later edit.
    """
    options.pop("transport", None)
    return httpx.AsyncClient(transport=SSRFGuardTransport(), **options)
