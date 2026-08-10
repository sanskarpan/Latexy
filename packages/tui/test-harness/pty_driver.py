#!/usr/bin/env python3
"""
Drive the built CLI inside a real pty and report what the terminal shows.

Why this exists: `ink-testing-library@4` does not deliver keystrokes to Ink 5. A
minimal `useInput` probe that appends every character it receives renders `[]`
after two writes to its stdin, with and without CI set. So the only way to test
keyboard behaviour is a real pty — and without it, three separate keyboard fixes
shipped wrong (the Ctrl+L repair twice, the paste handler once).

`script(1)` is not usable here: under piped stdio it fails with
`tcgetattr/ioctl: Operation not supported on socket`. Hence pty.fork().

Two hard-won details, both of which produced false failures before they were
understood:

  * Keystrokes must be paced. Writing "hello\\r" in one call — or even one byte
    at a time too quickly — lets the pty coalesce them into a single read, and
    Ink parses the chunk as one key event with the \\r landing as a literal
    character. That looks exactly like "Enter does not submit". PACE below is
    deliberately generous.

  * The child must be reaped while the master fd is drained. Breaking out of the
    read loop on EIO without waitpid leaves a zombie, and a child blocked
    mid-write to a full pty never exits — which looks exactly like "Ctrl+C does
    not exit".

Usage:  pty_driver.py <scenario>   ->  one JSON object on stdout
"""
from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time

PACE = 0.12          # seconds between keystrokes
ROWS, COLS = 34, 110


class StubBackend:
    """
    The smallest server that gets the app past its login overlay.

    app.tsx validates the stored token with `GET /me` and opens LoginOverlay when
    that fails. With the overlay up, PromptInput renders its blocked branch and
    has no text input at all — so every keyboard scenario silently tested nothing.
    Serving /me locally keeps the harness self-contained: no backend, no database,
    nothing to start in CI.
    """

    def __init__(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:            # noqa: N802
                if self.path.startswith("/me"):
                    self._json(200, {"id": "00000000-0000-4000-8000-000000000000",
                                     "email": "pty@harness.test", "plan": "free"})
                elif self.path.startswith("/health"):
                    self._json(200, {"status": "healthy"})
                elif self.path.startswith("/resumes"):
                    self._json(200, {"resumes": [], "total": 0})
                else:
                    self._json(404, {"detail": "Not Found"})

            def log_message(self, *_args) -> None:   # silence request logging
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

# Ink's alternate-screen and cursor sequences, plus OSC strings.
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>]")

CTRL_C, CTRL_L, CTRL_A = "\x03", "\x0c", "\x01"


class Session:
    def __init__(self) -> None:
        self.xdg = tempfile.mkdtemp(prefix="latexy-pty-")
        self.backend = StubBackend()
        env = dict(os.environ)
        # Never the developer's real config: /logout calls clearConfig().
        env["XDG_CONFIG_HOME"] = self.xdg
        # Any non-empty token is enough: the stub above answers /me, which is what
        # app.tsx checks before deciding whether to open the login overlay.
        env["LATEXY_SESSION_TOKEN"] = "pty-harness-not-a-real-token"
        env["LATEXY_API_URL"] = self.backend.url
        env["LATEXY_APP_URL"] = self.backend.url
        env.pop("CI", None)          # CI=true would route to headless mode
        env.pop("LATEXY_PASSWORD", None)

        self.buf = ""
        self.raw = ""
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(os.path.join(os.path.dirname(__file__), ".."))
            os.execve("/usr/bin/env", ["env", "node", "dist/cli.js"], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            self.raw += chunk.decode("utf-8", "replace")
            self.buf = ANSI.sub("", self.raw)

    def await_prompt(self, timeout: float = 20.0) -> bool:
        """Block until the prompt is focused, i.e. no overlay is covering it."""
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.3)
            if "overlay open" not in self.buf.splitlines()[-6:].__str__() and "❯" in self.buf:
                # The last frame must show the input, not a stale earlier one.
                tail = "\n".join(self.buf.splitlines()[-12:])
                if "❯" in tail and "Sign in to Latexy" not in tail:
                    return True
        return False

    def type(self, text: str, settle: float = 1.0) -> None:
        for ch in text:
            os.write(self.fd, ch.encode())
            time.sleep(PACE)
        self.pump(settle)

    def enter(self, settle: float = 2.0) -> None:
        """Send Enter as its own write, well after the last character."""
        time.sleep(0.3)
        os.write(self.fd, b"\r")
        self.pump(settle)

    def prompt(self) -> str:
        """The prompt line's contents, glyph and placeholder stripped."""
        for line in reversed(self.buf.splitlines()):
            if "❯" in line:
                text = line.split("❯", 1)[1].replace("│", "").strip()
                return "" if text.startswith("Ask anything") else text
        return "<no prompt line found>"

    def transcript_has(self, needle: str) -> bool:
        return needle in self.buf

    def close(self, expect_exit: bool = False) -> dict:
        """Reap while draining, so a child blocked on write can still exit."""
        result = {"exited": False, "exit_code": None, "exit_seconds": None}
        start = time.time()
        if not expect_exit:
            # Nothing has asked it to quit, so do not sit waiting out the full
            # exit budget for every scenario — that alone cost ~12s each.
            os.kill(self.pid, signal.SIGTERM)
        deadline = start + (12 if expect_exit else 3)
        while time.time() < deadline:
            try:
                wpid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                result["exited"] = True
                break
            if wpid:
                result["exited"] = True
                result["exit_code"] = os.waitstatus_to_exitcode(status) if hasattr(
                    os, "waitstatus_to_exitcode") else (status >> 8)
                result["exit_seconds"] = round(time.time() - start, 2)
                break
            self.pump(0.2)      # keep draining or the child may block on write
        if not result["exited"]:
            os.kill(self.pid, signal.SIGKILL)
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
        os.close(self.fd)
        self.backend.stop()
        shutil.rmtree(self.xdg, ignore_errors=True)
        return result


