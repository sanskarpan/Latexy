"""Check local auth, durable output recovery, storage, and cancellation.

Start scripts/dev.sh with OPENAI_API_KEY='', RESEND_API_KEY='', and
BILLING_MODE=disabled first. This creates one synthetic local account/resume
and two retained jobs; it never reads developer credentials or calls providers.
With --include-jd, also exercises provider-free JD analysis and exact recovery
of a long requirement through the actual Celery worker. Deletes only freshly
created fixture jobs' four transport keys in local Redis DB 0
to simulate expiry; retained database/storage artifacts are never deleted.
Run using backend/.venv/bin/python. Account passwords/cookies are memory-only.
"""

import argparse
import asyncio
import hashlib
import json
import secrets
import time
import uuid
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def local_origin(value: str) -> str:
    target = urlsplit(value)
    if (
        target.scheme != "http"
        or target.hostname not in {"localhost", "127.0.0.1", "::1"}
        or target.username or target.password or target.path not in {"", "/"}
        or target.query or target.fragment
    ):
        raise argparse.ArgumentTypeError("Only credential-free loopback HTTP origins are allowed")
    try:
        _port = target.port
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid local port") from None
    return value.rstrip("/")


async def inspect_durable(job_id: str, user_id: str, resume_id: str, pdf: bytes | None = None) -> None:
    # Exact dev.sh database only: never inherit a production DATABASE_URL.
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1", port=5434, user="latexy", password="latexy_password", database="latexy",
    )
    try:
        row = await connection.fetchrow(
            """SELECT f.state, f.user_id::text AS owner, f.resume_id::text AS resume,
                      f.pdf_path, f.pdf_size, f.pdf_sha256, f.result_payload,
                      c.status, c.pdf_path AS compilation_pdf_path
               FROM job_finalizations f
               JOIN compilations c ON c.id = f.compilation_id
               WHERE f.job_id = $1""",
            job_id,
        )
        if not row or row["owner"] != user_id or row["resume"] != resume_id:
            raise RuntimeError("Durable job ownership/history was not committed")
        if pdf is None:
            if row["state"] != "cancelled" or row["status"] != "cancelled" or row["pdf_path"]:
                raise RuntimeError("Cancelled job has inconsistent durable history")
            return
        payload = json.loads(row["result_payload"])
        if (
            row["state"] != "completed" or row["status"] != "completed"
            or not row["pdf_path"] or row["pdf_path"] != row["compilation_pdf_path"]
            or row["pdf_size"] != len(pdf)
            or row["pdf_sha256"] != hashlib.sha256(pdf).hexdigest()
            or payload.get("job_id") != job_id or payload.get("success") is not True
        ):
            raise RuntimeError("Durable PDF/result metadata does not match downloaded output")
        # Inspect the exact local MinIO object as well as the Redis download.
        import boto3
        from botocore.config import Config

        store = boto3.client(
            "s3", endpoint_url="http://127.0.0.1:9000", aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin_secret", region_name="us-east-1",
            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15),
        )
        artifact = store.get_object(Bucket="latexy", Key=row["pdf_path"])["Body"]
        try:
            stored_pdf = artifact.read(len(pdf) + 1)
        finally:
            artifact.close()
        if stored_pdf != pdf:
            raise RuntimeError("Persisted storage object differs from the downloaded PDF")
    finally:
        await connection.close()


def expire_local_job_transport(job_id: str) -> None:
    """Simulate expiry for exactly one freshly created local fixture job."""
    canonical_id = str(uuid.UUID(job_id))
    if canonical_id != job_id:
        raise ValueError("A canonical fixture job UUID is required")
    import redis

    # Explicit local dev endpoint; never honor a provider URL from the env.
    transport = redis.Redis(
        host="127.0.0.1", port=6380, db=0,
        socket_connect_timeout=5, socket_timeout=5,
    )
    keys = [f"latexy:job:{canonical_id}:{suffix}" for suffix in ("meta", "state", "result", "pdf")]
    try:
        transport.delete(*keys)
        if transport.exists(*keys):
            raise RuntimeError("Fixture transport keys were not expired")
    finally:
        transport.close()


