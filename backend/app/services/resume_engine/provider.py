"""Capability-aware, credential-scoped JSON calls with durable reservations."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import openai

from ...core.config import settings
from ...core.engine_observability import engine_span
from ..render_engine.cancellation import CancellationPoll
from .budgets import BudgetExceeded
from .credential_scope import credential_scope as credential_scope_for_api_key
from .patches import CompactOptimizationCancelled, CompactOptimizationError

_LIMIT = """
local t=redis.call('TIME'); local bucket=math.floor(tonumber(t[1])/60)
local global=KEYS[1]..':'..bucket; local tenant=KEYS[2]..':'..bucket
local tokens=tonumber(ARGV[1]); local rpm=tonumber(ARGV[2]); local tpm=tonumber(ARGV[3])
local tenant_rpm=tonumber(ARGV[4]); local tenant_tpm=tonumber(ARGV[5])
if redis.call('EXISTS',KEYS[3]) == 1 then return 1 end
if tonumber(redis.call('HGET',global,'requests') or '0') >= rpm then return -1 end
if tonumber(redis.call('HGET',global,'tokens') or '0')+tokens > tpm then return -2 end
if tonumber(redis.call('HGET',tenant,'requests') or '0') >= tenant_rpm then return -3 end
if tonumber(redis.call('HGET',tenant,'tokens') or '0')+tokens > tenant_tpm then return -4 end
for _,key in ipairs({global,tenant}) do
  redis.call('HINCRBY',key,'requests',1); redis.call('HINCRBY',key,'tokens',tokens); redis.call('EXPIRE',key,75)