# --- scenarios ------------------------------------------------------------
# Each returns a dict that the vitest wrapper asserts on.

def s_boot() -> dict:
    s = Session(); ready = s.await_prompt()
    out = {"booted": "Latexy" in s.buf, "has_prompt": "❯" in s.buf, "ready": ready,
           "no_crash": "at Object." not in s.buf and "Error:" not in s.buf}
    out.update(s.close())
    return out


def s_slash_menu() -> dict:
    s = Session(); ready = s.await_prompt()
    s.type("/", settle=1.5)
    shown = s.buf
    out = {"suggestions_visible": "Commands" in shown or "/compile" in shown,
           "prompt": s.prompt()}
    out.update(s.close())
    return out


def _ctrl_l_case(prefix: str) -> dict:
    s = Session(); ready = s.await_prompt()
    if prefix:
        s.type(prefix, settle=1.0)
    s.type(CTRL_L, settle=1.5)
    out = {"prompt": s.prompt()}
    out.update(s.close())
    return out


def s_ctrl_l_empty() -> dict:        return _ctrl_l_case("")
def s_ctrl_l_text() -> dict:         return _ctrl_l_case("hello")
def s_ctrl_l_trailing_l() -> dict:   return _ctrl_l_case("abcl")


def s_ctrl_a_text() -> dict:
    s = Session(); ready = s.await_prompt()
    s.type("abc", settle=1.0)
    s.type(CTRL_A, settle=1.5)
    out = {"prompt": s.prompt()}
    out.update(s.close())
    return out


def s_ctrl_c_keeps_c() -> dict:
    """ink-text-input does not append for Ctrl+C, so a real trailing c must survive."""
    s = Session(); ready = s.await_prompt()
    s.type("abc", settle=1.0)
    before = s.prompt()
    os.write(s.fd, CTRL_C.encode())
    res = s.close(expect_exit=True)
    return {"prompt_before_exit": before, **res}


def s_typing_l() -> dict:
    s = Session(); ready = s.await_prompt()
    s.type("llama", settle=1.5)
    out = {"prompt": s.prompt()}
    out.update(s.close())
    return out


def s_paste_single() -> dict:
    """A pasted command arrives as one chunk including its newline."""
    s = Session(); ready = s.await_prompt()
    os.write(s.fd, b"/help\r")
    s.pump(3)
    out = {"submitted": s.transcript_has("Available commands") or s.transcript_has("/compile"),
           "prompt": s.prompt()}
    out.update(s.close())
    return out


def s_paste_multi() -> dict:
    s = Session(); ready = s.await_prompt()
    # Two commands with distinct, additive output. An earlier version used /clear
    # and asserted on its ABSENCE, which can never work here: this buffer keeps
    # everything ever emitted, so a cleared transcript still contains the old text.
    os.write(s.fd, b"/help\r/health\r")
    s.pump(5)
    out = {"prompt": s.prompt(),
           "first_ran": s.transcript_has("Available commands"),
           "second_ran": s.transcript_has("Backend status")}
    out.update(s.close())
    return out


def s_paste_blank_first() -> dict:
    s = Session(); ready = s.await_prompt()
    os.write(s.fd, b"\n/help\r")
    s.pump(3)
    out = {"submitted": s.transcript_has("Available commands") or s.transcript_has("/compile"),
           "prompt": s.prompt()}
    out.update(s.close())
    return out


def s_paste_incomplete_tail() -> dict:
    """No trailing newline: the last line must stay in the box, unsubmitted."""
    s = Session(); ready = s.await_prompt()
    os.write(s.fd, b"/help\r/clear")
    s.pump(3)
    out = {"prompt": s.prompt()}
    out.update(s.close())
    return out


def s_ctrl_c_exits() -> dict:
    s = Session(); ready = s.await_prompt()
    os.write(s.fd, CTRL_C.encode())
    return s.close(expect_exit=True)


SCENARIOS = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("s_")}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        print(json.dumps({"error": "unknown scenario",
                          "available": sorted(SCENARIOS)}), flush=True)
        sys.exit(2)
    print(json.dumps(SCENARIOS[sys.argv[1]]()), flush=True)
