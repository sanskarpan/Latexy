"""Capability-aware, credential-scoped JSON calls with durable reservations."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
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
    protocol: str = "openai_chat_completions"

    @property
    def endpoint_identity(self) -> str:
        return self.protocol + ":" + (self.base_url or "https://api.openai.com/v1")

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_million + output_tokens * self.output_per_million) / 1_000_000


BYOK_ENDPOINTS = {"openai": None, "anthropic": "https://api.anthropic.com/v1/messages",
                  "openrouter": "https://openrouter.ai/api/v1"}


def configured_models(provider: str) -> list[str]:
    prefix = provider + ":"
    return sorted(key[len(prefix):] for key in settings.RESUME_ENGINE_MODEL_PRICING
                  if key.startswith(prefix) and 0 < len(key[len(prefix):]) <= 200
                  and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", key[len(prefix):]))


def resolve_provider(api_key: str, model: str | None, *, selected_provider: str | None = None) -> ProviderSpec:
    if selected_provider is not None:
        if selected_provider not in BYOK_ENDPOINTS:
            raise BudgetExceeded("Unsupported optimization provider")
        models = configured_models(selected_provider)
        if model is None:
            if len(models) != 1:
                raise BudgetExceeded("Choose an exactly priced model for this provider")
            model = models[0]
        provider, base_url, effective_model = selected_provider, BYOK_ENDPOINTS[selected_provider], model
    else:
        return _resolve_implicit_provider(api_key, model)
    return _priced_spec(provider, effective_model, base_url)


def _resolve_implicit_provider(api_key: str, model: str | None) -> ProviderSpec:
    platform = bool(settings.OPENAI_BASE_URL) and api_key == settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL if platform else None
    host = urlparse(base_url or "https://api.openai.com").hostname
    provider = (
        "openai"
        if host == "api.openai.com"
        else ("gemini" if host == "generativelanguage.googleapis.com" else "openai_compatible")
    )
    effective_model = model or (settings.OPENAI_MODEL if platform or not settings.OPENAI_BASE_URL else "gpt-4o-mini")
    return _priced_spec(provider, effective_model, base_url)


def _priced_spec(provider: str, effective_model: str, base_url: str | None) -> ProviderSpec:
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
    return ProviderSpec(provider, effective_model, base_url, input_price, output_price, strict,
                        protocol="anthropic_messages_v1" if provider == "anthropic" else "openai_chat_completions")


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


def _token_count(value) -> int:
    if type(value) is not int or value < 0:
        raise CompactOptimizationError("Provider usage is invalid")
    return value


def _validate_native_usage(usage: dict) -> None:
    # Cache writes use a different unit price. This adapter deliberately sends
    # no cache_control and has only exact ordinary input/output pricing; never
    # silently treat a positive cache category as ordinary input cost.
    for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        if key in usage and _token_count(usage[key]) != 0:
            raise CompactOptimizationError("Provider cache usage needs a priced cache policy")
    if usage.get("cache_creation") is not None:
        nested = usage["cache_creation"]
        if not isinstance(nested, dict) or any(_token_count(value) != 0 for value in nested.values()):
            raise CompactOptimizationError("Provider cache usage needs a priced cache policy")


class AnthropicStageStream:
    """Bounded native SSE normalized for the existing durable provider loop.

    The wrapper is closeable before headers arrive, so the shared deadline and
    cancellation watchdog can close its client during a blocked request too.
    Fixed URL, disabled redirects and no automatic retries retain credential and
    paid-intent isolation. All framing bytes count toward the response ceiling.
    """

    def __init__(self, client, spec, system, prompt, max_tokens, timeout):
        self.client, self.spec, self.response = client, spec, None
        self.params = {"model": spec.model, "system": system,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "stream": True}
        self.timeout = timeout
        self.closed = threading.Event()

    def close(self):
        self.closed.set()
        _close(self.response)
        _close(self.client)

    @staticmethod
    def _chunk(text=None, *, usage=None, finish=None):
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(
            delta=SimpleNamespace(content=text, refusal=None), finish_reason=finish)])

    def __iter__(self):
        if self.spec.base_url != BYOK_ENDPOINTS["anthropic"]:
            raise CompactOptimizationError("Invalid Anthropic endpoint")
        started, stopped, block, next_index = False, False, None, 0
        reported_input, reported_output, finish = None, None, None
        raw, total = b"", 0
        with self.client.stream("POST", self.spec.base_url, json=self.params, timeout=self.timeout) as response:
            self.response = response
            if self.closed.is_set():
                raise CompactOptimizationCancelled("Optimization transport closed")
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", "").lower():
                raise CompactOptimizationError("Provider returned an invalid stream type")
            for content in response.iter_bytes():
                if self.closed.is_set():
                    raise CompactOptimizationCancelled("Optimization transport closed")
                total += len(content)
                if total > 128_000:
                    raise CompactOptimizationError("Provider stream exceeded the response limit")
                raw = (raw + content).replace(b"\r\n", b"\n")
                while b"\n\n" in raw:
                    frame, raw = raw.split(b"\n\n", 1)
                    event, lines = None, []
                    for line in frame.decode("utf-8", errors="strict").split("\n"):
                        if not line or line.startswith(":"):
                            continue
                        field, separator, value = line.partition(":")
                        if not separator:
                            raise CompactOptimizationError("Provider stream framing is invalid")
                        value = value.removeprefix(" ")
                        if field == "event" and event is None:
                            event = value
                        elif field == "data":
                            lines.append(value)
                        else:
                            raise CompactOptimizationError("Provider stream framing is invalid")
                    if not lines and event is None:
                        continue
                    value = json.loads("\n".join(lines), object_pairs_hook=_unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
                    if not isinstance(value, dict) or value.get("type") != event:
                        raise CompactOptimizationError("Provider stream event is invalid")
                    if event == "ping":
                        continue
                    if stopped:
                        raise CompactOptimizationError("Provider emitted data after completion")
                    if event == "message_start" and not started:
                        message = value.get("message")
                        if not isinstance(message, dict) or message.get("type") != "message" or message.get("role") != "assistant":
                            raise CompactOptimizationError("Provider message is invalid")
                        usage = message.get("usage")
                        if not isinstance(usage, dict):
                            raise CompactOptimizationError("Provider usage is unavailable")
                        _validate_native_usage(usage)
                        if "input_tokens" not in usage:
                            raise CompactOptimizationError("Provider input usage is unavailable")
                        reported_input = _token_count(usage["input_tokens"])
                        reported_output = _token_count(usage.get("output_tokens"))
                        started = True
                    elif not started:
                        raise CompactOptimizationError("Provider message did not start")
                    elif event == "content_block_start" and block is None and finish is None:
                        item = value.get("content_block")
                        if type(value.get("index")) is not int or value["index"] != next_index or not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                            raise CompactOptimizationError("Provider text block is invalid")
                        block, next_index = next_index, next_index + 1
                        if item["text"]:
                            yield self._chunk(item["text"])
                    elif event == "content_block_delta" and block is not None:
                        delta = value.get("delta")
                        if type(value.get("index")) is not int or value["index"] != block or not isinstance(delta, dict) or delta.get("type") != "text_delta" or not isinstance(delta.get("text"), str):
                            raise CompactOptimizationError("Provider text delta is invalid")
                        yield self._chunk(delta["text"])
                    elif event == "content_block_stop" and block is not None:
                        if type(value.get("index")) is not int or value["index"] != block:
                            raise CompactOptimizationError("Provider block completion is invalid")
                        block = None
                    elif event == "message_delta" and block is None:
                        delta, usage = value.get("delta"), value.get("usage")
                        if not isinstance(delta, dict) or (delta.get("stop_reason") is not None and not isinstance(delta["stop_reason"], str)) or not isinstance(usage, dict):
                            raise CompactOptimizationError("Provider completion is invalid")
                        _validate_native_usage(usage)
                        if "input_tokens" in usage and _token_count(usage["input_tokens"]) != reported_input:
                            raise CompactOptimizationError("Provider input usage changed")
                        output = _token_count(usage.get("output_tokens"))
                        if output < reported_output:
                            raise CompactOptimizationError("Provider output usage decreased")
                        reported_output = output
                        reason = delta.get("stop_reason")
                        if reason is not None:
                            next_finish = "stop" if reason in {"end_turn", "stop_sequence"} else reason
                            if finish is not None and next_finish != finish:
                                raise CompactOptimizationError("Provider stop reason changed")
                            finish = next_finish
                    elif event == "message_stop" and block is None and finish is not None:
                        stopped = True
                    else:
                        raise CompactOptimizationError("Provider stream event sequence is invalid")
            if raw.strip() or not stopped:
                raise CompactOptimizationError("Provider response was incomplete")
            yield self._chunk(usage=SimpleNamespace(prompt_tokens=reported_input,
                                                   completion_tokens=reported_output), finish=finish)


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
        client_factory=None,
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
                if self.spec.protocol == "anthropic_messages_v1":
                    self._clients[key] = (self.client_factory or httpx.Client)(timeout=timeout, follow_redirects=False,
                        headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
                else:
                    kwargs = {"api_key": self.api_key, "max_retries": 0, "timeout": timeout}
                    if self.spec.base_url:
                        kwargs["base_url"] = self.spec.base_url
                    self._clients[key] = (self.client_factory or openai.OpenAI)(**kwargs)
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
            "endpoint_identity": self.spec.endpoint_identity,
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
            + self.spec.provider + ":"
            + hashlib.sha256(self.spec.endpoint_identity.encode()).hexdigest()[:16] + ":"
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
                stream = (AnthropicStageStream(client, self.spec, system, prompt, max_output_tokens, remaining)
                          if self.spec.protocol == "anthropic_messages_v1" else client.chat.completions.create(**kwargs))
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
