"""Exercise real local API -> Celery -> TeX -> private immutable artifacts.

One synthetic identity per invocation; normal anonymous quotas still apply.
The optional storage inspection is restricted to the isolated CI topology.
No provider calls, production credentials, source logging, or security probes.
"""

import argparse
import asyncio
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 25 * 1024 * 1024
HASH = re.compile(r"^[a-f0-9]{64}$")
MINIMAL_SOURCE = (
    "\\documentclass{article}\n\\begin{document}\n"
    "\\section{Experience}\n\\begin{itemize}\n"
    "\\item Local real worker smoke produced a verified artifact.\n"
    "\\end{itemize}\n\\end{document}\n"
)


def local_origin(value: str) -> str:
    target = urlsplit(value)
    try:
        port = target.port
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid local port") from None
    if (
        target.scheme != "http" or target.hostname not in {"localhost", "127.0.0.1", "::1"}
        or target.username or target.password or target.path not in {"", "/"}
        or target.query or target.fragment or port == 0
    ):
        raise argparse.ArgumentTypeError("Only a credential-free loopback HTTP origin is allowed")
    return value.rstrip("/")


def artifact_path(value: object, expected: str) -> str:
    # Never follow a server-supplied absolute URL or another job's capability.
    if value != expected:
        raise RuntimeError("Artifact URL does not match this submitted job")
    return expected


def hindi_fixture_path(script: Path) -> Path:
    fixture_root = script.resolve().parents[2]
    if (fixture_root / "backend").is_dir():
        fixture_root /= "backend"
    return fixture_root / "app/data/templates/ats_safe/hindi_professional.tex"


def unwrap_compile_result(envelope: object, job_id: str) -> dict:
    """Validate JobResultResponse separately from its worker result payload.

    Failed results, including typed delivery failures, are never acceptable
    compile evidence. Do not fall back to the obsolete flattened shape.
    """
    if (not isinstance(envelope, dict)
            or set(envelope) != {"success", "job_id", "result", "error"}
            or envelope.get("job_id") != job_id or envelope.get("success") is not True
            or envelope.get("error") is not None):
        raise RuntimeError("Compilation result envelope failed or did not match this job")
    result = envelope.get("result")
    if (not isinstance(result, dict) or result.get("success") is not True
            or result.get("job_id") != job_id or result.get("pdf_job_id") != job_id
            or result.get("error") is not None
            or not isinstance(result.get("artifact"), dict)
            or result["artifact"].get("job_id") != job_id):
        raise RuntimeError("Completed worker result did not publish this job's immutable artifact")
    return result


def validate_artifact(artifact: dict, job_id: str, source: str, compiler: str, pdf: bytes) -> str:
    artifact_id = artifact.get("artifact_id")
    if (
        not isinstance(artifact_id, str) or not HASH.fullmatch(artifact_id)
        or artifact.get("job_id") != job_id or artifact.get("compiler") != compiler
        or artifact.get("source_sha256") != hashlib.sha256(source.encode()).hexdigest()
        or artifact.get("pdf_sha256") != hashlib.sha256(pdf).hexdigest()
        or type(artifact.get("pdf_size")) is not int or artifact["pdf_size"] != len(pdf)
        or type(artifact.get("content_revision")) is not int or artifact["content_revision"] != 1
        or artifact.get("branch") != "draft" or artifact.get("document_id") != "guest"
        or type(artifact.get("page_count")) is not int or not 1 <= artifact["page_count"] <= 1000
    ):
        raise RuntimeError("Artifact PDF/source/revision identity is inconsistent")
    return artifact_id


def validate_geometry(geometry: dict, artifact: dict, *, require_boxes: bool) -> None:
    if (
        geometry.get("artifact_id") != artifact["artifact_id"]
        or geometry.get("pdf_sha256") != artifact["pdf_sha256"]
        or geometry.get("source_sha256") != artifact["source_sha256"]
        or geometry.get("content_revision") != artifact["content_revision"]
        or geometry.get("coordinate_system") != "pdf_points_top_left"
        or geometry.get("branch") != "draft"
        or len(geometry.get("pages", [])) != artifact["page_count"]
    ):
        raise RuntimeError("Geometry is not bound to the exact PDF/source revision")
    pages = {page["page"]: page for page in geometry["pages"]}
    boxes = geometry.get("boxes")
    if not isinstance(boxes, list) or (require_boxes and not boxes):
        raise RuntimeError("Literal smoke bullet has no verified PDF geometry")
    for box in boxes:
        page = pages.get(box.get("page"))
        numbers = [box.get(key) for key in ("x", "y", "width", "height")]
        if not page or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in numbers):
            raise RuntimeError("Geometry contains invalid PDF coordinates")
        x, y, width, height = numbers
        if not (x >= 0 and y >= 0 and width > 0 and height > 0
                and x + width <= page["width"] + 1 and y + height <= page["height"] + 1):
            raise RuntimeError("Geometry box falls outside the rendered page")


