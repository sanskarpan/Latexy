"""Seed the accepted PDF only after checking the effective disposable S3 target."""
import base64
import json
import os
import re
import sys
from urllib.parse import urlsplit


def isolated_endpoint(value, mode):
    url = urlsplit(value)
    hosts = {'localhost', '127.0.0.1', '::1'}
    if mode == 'docker':
        hosts |= {'storage', 'host.docker.internal'}
    if (url.scheme != 'http' or url.hostname not in hosts or
            url.username or url.password or url.query or url.fragment or
            url.path not in ('', '/') or not url.port or url.port < 1024 or
            (url.hostname == 'storage' and url.port != 9000)):
        raise ValueError('Sharing fixture requires an explicit isolated HTTP storage endpoint')
    return value.rstrip('/')


def seed(settings, get_client, payload, environment):
    mode = payload['mode']
    if mode not in ('host', 'docker') or environment.get('SHARING_ACCEPTANCE_DISPOSABLE') != '1':
        raise ValueError('Sharing fixture requires explicit disposable-service opt-in')
    endpoint = isolated_endpoint(payload['endpoint'], mode)
    bucket = payload['bucket']
    if not re.fullmatch(r'latexy-sharing-[a-f0-9]{32}', bucket):
        raise ValueError('Sharing fixture requires a per-run synthetic bucket')
    if (settings.ENVIRONMENT != 'test' or settings.DEPLOY_TARGET != 'local' or
            settings.OPENAI_API_KEY or settings.RESEND_API_KEY or
            isolated_endpoint(settings.MINIO_ENDPOINT, mode) != endpoint or
            settings.MINIO_BUCKET != bucket):
        raise ValueError('Effective backend settings do not match the isolated fixture target')
    isolated_endpoint(payload['origin'], 'host')
    if not re.fullmatch(r'compilations/[a-f0-9-]{36}/accepted\.pdf', payload['key']):
        raise ValueError('Sharing fixture requires a synthetic compilation key')
    data = base64.b64decode(payload['pdf'], validate=True)
    if not data.startswith(b'%PDF-'):
        raise ValueError('Sharing fixture requires PDF bytes')
    client = get_client()
    # Inspect the actual client too: a cached/misconfigured client must never
    # reach create_bucket, put_bucket_cors or put_object on a different target.
    if isolated_endpoint(client.meta.endpoint_url, mode) != endpoint:
        raise ValueError('Effective S3 client does not match the isolated fixture target')
    client.create_bucket(Bucket=bucket)
    client.put_bucket_cors(Bucket=bucket, CORSConfiguration={'CORSRules': [{
        'AllowedOrigins': [payload['origin']], 'AllowedMethods': ['GET', 'HEAD'],
        'AllowedHeaders': ['*'], 'ExposeHeaders': ['ETag', 'Content-Length'],
    }]})
    client.put_object(Bucket=bucket, Key=payload['key'], Body=data, ContentType='application/pdf')


if __name__ == '__main__':
    from app.core.config import settings
    from app.services.storage_service import _get_client

    seed(settings, _get_client, json.loads(sys.argv[1]), os.environ)
