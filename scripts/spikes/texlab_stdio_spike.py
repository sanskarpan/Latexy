#!/usr/bin/env python3
"""Exercise the texlab capabilities Latexy would consume over LSP stdio.

This is deliberately dependency-free and does not write source files. Pass a
texlab binary explicitly so CI and developer machines do not silently depend
on whichever version happens to be on PATH.
"""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def _send(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode()
    assert process.stdin is not None
    process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
    process.stdin.flush()


def _receive(process: subprocess.Popen[bytes], timeout: float) -> list[dict[str, Any]]:
    assert process.stdout is not None
    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            [process.stdout], [], [], max(0, deadline - time.monotonic())
        )
        if not ready:
            break
        headers: dict[str, str] = {}
        while True:
            line = process.stdout.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length:
            messages.append(json.loads(process.stdout.read(length)))
    return messages


def _labels(response: dict[str, Any]) -> list[str]:
    result = response.get("result") or []
    items = result.get("items", []) if isinstance(result, dict) else result
    return [item["label"] for item in items if isinstance(item, dict) and "label" in item]


def run(texlab: Path) -> dict[str, Any]:
    version = subprocess.run(
        [str(texlab), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    process = subprocess.Popen(
        [str(texlab)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    messages: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="latexy-texlab-spike-") as workspace:
            root_uri = Path(workspace).as_uri()
            tex_uri = f"{root_uri}/main.tex"
            bib_uri = f"{root_uri}/refs.bib"
            source = (
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\section{Introduction}\n"
                "\\label{sec:intro}\n"
                "See \\ref{sec:}\n"
                "Prior work \\cite{do}\n"
                "\\bibliography{refs}\n"
                "\\end{document}\n"
            )
            bibliography = (
                "@article{doe2024,\n"
                "  title={Useful Paper},\n"
                "  author={Doe, Jane},\n"
                "  year={2024}\n"
                "}\n"
            )
            _send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "processId": None,
                        "rootUri": root_uri,
                        "capabilities": {},
                        "workspaceFolders": [{"uri": root_uri, "name": "latexy-spike"}],
                    },
                },
            )
            messages.extend(_receive(process, 2))
            _send(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
            for uri, language_id, text in (
                (tex_uri, "latex", source),
                (bib_uri, "bibtex", bibliography),
            ):
                _send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/didOpen",
                        "params": {
                            "textDocument": {
                                "uri": uri,
                                "languageId": language_id,
                                "version": 1,
                                "text": text,
                            }
                        },
                    },
                )
            time.sleep(0.5)
            requests = (
                (2, "textDocument/completion", {"textDocument": {"uri": tex_uri}, "position": {"line": 4, "character": 13}}),
                (3, "textDocument/completion", {"textDocument": {"uri": tex_uri}, "position": {"line": 5, "character": 19}}),
                (4, "textDocument/documentSymbol", {"textDocument": {"uri": tex_uri}}),
                (5, "textDocument/hover", {"textDocument": {"uri": tex_uri}, "position": {"line": 2, "character": 3}}),
            )
            for request_id, method, params in requests:
                _send(
                    process,
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                )
            messages.extend(_receive(process, 6))
    finally:
        if process.poll() is None:
            _send(process, {"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None})
            _receive(process, 1)
            _send(process, {"jsonrpc": "2.0", "method": "exit", "params": None})
            process.wait(timeout=2)

    responses = {message.get("id"): message for message in messages if "id" in message}
    capabilities = responses.get(1, {}).get("result", {}).get("capabilities", {})
    result = {
        "texlab": version,
        "providers": {
            "completion": bool(capabilities.get("completionProvider")),
            "document_symbols": bool(capabilities.get("documentSymbolProvider")),
            "hover": bool(capabilities.get("hoverProvider")),
        },
        "reference_completion": "sec:intro" in _labels(responses.get(2, {})),
        "citation_completion": "doe2024" in _labels(responses.get(3, {})),
        "document_symbols": [
            item.get("name")
            for item in (responses.get(4, {}).get("result") or [])
            if isinstance(item, dict)
        ],
        "errors": [message["error"] for message in messages if "error" in message],
    }
    if not (
        all(result["providers"].values())
        and result["reference_completion"]
        and result["citation_completion"]
        and "Introduction" in result["document_symbols"]
        and not result["errors"]
    ):
        raise RuntimeError(f"texlab spike failed: {json.dumps(result, indent=2)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texlab", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.texlab.resolve())
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
