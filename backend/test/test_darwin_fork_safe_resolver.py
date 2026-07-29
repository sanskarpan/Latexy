"""
Unit tests for the macOS fork-safety resolver guard in app.core.celery_app.

Regression cover for the prefork SIGSEGV crash loop: macOS resolves AF_UNSPEC
lookups through Network.framework's NAT64 pass, which is not fork-safe, so a
prefork child segfaulted the first time a task resolved an external hostname
(api.openai.com). Pinning AF_INET is the only variant that survives.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import app.core.celery_app as ca


def _uninstall() -> None:
    """Undo the guard so each test starts from stock resolution."""
    if getattr(socket, "_latexy_ipv4_only", False):
        socket.getaddrinfo = socket._latexy_stock_getaddrinfo
        del socket._latexy_ipv4_only
        del socket._latexy_stock_getaddrinfo


class TestDarwinForkSafeResolver:
    def test_noop_off_darwin(self):
        """Linux/Docker keeps stock dual-stack resolution — fork is safe there."""
        stock = socket.getaddrinfo
        with patch.object(ca.sys, "platform", "linux"):
            ca._install_darwin_fork_safe_resolver()
        try:
            assert socket.getaddrinfo is stock
            assert not getattr(socket, "_latexy_ipv4_only", False)
        finally:
            _uninstall()

    def test_forces_ipv4_on_darwin(self):
        """AF_UNSPEC is rewritten to AF_INET, which skips the NAT64 pass."""
        calls = []
        with patch.object(ca.sys, "platform", "darwin"), \
                patch.object(socket, "getaddrinfo", lambda *a, **k: calls.append(a) or []):
            ca._install_darwin_fork_safe_resolver()
            try:
                socket.getaddrinfo("api.openai.com", 443)
                socket.getaddrinfo("api.openai.com", 443, socket.AF_UNSPEC)
            finally:
                _uninstall()

        assert [c[2] for c in calls] == [socket.AF_INET, socket.AF_INET]

    def test_preserves_explicit_family(self):
        """An explicit family is passed through untouched."""
        calls = []
        with patch.object(ca.sys, "platform", "darwin"), \
                patch.object(socket, "getaddrinfo", lambda *a, **k: calls.append(a) or []):
            ca._install_darwin_fork_safe_resolver()
            try:
                socket.getaddrinfo("::1", 443, socket.AF_INET6)
            finally:
                _uninstall()

        assert calls[0][2] == socket.AF_INET6

    def test_install_is_idempotent(self):
        """worker_process_init can run more than once without stacking wrappers."""
        with patch.object(ca.sys, "platform", "darwin"):
            ca._install_darwin_fork_safe_resolver()
            first = socket.getaddrinfo
            ca._install_darwin_fork_safe_resolver()
            try:
                assert socket.getaddrinfo is first
            finally:
                _uninstall()
