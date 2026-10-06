"""Static regressions for transport-level WebSocket frame limits."""

from pathlib import Path

from app.api.ws_routes import _check_rate_limit, _ws_message_counts

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT_MAX = "524288"


def test_every_uvicorn_launch_sets_transport_frame_limit():
    command_files = {
        "docker-compose.yml": "uvicorn app.main:app",
        "Makefile": "uvicorn app.main:app",
        "backend/Dockerfile": '"uvicorn", "app.main:app"',
        "backend/Dockerfile.prod": "uvicorn app.main:app",
        "scripts/dev.sh": '"$UVICORN" app.main:app',
        "scripts/ci/full-stack-smoke.sh": '"${backend_uvicorn[@]}" app.main:app',
    }

    for relative_path, marker in command_files.items():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert marker in source, relative_path
        assert "--ws-max-size" in source, relative_path
        assert TRANSPORT_MAX in source, relative_path


def test_direct_uvicorn_runner_uses_same_transport_limit():
    source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert "WS_MAX_SIZE_BYTES = 512 * 1024" in source
    assert "ws_max_size=WS_MAX_SIZE_BYTES" in source


def test_modal_entrypoint_documents_managed_ingress_limit_behavior():
    source = (ROOT / "backend/modal_app.py").read_text(encoding="utf-8")
    assert "managed ingress rather than" in source
    assert "64 KiB/256 KiB app-level" in source


def test_jobs_rate_limiter_does_not_store_rejected_frame_timestamps():
    connection_id = "rate-limit-regression"
    _ws_message_counts.pop(connection_id, None)
    try:
        assert all(_check_rate_limit(connection_id, max_per_second=20) for _ in range(20))
        assert not any(_check_rate_limit(connection_id, max_per_second=20) for _ in range(2_000))
        assert len(_ws_message_counts[connection_id]) == 20
    finally:
        _ws_message_counts.pop(connection_id, None)
