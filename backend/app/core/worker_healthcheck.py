"""Probe this Celery worker without importing the full application."""

import os
import socket

from celery import Celery


def worker_is_ready() -> bool:
    broker = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL")
    if not broker:
        return False
    destination = f"celery@{socket.gethostname()}"
    try:
        client = Celery("latexy_healthcheck", broker=broker)
        # Match the application's Redis queue separator. A mismatched probe
        # also writes incompatible pidbox reply bindings into the broker.
        client.conf.broker_transport_options = {"sep": ":"}
        replies = client.control.ping(destination=[destination], timeout=8)
        return any(reply.get(destination, {}).get("ok") == "pong" for reply in replies)
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if worker_is_ready() else 1)
