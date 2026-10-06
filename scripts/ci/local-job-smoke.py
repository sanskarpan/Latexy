"""Exercise real local API → Celery → TeX → Redis → PDF download wiring.

No mocks, paid AI calls, credentials, or remote URLs. Each invocation consumes
one anonymous local trial and retains its job artifacts under normal retention.
Run only after the local launcher and worker have started.
"""

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8030")
    parser.add_argument("--engine", choices=("pdflatex", "xelatex", "lualatex"))
    parser.add_argument("--fixture", choices=("minimal", "hindi"), default="minimal")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    target = urlsplit(base)
    if (
        target.scheme != "http" or target.hostname not in {"localhost", "127.0.0.1", "::1"}
        or target.username or target.password or target.path or target.query or target.fragment
    ):
        parser.error("Only a credential-free loopback HTTP origin is allowed")
    if not 1 <= args.timeout <= 600:
        parser.error("Timeout must be between 1 and 600 seconds")
    engine = args.engine or ("lualatex" if args.fixture == "hindi" else "pdflatex")
    if args.fixture == "hindi" and engine != "lualatex":
        parser.error("The shipped Hindi fixture requires LuaLaTeX/HarfBuzz shaping")
    if args.fixture == "hindi":
        # Fixed repository-owned source, never an arbitrary user document or
        # dotenv path. Exercise the same fonts/packages as the shipped gallery.
        source = (
            Path(__file__).resolve().parents[2]
            / "backend/app/data/templates/ats_safe/hindi_professional.tex"
        ).read_text(encoding="utf-8")
    else:
        source = (
            "\\documentclass{article}\n\\begin{document}\n"
            "Local real-worker smoke.\n\\end{document}\n"
        )

    def request(path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        with urlopen(Request(
            base + path, data=body, headers={"Content-Type": "application/json"},
        ), timeout=20) as response:
            return response.read(), response.headers.get_content_type()

    raw, _ = request("/health")
    health = json.loads(raw)
    if health.get("status") != "healthy" or not health.get("latex_available"):
        raise RuntimeError("Local backend is not healthy with an available TeX engine")

    raw, _ = request("/jobs/submit", {
        "job_type": "latex_compilation",
        "latex_content": source,
        "compiler": engine,
        "device_fingerprint": "local-worker-smoke-" + uuid.uuid4().hex,
    })
    submitted = json.loads(raw)
    if submitted.get("success") is not True:
        raise RuntimeError("Local job submission was not accepted")
    job_id = str(uuid.UUID(submitted["job_id"]))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            raw, _ = request(f"/jobs/{job_id}/result")
        except HTTPError as error:
            if error.code != 404:
                raise
            time.sleep(0.5)
            continue
        result = json.loads(raw)
        if result.get("success") is not True:
            # Do not log source or provider error text from a failed payload.
            raise RuntimeError(f"Local compilation failed: job {job_id}")
        break
    else:
        raise RuntimeError(f"Timed out waiting for real worker: job {job_id}")

    # The result is deliberately committed before its completion event/state.
    # Allow bounded delivery latency without accepting a permanently stuck job.
    state_deadline = time.monotonic() + 10
    while True:
        raw, _ = request(f"/jobs/{job_id}/state")
        state = json.loads(raw).get("status")
        if state == "completed":
            break
        if state in {"failed", "cancelled"} or time.monotonic() >= state_deadline:
            raise RuntimeError(f"Result and terminal state disagree: job {job_id}")
        time.sleep(0.1)
    pdf, media_type = request(f"/download/{job_id}")
    if media_type != "application/pdf" or not pdf.startswith(b"%PDF-"):
        raise RuntimeError("Downloaded artifact is not a PDF")
    print(json.dumps({
        "engine": engine, "fixture": args.fixture, "job_id": job_id,
        "pdf_bytes": len(pdf), "success": True,
    }))


if __name__ == "__main__":
    main()
