"""Stateless rollout contracts; safe without a database or provider access."""

from inspect import getclosurevars

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import export_routes, resume_routes


def _app(*, legacy_only=False):
    app = FastAPI()
    routes = [*resume_routes.router.routes, *export_routes.router.routes]
    if legacy_only:
        routes = [
            route for route in routes
            if "/builder/v1" not in getattr(route, "path", "")
            and getattr(route, "path", "") != "/resumes/builder/capabilities"
        ]
    # Extend concrete routes: newer FastAPI versions defer include_router via
    # wrapper entries, whose children cannot be filtered through app.routes.
    app.router.routes.extend(routes)
    return app


def test_capability_is_explicit_and_never_cached():
    with TestClient(_app()) as client:
        response = client.get("/resumes/builder/capabilities")
    assert response.status_code == 200
    assert response.json() == {"guided_builder_version": 1}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/resumes/builder/v1"),
    ("post", "/resumes/builder/v1/seed-upload"),
    ("get", "/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1"),
    ("patch", "/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1"),
    ("get", "/export/builder/v1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/json"),
    ("get", "/export/builder/v1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/canva"),
    ("get", "/export/builder/v1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/figma"),
])
def test_versioned_calls_cannot_fall_through_to_legacy_routes(method, path):
    with TestClient(_app(legacy_only=True)) as client:
        response = getattr(client, method)(path)
    assert response.status_code == 404


def test_versioned_save_requires_an_explicit_integer_baseline():
    for body in ({}, {"expected_structured_version": None},
                 {"expected_structured_version": "1"}, {"expected_structured_version": True}):
        with pytest.raises(ValidationError):
            resume_routes.BuilderResumeV1PatchRequest.model_validate(body)
    assert resume_routes.BuilderResumeV1PatchRequest(expected_structured_version=1).expected_structured_version == 1


def test_versioned_routes_reuse_existing_permissions_and_handlers():
    routes = {route.path: route for route in _app().routes if hasattr(route, "endpoint")}
    for old, new in [
        ("/resumes/builder", "/resumes/builder/v1"),
        ("/resumes/builder/seed-upload", "/resumes/builder/v1/seed-upload"),
        ("/export/{resume_id}/{fmt}", "/export/builder/v1/{resume_id}/{fmt}"),
        ("/export/{resume_id}/canva", "/export/builder/v1/{resume_id}/canva"),
        ("/export/{resume_id}/figma", "/export/builder/v1/{resume_id}/figma"),
    ]:
        assert routes[old].endpoint is routes[new].endpoint
        old_dependencies = routes[old].dependencies
        new_dependencies = routes[new].dependencies
        assert len(old_dependencies) == len(new_dependencies)
        for old_dependency, new_dependency in zip(old_dependencies, new_dependencies):
            assert old_dependency.dependency.__code__ is new_dependency.dependency.__code__
            assert getclosurevars(old_dependency.dependency).nonlocals == getclosurevars(new_dependency.dependency).nonlocals
