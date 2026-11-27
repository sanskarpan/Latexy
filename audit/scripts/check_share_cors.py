#!/usr/bin/env python3
"""Regression check: R2 shared-PDF CORS and HTTP Range support.

Creates a tiny object in the configured R2 bucket, presigns it, and asserts:
- a GET with an allowed Origin returns Access-Control-Allow-Origin;
- a Range GET returns 206 plus Content-Range and the exposed header;
- a disallowed Origin does not receive Access-Control-Allow-Origin.

Requires the same R2_* / MINIO_* env vars used by the backend. The test object is
deleted even when an assertion fails. Run from the repository root:

    backend/.venv/Scripts/python.exe audit/scripts/check_share_cors.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import boto3
import requests
from botocore.config import Config
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="https://latexy.xyz")
    parser.add_argument("--disallowed-origin", default="https://evil.example")
    parser.add_argument("--bucket", default=os.environ.get("MINIO_BUCKET", "latexy"))
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    endpoint = os.environ.get("R2_API_ENDPOINT")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (endpoint and access and secret):
        fail("R2_API_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY are not set")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    key = f"audit-cors-check/regression-{int(time.time())}.txt"
    client.put_object(Bucket=args.bucket, Key=key, Body=b"cors-range-regression", ContentType="text/plain")
    try:
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": args.bucket, "Key": key}, ExpiresIn=300
        )
        allowed = requests.get(url, headers={"Origin": args.origin, "Range": "bytes=0-3"}, timeout=30)
        if allowed.status_code != 206:
            fail(f"Range GET expected 206, got {allowed.status_code}")
        if allowed.headers.get("Access-Control-Allow-Origin") != args.origin:
            fail(f"missing/incorrect ACAO: {allowed.headers.get('Access-Control-Allow-Origin')!r}")
        if not (allowed.headers.get("Content-Range") or "").startswith("bytes 0-3/"):
            fail(f"missing Content-Range: {allowed.headers.get('Content-Range')!r}")
        exposed = (allowed.headers.get("Access-Control-Expose-Headers") or "").lower()
        if "content-range" not in exposed:
            fail(f"Content-Range is not exposed: {exposed!r}")

        evil = requests.get(url, headers={"Origin": args.disallowed_origin}, timeout=30)
        if evil.headers.get("Access-Control-Allow-Origin"):
            fail("disallowed origin received Access-Control-Allow-Origin")

        print(f"PASS: Range 206, ACAO={allowed.headers['Access-Control-Allow-Origin']}")
        print(f"PASS: expose={allowed.headers.get('Access-Control-Expose-Headers')}")
        print(f"PASS: disallowed origin {args.disallowed_origin} has no ACAO")
    finally:
        client.delete_object(Bucket=args.bucket, Key=key)
        print(f"cleaned: {key}")


if __name__ == "__main__":
    main()
