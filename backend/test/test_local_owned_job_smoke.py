"""Local smoke commands reject unsafe origins before making any HTTP calls."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_script = Path(__file__).resolve().parents[2] / "scripts/ci/local-owned-job-smoke.py"
_spec = importlib.util.spec_from_file_location("local_owned_job_smoke", _script)
assert _spec is not None and _spec.loader is not None
_smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smoke)


@pytest.mark.parametrize("arguments", [
    [],
    ["--base-url", "https://latexy.xyz"],
    ["--frontend-url", "http://localhost:5180/path"],
    ["--base-url", "http://username:password@localhost:8030"],
    ["--base-url", "http://localhost:8030?token=synthetic"],
    ["--base-url", "http://localhost:not-a-port"],
    ["--timeout", "nan"],
    ["--timeout", "inf"],
    ["--timeout", "601"],
    ["--base-url", "http://127.0.0.1:8030", "--frontend-url", "http://localhost:5180"],
])
def test_owned_smoke_rejects_unsafe_configuration_before_http(arguments):
    acknowledgement = ["--confirm-isolated-local-run"] if arguments else []
    with (
        patch("sys.argv", [str(_script), *acknowledgement, *arguments]),
        patch.object(_smoke, "build_opener") as opener,
        pytest.raises(SystemExit) as error,
    ):
        _smoke.main()
    assert error.value.code == 2
    opener.assert_not_called()


@pytest.mark.parametrize("origin", ["http://localhost:8030", "http://127.0.0.1:8030/", "http://[::1]:8030"])
def test_owned_smoke_accepts_only_loopback_origins(origin):
    assert _smoke.local_origin(origin) == origin.rstrip("/")


def test_transport_expiry_targets_only_canonical_fixture_keys():
    job_id = "11111111-1111-4111-8111-111111111111"
    client = MagicMock()
    client.exists.return_value = 0
    with patch("redis.Redis", return_value=client) as factory:
        _smoke.expire_local_job_transport(job_id)
    factory.assert_called_once_with(
        host="127.0.0.1", port=6380, db=0, socket_connect_timeout=5, socket_timeout=5,
    )
    keys = [f"latexy:job:{job_id}:{suffix}" for suffix in ("meta", "state", "result", "pdf")]
    client.delete.assert_called_once_with(*keys)
    client.exists.assert_called_once_with(*keys)
    client.close.assert_called_once_with()


@pytest.mark.parametrize("job_id", ["*", "other-job", "{11111111-1111-4111-8111-111111111111}"])
def test_transport_expiry_rejects_noncanonical_keys_before_connecting(job_id):
    with patch("redis.Redis") as factory, pytest.raises(ValueError):
        _smoke.expire_local_job_transport(job_id)
    factory.assert_not_called()


def test_transport_expiry_closes_connection_when_delete_fails():
    client = MagicMock()
    client.delete.side_effect = RuntimeError("Synthetic local failure")
    with patch("redis.Redis", return_value=client), pytest.raises(RuntimeError):
        _smoke.expire_local_job_transport("11111111-1111-4111-8111-111111111111")
    client.close.assert_called_once_with()