end
redis.call('SET',KEYS[3],'1','EX',75)
return 1
"""


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    model: str
    base_url: str | None
    input_per_million: float
    output_per_million: float
    strict_json_schema: bool
    streaming: bool = True
    cancellation: str = "transport_close_best_effort"
    usage_accounting: bool = True
    reasoning_controls: bool = False

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_million + output_tokens * self.output_per_million) / 1_000_000


def resolve_provider(api_key: str, model: str | None) -> ProviderSpec:
    platform = bool(settings.OPENAI_BASE_URL) and api_key == settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL if platform else None
    host = urlparse(base_url or "https://api.openai.com").hostname
    provider = (
        "openai"
        if host == "api.openai.com"
        else ("gemini" if host == "generativelanguage.googleapis.com" else "openai_compatible")
    )
    effective_model = model or (settings.OPENAI_MODEL if platform or not settings.OPENAI_BASE_URL else "gpt-4o-mini")
    price = settings.RESUME_ENGINE_MODEL_PRICING.get(provider + ":" + effective_model)
    if not price:
        raise BudgetExceeded("This provider/model needs an operator-configured price before bounded optimization")
    input_price, output_price = price.get("input_per_million"), price.get("output_per_million")
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or value < 0
        for value in (input_price, output_price)
    ):
        raise BudgetExceeded("Provider pricing is invalid")
    strict = provider == "openai" and effective_model in {
        "gpt-4o-mini",
        "gpt-4o-mini-2024-07-18",
        "gpt-4o",
        "gpt-4o-2024-08-06",
    }
    return ProviderSpec(provider, effective_model, base_url, input_price, output_price, strict)


def _close(resource):
    if resource is not None and callable(getattr(resource, "close", None)):
        try:
            resource.close()
        except Exception:
            pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CompactOptimizationError("Provider JSON has duplicate keys")
        result[key] = value
    return result


class SemanticProvider:
    """One adapter per run; connections reused only inside its credential scope."""

    def __init__(
        self,
        *,
        spec: ProviderSpec,
        api_key: str,
        ledger,
        deadline: float,
        cancelled,
        owner_scope: str,
        client_factory=openai.OpenAI,
    ):
        self.spec, self.api_key, self.ledger, self.deadline = spec, api_key, ledger, deadline
        self.cancelled, self.owner_scope, self.client_factory = cancelled, owner_scope, client_factory
        self.credential_scope = credential_scope_for_api_key(api_key)
        self._clients: dict[int, object] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def close(self):
        self._stopped.set()
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            _close(client)

    def _client(self, timeout):
        key = threading.get_ident()
        with self._lock:
            if self._stopped.is_set():
                raise CompactOptimizationCancelled("Optimization run stopped")
            if key not in self._clients:
                kwargs = {"api_key": self.api_key, "max_retries": 0, "timeout": timeout}
                if self.spec.base_url:
                    kwargs["base_url"] = self.spec.base_url
                self._clients[key] = self.client_factory(**kwargs)
            return self._clients[key]

    def generate(
        self, stage_key: str, *, system: str, payload: dict, schema: dict, max_output_tokens=2048
    ) -> tuple[dict, dict | None, bool]:
        remaining = self.deadline - time.monotonic()
        if self.cancelled() or self._stopped.is_set():
            raise CompactOptimizationCancelled("Optimization cancelled")
        prompt = json.dumps({"input": payload, "response_schema": schema}, ensure_ascii=False, allow_nan=False)
        request = {
            "system": system,
            "payload": payload,
            "schema": schema,
            "model": self.spec.model,
            "provider": self.spec.provider,
            "max_output_tokens": max_output_tokens,
            "version": "semantic-provider-v1",
        }
        # Byte upper bound works even when the app tokenizer uses a fallback or
        # when this compatible provider uses another vocabulary/tokenizer.
        input_tokens = len((system + prompt + json.dumps(schema)).encode()) + 256
        reservation = {
            "input_tokens": input_tokens,
            "output_tokens": max_output_tokens,
            "cost_usd": self.spec.cost(input_tokens, max_output_tokens),
        }
        # begin first recovers completed stages without new rate or spend use.
        restored = self.ledger.begin(stage_key, request, reservation)
        if restored:
            return restored["output"], restored["usage"], True
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.ledger.fail(
                stage_key,
                error_code="deadline_before_provider",
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            raise BudgetExceeded("Optimization deadline reached")
        rate_key = (
            "latexy:resume-engine:rate:"
            + self.credential_scope
            + ":"
            + hashlib.sha256(self.spec.model.encode()).hexdigest()[:16]
        )
        tenant_key = rate_key + ":" + hashlib.sha256(self.owner_scope.encode()).hexdigest()[:16]
        reservation_key = rate_key + ":intent:" + hashlib.sha256((self.ledger.job_id + "\0" + stage_key).encode()).hexdigest()
        rate_result = self.ledger.redis.eval(
                _LIMIT,
                3,
                rate_key,
                tenant_key,
                reservation_key,
                input_tokens + max_output_tokens,
                settings.RESUME_ENGINE_PROVIDER_RPM,
                settings.RESUME_ENGINE_PROVIDER_TPM,
                settings.RESUME_ENGINE_TENANT_RPM,
                settings.RESUME_ENGINE_TENANT_TPM,
            )
        if rate_result != 1:
            # No provider was called, but a unique intent exists. Marking it
            # non-retryable avoids ambiguity and permits other completed work.
            self.ledger.fail(
                stage_key,
                error_code={-1: "provider_requests_rate_limited", -2: "provider_tokens_rate_limited",
                            -3: "tenant_requests_rate_limited", -4: "tenant_tokens_rate_limited"}.get(rate_result, "rate_limited_before_provider"),
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            scope = {-1: "provider requests", -2: "provider tokens", -3: "tenant requests", -4: "tenant tokens"}.get(rate_result, "provider")
            raise BudgetExceeded(scope + " rate budget reached")
        client = self._client(remaining)
        active_stream = [None]
        expired = threading.Event()
        cancelled_transport = threading.Event()
        finished = threading.Event()

        def expire():
            expired.set()
            _close(active_stream[0])
            _close(client)

        timer = threading.Timer(max(0.001, self.deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()

        def watch_cancel():
            # Chunk callbacks cannot observe cancellation during blocked headers
            # or a silent stream. Closing the transport is best effort only.
            while not finished.wait(0.1):
                try:
                    stop = self.cancelled() or self._stopped.is_set()
                except Exception:
                    stop = True
                if stop:
                    cancelled_transport.set()
                    _close(active_stream[0])
                    _close(client)
                    return

        watcher = threading.Thread(target=watch_cancel, name="resume-provider-cancellation", daemon=True)
        watcher.start()
        usage = None
        try:
            self.ledger.check_owner()
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExceeded("Optimization deadline reached")
            kwargs = dict(
                model=self.spec.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                max_tokens=max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
                timeout=remaining,
            )
            if self.spec.strict_json_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "resume_engine_stage", "strict": True, "schema": schema},
                }
            raw_parts, byte_count, finish = [], 0, None
            poll_cancel = CancellationPoll(self.cancelled)
            with engine_span("model_call"):
                stream = client.chat.completions.create(**kwargs)
                active_stream[0] = stream
                if cancelled_transport.is_set():
                    raise CompactOptimizationCancelled("Optimization cancelled")
                if expired.is_set():
                    _close(stream)
                    raise BudgetExceeded("Optimization deadline reached")
                for chunk in stream:
                    if poll_cancel() or self._stopped.is_set():
                        raise CompactOptimizationCancelled("Optimization cancelled")
                    if expired.is_set() or time.monotonic() >= self.deadline:
                        raise BudgetExceeded("Optimization deadline reached")
                    if chunk.usage is not None:
                        reported_in = getattr(chunk.usage, "prompt_tokens", None)
                        reported_out = getattr(chunk.usage, "completion_tokens", None)
                        if (
                            isinstance(reported_in, int) and not isinstance(reported_in, bool)
                            and isinstance(reported_out, int) and not isinstance(reported_out, bool)
                            and reported_in >= 0
                            and reported_out >= 0
                        ):
                            usage = {
                                "input_tokens": reported_in,
                                "output_tokens": reported_out,
                                "cost_usd": self.spec.cost(reported_in, reported_out),
                            }
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if getattr(choice.delta, "refusal", None):
                        raise CompactOptimizationError("Provider refused this stage")
                    if isinstance(getattr(choice, "finish_reason", None), str):
                        finish = choice.finish_reason
                    delta = choice.delta.content
                    if delta:
                        byte_count += len(delta.encode())
                        if byte_count > 128_000:
                            raise CompactOptimizationError("Provider stage exceeded the response limit")
                        raw_parts.append(delta)
            if expired.is_set() or time.monotonic() >= self.deadline:
                raise BudgetExceeded("Optimization deadline reached")
            if self.cancelled():
                raise CompactOptimizationCancelled("Optimization cancelled")
            if finish != "stop":
                raise CompactOptimizationError("Provider response was incomplete")
            if usage and (
                usage["input_tokens"] > reservation["input_tokens"]
                or usage["output_tokens"] > max_output_tokens
                or usage["cost_usd"] > reservation["cost_usd"] + 1e-12
            ):
                # Record the actual overage through fail(), but never accept
                # this stage's output or hide it by clamping reported usage.
                raise BudgetExceeded("Provider reported usage beyond the reserved ceiling")
            value = json.loads(
                "".join(raw_parts),
                object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
            )
            if not isinstance(value, dict):
                raise CompactOptimizationError("Provider stage must return an object")
            self.ledger.complete(stage_key, output=value, usage=usage)
            return value, usage, False
        except Exception:
            try:
                self.ledger.fail(stage_key, usage=usage)
            except Exception:
                pass  # Existing requesting intent remains ambiguous, never paid again.
            raise
        finally:
            finished.set()
            timer.cancel()
            timer.join(timeout=0.1)
            watcher.join(timeout=0.2)
            _close(active_stream[0])
