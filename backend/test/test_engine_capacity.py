import pytest

from app.core.engine_capacity import capacity_options


def test_default_capacity_retains_current_worker_provisioning():
    assert capacity_options("LATEX", {}) == {"min_containers": 1, "buffer_containers": 0, "scaledown_window": 120}
    assert capacity_options("LLM", {})["min_containers"] == 0


def test_explicit_capacity_and_region_are_independent_by_worker_class():
    options = capacity_options("LATEX", {"MODAL_LATEX_MIN_CONTAINERS": "2", "MODAL_LATEX_BUFFER_CONTAINERS": "1", "MODAL_LATEX_CPU": "2", "MODAL_ENGINE_REGION": "us-east"})
    assert options == {"min_containers": 2, "buffer_containers": 1, "scaledown_window": 120, "cpu": 2., "region": "us-east"}


@pytest.mark.parametrize("values", [
    {"MODAL_LATEX_MIN_CONTAINERS": "-1"},
    {"MODAL_LATEX_BUFFER_CONTAINERS": "1000"},
    {"MODAL_LATEX_CPU": "nan"},
    {"MODAL_LATEX_CPU": "inf"},
    {"MODAL_LATEX_CPU": "0"},
    {"MODAL_LATEX_SCALEDOWN_SECONDS": "1"},
    {"MODAL_ENGINE_REGION": "us-east\nprivate"},
    {"MODAL_LATEX_MAX_CONTAINERS": "1", "MODAL_LATEX_MIN_CONTAINERS": "2"},
])
def test_invalid_capacity_cannot_silently_change_deployment(values):
    with pytest.raises(ValueError):
        capacity_options("LATEX", values)
