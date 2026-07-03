"""Unit tests for observability record helpers and the traced() span helper."""

from prometheus_client import generate_latest

from app.core import observability, tracing


def _sample_value(metric, **labels):
    """Read the current value of a labelled Prometheus child, or None."""
    try:
        return metric.labels(**labels)._value.get()
    except Exception:
        return None


def test_record_llm_call_increments_counters_and_latency():
    before = _sample_value(
        observability.LLM_REQUESTS_TOTAL, provider="openai", model="test-model", status="success"
    ) or 0.0
    observability.record_llm_call(
        "openai", "test-model", "success",
        total_seconds=2.0, prompt_build_seconds=0.2, provider_call_seconds=1.7,
        prompt_tokens=10, completion_tokens=20, total_tokens=30, cost_usd=0.01,
    )
    after = _sample_value(
        observability.LLM_REQUESTS_TOTAL, provider="openai", model="test-model", status="success"
    )
    assert after == before + 1
    # Token counter recorded for the total kind.
    assert _sample_value(
        observability.LLM_TOKENS_TOTAL, provider="openai", model="test-model", kind="total"
    ) >= 30


def test_record_llm_call_defaults_unknown_labels():
    observability.record_llm_call("", "", "error")
    assert _sample_value(
        observability.LLM_REQUESTS_TOTAL, provider="unknown", model="unknown", status="error"
    ) >= 1


def test_record_compile_and_ats_and_business():
    observability.record_compile("success", duration_seconds=1.0, pdf_bytes=1234, pages=1)
    assert _sample_value(observability.COMPILES_TOTAL, status="success") >= 1

    observability.record_ats_score("quick", "success", duration_seconds=0.05)
    assert _sample_value(observability.ATS_SCORES_TOTAL, scorer="quick", status="success") >= 1

    observability.record_job_submitted("optimize", authenticated=False)
    assert _sample_value(
        observability.JOBS_SUBMITTED_TOTAL, job_type="optimize", auth="anonymous"
    ) >= 1

    observability.record_trial_use("limit_exceeded")
    assert _sample_value(observability.TRIAL_USES_TOTAL, outcome="limit_exceeded") >= 1

    observability.record_business_event("subscription", "created")
    assert _sample_value(
        observability.BUSINESS_EVENTS_TOTAL, event="subscription", detail="created"
    ) >= 1


def test_gauges_set_queue_depth_and_db_pool():
    observability.set_queue_depth("llm", 7)
    assert _sample_value(observability.CELERY_QUEUE_DEPTH, queue="llm") == 7

    observability.set_db_pool_stats(size=10, checked_out=3, overflow=1)
    assert _sample_value(observability.DB_POOL_CONNECTIONS, state="size") == 10
    assert _sample_value(observability.DB_POOL_CONNECTIONS, state="checked_out") == 3
    assert _sample_value(observability.DB_POOL_CONNECTIONS, state="overflow") == 1


def test_metrics_payload_is_prometheus_text():
    observability.record_compile("error", duration_seconds=0.5)
    payload = observability.metrics_payload()
    assert isinstance(payload, bytes)
    assert b"latexy_compiles_total" in payload
    # Same exposition format as the default-registry scrape (families overlap).
    # Note: exact byte-equality is not asserted because the default registry also
    # exposes live process/GC collectors whose values change between scrapes.
    assert b"latexy_compiles_total" in generate_latest()


def test_traced_is_a_noop_context_manager_when_otel_disabled():
    """traced() must never raise regardless of OTEL state and must yield a context."""
    with tracing.traced("unit.test.span", foo="bar", n=1):
        result = 1 + 1
    assert result == 2


def test_traced_swallows_attribute_types():
    # Non-string attribute values must not blow up the span helper.
    with tracing.traced("unit.test.span2", count=3, ratio=0.5, flag=True):
        pass