async def inspect_durable_jd(job_id: str, user_id: str, expected: dict) -> None:
    """Verify a non-PDF typed result in the exact isolated application database."""
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1", port=5434, user="latexy", password="latexy_password", database="latexy",
    )
    try:
        row = await connection.fetchrow(
            """SELECT state, user_id::text AS owner, job_type, result_payload, pdf_path
               FROM job_finalizations WHERE job_id = $1""",
            job_id,
        )
        if (
            not row or row["owner"] != user_id or row["state"] != "completed"
            or row["job_type"] != "job_description_analysis" or row["pdf_path"]
        ):
            raise RuntimeError("JD durable ownership/terminal type is inconsistent")
        payload = json.loads(row["result_payload"])
        if payload.get("success") is not True or payload.get("recovery_complete") is not True:
            raise RuntimeError("JD durable output is incomplete")
        for field in ("keywords", "requirements", "preferred_qualifications", "detected_industry", "analysis_metrics"):
            if payload.get(field) != expected.get(field):
                raise RuntimeError(f"JD durable output differs for {field}")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_origin, default="http://localhost:8030")
    parser.add_argument("--frontend-url", type=local_origin, default="http://localhost:5180")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--confirm-isolated-local-run", action="store_true")
    parser.add_argument("--include-jd", action="store_true", help="Also verify actual-worker JD durable recovery")
    args = parser.parse_args()
    if not args.confirm_isolated_local_run:
        parser.error("Confirm that this is dev.sh with email, AI, and billing disabled")
    if not 1 <= args.timeout <= 600:
        parser.error("Timeout must be between 1 and 600 seconds")
    if urlsplit(args.base_url).hostname != urlsplit(args.frontend_url).hostname:
        parser.error("Auth and API must use the same loopback hostname for cookies")
    authenticated = build_opener(HTTPCookieProcessor(CookieJar()))
    anonymous = build_opener()

    def request(origin: str, path: str, payload=None, method=None, *, unauthenticated=False):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", "Origin": args.frontend_url}
        opener = anonymous if unauthenticated else authenticated
        try:
            with opener.open(Request(origin + path, data=body, headers=headers, method=method), timeout=45) as response:
                return response.status, response.read(), response.headers.get_content_type()
        except HTTPError as error:
            # Never include server bodies, passwords, session cookies, or links.
            return error.code, b"", ""

    def json_request(origin: str, path: str, payload=None, method=None):
        status, body, _ = request(origin, path, payload, method)
        if status not in {200, 201}:
            raise RuntimeError(f"Local endpoint {path} returned HTTP {status}")
        return json.loads(body)

    health = json_request(args.base_url, "/health")
    if health.get("status") != "healthy" or not health.get("latex_available"):
        raise RuntimeError("Local backend is not healthy with TeX available")
    fixture = uuid.uuid4().hex
    signup = json_request(args.frontend_url, "/api/auth/sign-up/email", {
        "email": f"local-worker-smoke-{fixture}@example.invalid",
        "password": secrets.token_urlsafe(32), "name": "Local Worker Smoke",
    })
    user_id = str(uuid.UUID(signup["user"]["id"]))
    source = "\\documentclass{article}\n\\begin{document}\nOwned local worker smoke.\n\\end{document}\n"
    resume = json_request(args.base_url, "/resumes/", {"title": "Local worker smoke", "latex_content": source})
    resume_id = str(uuid.UUID(resume["id"]))

    def submit():
        result = json_request(args.base_url, "/jobs/submit", {
            "job_type": "latex_compilation", "latex_content": source, "compiler": "pdflatex",
            "metadata": {"resume_id": resume_id},
        })
        if result.get("success") is not True:
            raise RuntimeError("Owned local job was not accepted")
        return str(uuid.UUID(result["job_id"]))

    job_id = submit()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        status, body, _ = request(args.base_url, f"/jobs/{job_id}/result")
        if status == 404:
            time.sleep(0.5)
            continue
        if status != 200 or json.loads(body).get("success") is not True:
            raise RuntimeError(f"Owned compilation failed or was inaccessible: job {job_id}")
        break
    else:
        raise RuntimeError("Owned local compilation timed out")
    status, pdf, media_type = request(args.base_url, f"/download/{job_id}")
    if status != 200 or media_type != "application/pdf" or not pdf.startswith(b"%PDF-"):
        raise RuntimeError("Owned PDF download is invalid")
    asyncio.run(inspect_durable(job_id, user_id, resume_id, pdf))
    for path in (f"/jobs/{job_id}/result", f"/download/{job_id}"):
        if request(args.base_url, path, unauthenticated=True)[0] not in {403, 404}:
            raise RuntimeError("Unauthenticated caller could access owned output")

    expire_local_job_transport(job_id)
    recovered_result = json_request(args.base_url, f"/jobs/{job_id}/result")
    if recovered_result.get("success") is not True or recovered_result.get("job_id") != job_id:
        raise RuntimeError("Expired transport did not recover the owned result")
    if json_request(args.base_url, f"/jobs/{job_id}/state").get("status") != "completed":
        raise RuntimeError("Expired transport did not recover the terminal state")
    status, recovered_pdf, media_type = request(args.base_url, f"/download/{job_id}")
    if status != 200 or media_type != "application/pdf" or recovered_pdf != pdf:
        raise RuntimeError("Expired transport did not recover the exact persisted PDF")
    for path in (f"/jobs/{job_id}/state", f"/jobs/{job_id}/result", f"/download/{job_id}"):
        if request(args.base_url, path, unauthenticated=True)[0] not in {403, 404}:
            raise RuntimeError("Unauthenticated caller could access recovered owned output")
    # Read-only recovery must not recreate metadata or extend Redis retention.
    import redis

    with redis.Redis(host="127.0.0.1", port=6380, db=0, socket_connect_timeout=5, socket_timeout=5) as transport:
        if transport.exists(*(f"latexy:job:{job_id}:{suffix}" for suffix in ("meta", "state", "result", "pdf"))):
            raise RuntimeError("Recovery unexpectedly recreated fixture transport data")

    cancelled_job_id = submit()
    cancellation = json_request(args.base_url, f"/jobs/{cancelled_job_id}", method="DELETE")
    if cancellation.get("message") != "Cancellation requested":
        raise RuntimeError("Cancellation did not win the durable terminal decision")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            asyncio.run(inspect_durable(cancelled_job_id, user_id, resume_id))
            break
        except RuntimeError:
            time.sleep(0.5)
    else:
        raise RuntimeError("Cancelled compilation history was not reconciled")
    if json_request(args.base_url, f"/jobs/{cancelled_job_id}/state").get("status") != "cancelled":
        raise RuntimeError("Cancelled job polling disagrees with its durable decision")
    if request(args.base_url, f"/download/{cancelled_job_id}")[0] != 404:
        raise RuntimeError("Cancelled job exposed an artifact")
    summary = {"success": True, "owned_job_id": job_id, "cancelled_job_id": cancelled_job_id,
               "pdf_bytes": len(pdf), "durable_pdf_verified": True, "anonymous_access_denied": True,
               "expired_transport_recovery_verified": True}
    if args.include_jd:
        # No AI provider: this endpoint performs deterministic keyword extraction.
        # The requirement deliberately exceeds the old 2048-character truncation.
        requirement = "Python PostgreSQL reliable software services " * 115
        description = f"Required: {requirement}. Preferred: Kubernetes."
        submitted = json_request(args.base_url, "/ats/analyze-job-description", {
            "job_description": description, "async_processing": True,
        })
        if submitted.get("success") is not True:
            raise RuntimeError("Owned JD analysis was not accepted")
        jd_job_id = str(uuid.UUID(submitted["job_id"]))
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            status, body, _ = request(args.base_url, f"/jobs/{jd_job_id}/result")
            if status == 404:
                time.sleep(0.5)
                continue
            if status != 200 or json.loads(body).get("success") is not True:
                raise RuntimeError("Owned JD analysis failed or was inaccessible")
            break
        else:
            raise RuntimeError("Owned JD analysis timed out")
        expected = json.loads(body).get("result")
        if (
            not isinstance(expected, dict) or expected.get("requirements") != [requirement]
            or expected.get("preferred_qualifications") != ["Kubernetes"]
            or expected.get("pdf_job_id") is not None
        ):
            raise RuntimeError("JD output lost its exact requirement or advertised a PDF")
        asyncio.run(inspect_durable_jd(jd_job_id, user_id, expected))
        expire_local_job_transport(jd_job_id)
        recovered = json_request(args.base_url, f"/jobs/{jd_job_id}/result")
        if recovered.get("success") is not True or recovered.get("job_id") != jd_job_id:
            raise RuntimeError("Expired JD transport did not recover its owned result")
        recovered_payload = recovered.get("result", {})
        for field in ("keywords", "requirements", "preferred_qualifications", "detected_industry", "analysis_metrics"):
            if recovered_payload.get(field) != expected.get(field):
                raise RuntimeError(f"JD expired recovery differs for {field}")
        if json_request(args.base_url, f"/jobs/{jd_job_id}/state").get("status") != "completed":
            raise RuntimeError("JD expired recovery lost its terminal state")
        for path in (f"/jobs/{jd_job_id}/state", f"/jobs/{jd_job_id}/result"):
            if request(args.base_url, path, unauthenticated=True)[0] not in {403, 404}:
                raise RuntimeError("Unauthenticated caller could recover owned JD output")
        if request(args.base_url, f"/download/{jd_job_id}")[0] != 404:
            raise RuntimeError("Non-PDF JD job exposed a download artifact")
        with redis.Redis(host="127.0.0.1", port=6380, db=0, socket_connect_timeout=5, socket_timeout=5) as transport:
            if transport.exists(*(f"latexy:job:{jd_job_id}:{suffix}" for suffix in ("meta", "state", "result", "pdf"))):
                raise RuntimeError("JD recovery unexpectedly recreated transport data")
        summary.update({"jd_job_id": jd_job_id, "jd_exact_durable_recovery_verified": True})
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
