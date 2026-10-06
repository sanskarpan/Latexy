"""Bounded, ordered content publication off compiler/provider read loops."""
from __future__ import annotations

import json
import threading
import time
from collections import deque

from .event_publisher import get_worker_redis, publish_event, publish_event_batch
from .job_lifecycle import clear_current_owner, current_owner, current_owner_epoch, set_current_capability


class BufferedEventPublisher:
    """Flush content every 40ms, preserving the invocation's immutable capability.

    Only content deltas enter this queue. Closing is a barrier: callers publish
    progress/artifacts/terminal events only after the context exits. A saturated
    queue applies backpressure rather than losing logs or growing without bound.
    Memory is bounded by one queued batch plus one in-flight batch.
    Redis publication errors propagate to the producer; we never retry an
    ambiguous pipeline, which could duplicate already delivered tokens.
    """

    def __init__(self, job_id, publisher=publish_event, max_events=128, max_bytes=65536, flush_interval=.04):
        if max_events <= 0 or max_bytes <= 0 or flush_interval <= 0:
            raise ValueError("Buffer limits must be positive")
        self.job_id = job_id
        self.publisher = publisher
        self.max_events = max_events
        self.max_bytes = max_bytes
        self.flush_interval = flush_interval
        self._owner = current_owner(job_id)
        self._epoch = current_owner_epoch(job_id)
        if self._owner and self._epoch is None:
            # Legacy callers supply only a token. Freeze the epoch before any
            # asynchronous handoff; never upgrade an old delivery at flush time.
            raw_epoch = get_worker_redis().hget(f"latexy:job:{job_id}:lifecycle", "epoch")
            try:
                self._epoch = int(raw_epoch)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Cannot buffer events without an ownership epoch") from exc
        self._condition = threading.Condition()
        self._queue = deque()
        self._bytes = 0
        self._submitted = self._completed = 0
        self._closing = self._flush_requested = False
        self._error = None
        self._thread = threading.Thread(target=self._run, name="content-publisher", daemon=True)
        self._thread.start()

    def _check(self):
        if self._error is not None:
            raise RuntimeError("Buffered event publication failed") from self._error

    def publish(self, event_type, payload):
        if event_type not in {"log.line", "llm.token"}:
            raise ValueError("Lifecycle events must remain synchronous")
        payload = dict(payload)
        size = len(json.dumps(payload).encode("utf-8"))
        if size > self.max_bytes:
            if event_type == "llm.token" and isinstance(payload.get("token"), str):
                # Some providers deliver a whole response in one delta. Split
                # text only; the client still reconstructs the exact sequence.
                overhead = len(json.dumps({**payload, "token": ""}).encode("utf-8"))
                available = self.max_bytes - overhead
                if available <= 0:
                    raise ValueError("Content event exceeds buffer byte limit")
                # A non-BMP character expands to twelve JSON escape bytes.
                chunk_chars = max(1, available // 12)
                for start in range(0, len(payload["token"]), chunk_chars):
                    part = {**payload, "token": payload["token"][start:start + chunk_chars]}
                    if len(json.dumps(part).encode("utf-8")) > self.max_bytes:
                        raise ValueError("Content event exceeds buffer byte limit")
                    self.publish(event_type, part)
                return
            raise ValueError("Content event exceeds buffer byte limit")
        with self._condition:
            while len(self._queue) >= self.max_events or self._bytes + size > self.max_bytes:
                self._check()
                if self._closing:
                    raise RuntimeError("Publisher closed")
                self._flush_requested = True
                self._condition.notify_all()
                self._condition.wait()
            self._check()
            if self._closing:
                raise RuntimeError("Publisher closed")
            self._queue.append((event_type, payload))
            self._bytes += size
            self._submitted += 1
            self._condition.notify_all()

    def flush(self):
        with self._condition:
            target = self._submitted
            self._flush_requested = True
            self._condition.notify_all()
            while self._completed < target:
                self._check()
                self._condition.wait()
            self._check()

    def close(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join()
        self._check()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except Exception:
            if exc_type is None:
                raise

    def _run(self):
        if self._owner:
            set_current_capability(self.job_id, self._owner, self._epoch)
        try:
            while True:
                with self._condition:
                    while not self._queue and not self._closing:
                        self._condition.wait()
                    if not self._queue and self._closing:
                        return
                    deadline = time.monotonic() + self.flush_interval
                    while not self._closing and not self._flush_requested and len(self._queue) < self.max_events:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)
                    batch = list(self._queue)
                    self._queue.clear()
                    self._bytes = 0
                    self._flush_requested = False
                    self._condition.notify_all()
                if self.publisher is publish_event:
                    publish_event_batch(self.job_id, batch)
                else:
                    for kind, payload in batch:
                        self.publisher(self.job_id, kind, payload)
                with self._condition:
                    self._completed += len(batch)
                    self._condition.notify_all()
        except BaseException as exc:
            with self._condition:
                self._error = exc
                self._condition.notify_all()
        finally:
            clear_current_owner(self.job_id)
