"""Shared egress guard: public-address admission and fixed-origin enforcement.

One reviewed boundary now backs the job scraper, URL import and the fixed-origin
provider clients. These cases pin the properties that make it a guard rather
than a convention:

* non-http(s) schemes and any non-public resolved address are refused;
* a constructed provider URL cannot leave its configured origin, which is what
  makes the fixed-host call sites (GitHub, Crossref, Zotero) provably safe even
  though a user-influenced value reaches the path;
* the path-segment allowlist admits only inert characters.
"""

import socket

import pytest

from app.core import egress_guard
from app.core.egress_guard import (
    OriginMismatchError,
    SSRFError,
    SSRFGuardTransport,
    assert_public_url,
    assert_within_origin,
    guarded_async_client,
    host_is_public,
    ip_is_public,
    validate_path_segment,
)


def _resolves_to(*addresses: str):
    """Patch DNS resolution for the host under test."""
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addresses]
    return lambda host, port: infos


class TestIpAdmission:
    @pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111"])
    def test_public_addresses_allowed(self, address):
        assert ip_is_public(address) is True

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",          # loopback
            "10.0.0.1",           # RFC1918
            "192.168.1.1",        # RFC1918
            "172.16.0.1",         # RFC1918
            "169.254.169.254",    # cloud metadata / link-local
            "100.64.0.1",         # carrier-grade NAT (shared address space)
            "0.0.0.0",            # unspecified
            "224.0.0.1",          # multicast
            "::1",                # IPv6 loopback
            "fc00::1",            # IPv6 unique-local
            "fe80::1",            # IPv6 link-local
            "::ffff:127.0.0.1",   # IPv4-mapped loopback
        ],
    )
    def test_non_public_addresses_refused(self, address):
        assert ip_is_public(address) is False

    def test_garbage_is_refused(self):
        assert ip_is_public("not-an-ip") is False

    def test_host_with_any_private_answer_is_refused(self, monkeypatch):
        monkeypatch.setattr(egress_guard.socket, "getaddrinfo", _resolves_to("8.8.8.8", "127.0.0.1"))
        assert host_is_public("mixed.example") is False

    def test_unresolvable_host_is_refused(self, monkeypatch):
        def fail(host, port):
            raise socket.gaierror("name resolution failed")

        monkeypatch.setattr(egress_guard.socket, "getaddrinfo", fail)
        assert host_is_public("nope.invalid") is False

    def test_empty_host_is_refused(self):
        assert host_is_public("") is False


class TestPublicUrlAssertion:
    @pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "data", "javascript"])
    def test_non_http_schemes_refused(self, scheme):
        with pytest.raises(SSRFError, match="non-http"):
            assert_public_url(f"{scheme}://example.com/x")

    def test_private_host_refused(self, monkeypatch):
        monkeypatch.setattr(egress_guard.socket, "getaddrinfo", _resolves_to("169.254.169.254"))
        with pytest.raises(SSRFError, match="non-public"):
            assert_public_url("http://metadata.example/latest")

    def test_public_host_admitted(self, monkeypatch):
        monkeypatch.setattr(egress_guard.socket, "getaddrinfo", _resolves_to("93.184.216.34"))
        assert_public_url("https://example.com/portfolio")


class TestFixedOrigin:
    def test_same_origin_accepted(self):
        assert_within_origin("https://api.github.com/repos/a/b", "https://api.github.com")

    def test_case_and_default_port_do_not_change_the_origin(self):
        assert_within_origin("https://API.GitHub.com/repos/a/b", "https://api.github.com")

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example/repos/a/b",
            "https://api.github.com.evil.example/repos/a/b",
            "http://api.github.com/repos/a/b",           # downgraded scheme
            "https://api.github.com:8443/repos/a/b",     # unexpected port
            "https://user:pass@evil.example/repos/a/b",
        ],
    )
    def test_departures_from_the_origin_are_refused(self, url):
        with pytest.raises(OriginMismatchError):
            assert_within_origin(url, "https://api.github.com")

    def test_origin_mismatch_is_an_ssrf_error(self):
        """Callers that already catch SSRFError keep working."""
        assert issubclass(OriginMismatchError, SSRFError)


class TestPathSegment:
    @pytest.mark.parametrize("value", ["resume", "user_1.2-3", "a~b", "A1", "x" * 255])
    def test_inert_values_accepted(self, value):
        assert validate_path_segment(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "../../etc/passwd",
            "a/b",
            "a\\b",
            "a%2Fb",
            "a?x=1",
            "a#frag",
            "a@evil.example",
            "a:80",
            "a b",
            "a\nb",
            "",
            "x" * 256,
        ],
    )
    def test_active_values_refused(self, value):
        with pytest.raises(ValueError):
            validate_path_segment(value)

    def test_none_refused(self):
        with pytest.raises(ValueError):
            validate_path_segment(None)


class TestGuardedClient:
    def test_transport_is_always_the_guard(self):
        client = guarded_async_client(timeout=5)
        assert isinstance(client._transport, SSRFGuardTransport)

    def test_caller_cannot_override_the_transport(self):
        """A later edit must not be able to silently drop the guard."""
        import httpx

        client = guarded_async_client(transport=httpx.AsyncHTTPTransport(), timeout=5)
        assert isinstance(client._transport, SSRFGuardTransport)

    async def test_transport_refuses_a_private_target(self, monkeypatch):
        import httpx

        monkeypatch.setattr(egress_guard.socket, "getaddrinfo", _resolves_to("127.0.0.1"))
        transport = SSRFGuardTransport()
        request = httpx.Request("GET", "http://internal.example/admin")
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await transport.handle_async_request(request)

    async def test_transport_refuses_a_non_http_scheme(self):
        import httpx

        transport = SSRFGuardTransport()
        request = httpx.Request("GET", "http://example.com/")
        request.url = request.url.copy_with(scheme="ftp")
        with pytest.raises(httpx.UnsupportedProtocol):
            await transport.handle_async_request(request)