def request(base: str, path: str, fingerprint: str, payload=None) -> tuple[bytes, str]:
    body = json.dumps(payload).encode() if payload is not None else None
    with urlopen(Request(
        base + path, data=body,
        headers={"Content-Type": "application/json", "X-Device-Fingerprint": fingerprint},
    ), timeout=20) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Local response exceeds the smoke evidence bound")
        return data, response.headers.get_content_type()


async def inspect_isolated_storage(job_id: str, fingerprint: str, artifact: dict,
                                   pdf: bytes, synctex: bytes, geometry: dict) -> None:
    import asyncpg
    import boto3
    import redis
    from app.services.render_engine.artifacts import manifest_key, parse_manifest
    from botocore.config import Config

    if (os.environ.get("LATEXY_ISOLATED_CI") != "1"
            or os.environ.get("DATABASE_URL") != "postgresql+asyncpg://postgres@postgres:5432/latexy_ci_test"
            or os.environ.get("REDIS_URL") != "redis://redis:6379/0"
            or os.environ.get("MINIO_ENDPOINT") != "http://storage:9000"
            or not re.fullmatch(r"latexy-ci-[a-f0-9]{32}", os.environ.get("MINIO_BUCKET", ""))):
        raise RuntimeError("Storage verification requires the fresh isolated CI topology")
    connection = await asyncpg.connect(host="postgres", port=5432, user="postgres", database="latexy_ci_test")
    try:
        row = await connection.fetchrow(
            "SELECT state, user_id, job_type, pdf_path, pdf_size, pdf_sha256, result_payload "
            "FROM job_finalizations WHERE job_id = $1", job_id,
        )
        if (not row or row["state"] != "completed" or row["user_id"] is not None
                or row["job_type"] != "latex_compilation" or row["pdf_size"] != len(pdf)
                or row["pdf_sha256"] != artifact["pdf_sha256"]):
            raise RuntimeError("Durable finalization does not match this anonymous artifact")
        payload = json.loads(row["result_payload"])
        if payload.get("artifact") != artifact or payload.get("success") is not True:
            raise RuntimeError("Durable finalization payload differs from the API result")
        used = await connection.fetchval(
            "SELECT usage_count FROM device_trials WHERE device_fingerprint = $1", fingerprint,
        )
        if used != 1:
            raise RuntimeError("Normal device trial accounting was not preserved")
        with redis.Redis(host="redis", port=6379, db=0, socket_connect_timeout=5, socket_timeout=5) as transport:
            manifest = parse_manifest(transport.get(f"latexy:job:{job_id}:artifact"))
            meta = json.loads(transport.get(f"latexy:job:{job_id}:meta"))
            if (manifest.job_id != job_id or manifest.artifact_id != artifact["artifact_id"]
                    or manifest.owner_scope_kind != "device"
                    or manifest.owner_scope_sha256 != hashlib.sha256(f"device:{fingerprint}".encode()).hexdigest()
                    or meta.get("user_id") is not None or manifest.pdf.key != row["pdf_path"]):
                raise RuntimeError("Redis/DB artifact ownership or immutable pointer is inconsistent")
            if transport.exists(f"latexy:job:{job_id}:pdf"):
                raise RuntimeError("Admitted render unexpectedly stored PDF bytes in Redis")
        store = boto3.client("s3", endpoint_url="http://storage:9000",
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"], aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
            region_name="us-east-1", config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15))
        bucket = os.environ["MINIO_BUCKET"]
        for kind, expected in (("pdf", pdf), ("synctex", synctex), ("geometry", None)):
            reference = getattr(manifest, kind)
            if reference is None:
                raise RuntimeError("Required private artifact was not persisted")
            stream = store.get_object(Bucket=bucket, Key=reference.key)["Body"]
            try:
                stored = stream.read(reference.size + 1)
            finally:
                stream.close()
            if len(stored) != reference.size or hashlib.sha256(stored).hexdigest() != reference.sha256:
                raise RuntimeError("Private storage object differs from immutable manifest")
            if kind == "synctex":
                stored = gzip.decompress(stored)
            if expected is not None and stored != expected:
                raise RuntimeError("Private storage object differs from downloaded artifact")
            if kind == "geometry" and {**json.loads(stored), "artifact_id": manifest.artifact_id} != geometry:
                raise RuntimeError("Private geometry differs from downloaded artifact")
        stream = store.get_object(Bucket=bucket, Key=manifest_key(manifest.owner_scope_sha256, manifest.artifact_id))["Body"]
        try:
            if parse_manifest(stream.read(32 * 1024 + 1)) != manifest:
                raise RuntimeError("Private manifest differs from the Redis capability")
        finally:
            stream.close()
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_origin, default="http://localhost:8030")
    parser.add_argument("--engine", choices=("pdflatex", "xelatex", "lualatex"))
    parser.add_argument("--fixture", choices=("minimal", "hindi"), default="minimal")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--verify-isolated-storage", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("Timeout must be between 1 and 600 seconds")
    engine = args.engine or ("lualatex" if args.fixture == "hindi" else "pdflatex")
    if args.fixture == "hindi" and engine != "lualatex":
        parser.error("The shipped Hindi fixture requires LuaLaTeX/HarfBuzz shaping")
    source = (hindi_fixture_path(Path(__file__))
              .read_text(encoding="utf-8") if args.fixture == "hindi" else MINIMAL_SOURCE)
    fingerprint = "local-worker-smoke-" + uuid.uuid4().hex
    call = lambda path, payload=None: request(args.base_url, path, fingerprint, payload)
    raw, _ = call("/health")
    health = json.loads(raw)
    if health.get("status") != "healthy" or not health.get("latex_available"):
        raise RuntimeError("Local backend is not healthy with an available TeX engine")
    raw, _ = call("/jobs/submit", {"job_type": "latex_compilation", "latex_content": source,
        "compiler": engine, "device_fingerprint": fingerprint})
    submitted = json.loads(raw)
    if submitted.get("success") is not True:
        raise RuntimeError("Local job submission was not accepted")
    job_id = str(uuid.UUID(submitted["job_id"]))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            raw, _ = call(f"/jobs/{job_id}/result")
        except HTTPError as error:
            if error.code != 404:
                raise
            time.sleep(0.5)
            continue
        result = unwrap_compile_result(json.loads(raw), job_id)
        break
    else:
        raise RuntimeError(f"Timed out waiting for real worker: job {job_id}")
    state_deadline = time.monotonic() + 10
    while True:
        raw, _ = call(f"/jobs/{job_id}/state")
        state = json.loads(raw).get("status")
        if state == "completed":
            break
        if state in {"failed", "cancelled"} or time.monotonic() >= state_deadline:
            raise RuntimeError(f"Result and terminal state disagree: job {job_id}")
        time.sleep(0.1)
    pdf, media_type = call(f"/download/{job_id}")
    if media_type != "application/pdf" or not pdf.startswith(b"%PDF-"):
        raise RuntimeError("Downloaded artifact is not a PDF")
    artifact = result["artifact"]
    artifact_id = validate_artifact(artifact, job_id, source, engine, pdf)
    prefix = f"/download/{job_id}/preview/{artifact_id}"
    preview, preview_type = call(artifact_path(artifact.get("preview_url"), prefix))
    if preview_type != "application/pdf" or preview != pdf:
        raise RuntimeError("Preview and terminal export differ")
    synctex, media_type = call(prefix + "/synctex")
    if media_type != "text/plain" or not synctex.startswith(b"SyncTeX Version:"):
        raise RuntimeError("Downloaded SyncTeX is invalid")
    raw, media_type = call(artifact_path(artifact.get("geometry_url"), prefix + "/geometry"))
    geometry = json.loads(raw)
    if media_type != "application/json":
        raise RuntimeError("Geometry response is not JSON")
    validate_geometry(geometry, artifact, require_boxes=args.fixture == "minimal")
    with tempfile.TemporaryDirectory(prefix="latexy-smoke-pdf-") as directory:
        path = Path(directory) / "smoke.pdf"
        path.write_bytes(pdf)
        extracted = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=True, timeout=15).stdout
        expected = b"Local real worker smoke" if args.fixture == "minimal" else "आरव".encode()
        if expected not in extracted:
            raise RuntimeError("Real PDF extraction does not contain the fixture text")
    if args.verify_isolated_storage:
        asyncio.run(inspect_isolated_storage(job_id, fingerprint, artifact, pdf, synctex, geometry))
    report = {"engine": engine, "fixture": args.fixture, "job_id": job_id, "artifact_id": artifact_id,
        "source_sha256": artifact["source_sha256"], "pdf_sha256": artifact["pdf_sha256"],
        "pdf_bytes": len(pdf), "page_count": artifact["page_count"], "geometry_boxes": len(geometry["boxes"]),
        "synctex_bytes": len(synctex), "storage_verified": args.verify_isolated_storage, "success": True}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
