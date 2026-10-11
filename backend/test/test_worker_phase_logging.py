"""Worker phase diagnostics remain observable without importing the API app."""
import json
import os
import subprocess
import sys


def test_clean_worker_emits_structured_phase_diagnostics_once():
    code = """
import logging, time
from app.core.worker_runtime import prepare_worker_logging
prepare_worker_logging()
handlers = list(logging.getLogger().handlers)
prepare_worker_logging()
assert list(logging.getLogger().handlers) == handlers
from app.core.engine_observability import engine_span
with engine_span('cache_lookup'):
    time.sleep(.26)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=30, env={**os.environ, "LOG_LEVEL": "INFO"})
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    phases = [row for row in rows if row.get("message") == "resume_engine_slow_phase"]
    assert len(phases) == 1
    assert phases[0]["phase"] == "cache_lookup"
    assert phases[0]["outcome"] == "success"
    assert phases[0]["latency_seconds"] >= .25
    assert not {"source", "latex_content", "api_key", "authorization"}.intersection(phases[0])
