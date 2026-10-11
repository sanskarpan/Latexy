"""New engine routes retain the capability boundaries of their operations.

All requests use fail-on-use DB/provider doubles and local ASGI transport.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.routes import router
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.middleware.capability_router import _route_gate, payload_capabilities
from app.services.entitlement_service import entitlement_service

OWNER = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def engine_policy_app(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optional] = lambda: OWNER
    app.dependency_overrides[get_current_user_required] = lambda: OWNER
    db = AsyncMock()
    db.execute.side_effect = AssertionError("Denied engine request reached the database")
    db.scalar.side_effect = AssertionError("Denied engine request reached the database")
    db.commit.side_effect = AssertionError("Denied engine request changed the database")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(entitlement_service, "has_feature", AsyncMock(return_value=True))
    return app, db


@pytest.mark.parametrize("method,path,key,body", [
    *(('POST', '/public/engine/document/patch', key, {}) for key in ('b10', 'c01')),
    *(('PATCH', f'/resumes/{OWNER}/engine/document', key, {}) for key in ('b10', 'c01')),
    *(('POST', f'/resumes/{OWNER}/engine/structure', key, {}) for key in ('b10', 'c01')),
    *(('POST', f'/resumes/{OWNER}/engine/optimize', key, {}) for key in ('d01', 'd18', 'c05', 'c01')),
    *(('POST', '/resumes/imports/pdf', key, {}) for key in ('b06', 'b08')),
    *(('POST', f'/resumes/imports/{OWNER}/adapt', key, {}) for key in ('b06', 'b08', 'b04', 'b01', 'c01')),
    *(('POST', f'/resumes/{OWNER}/engine/runs/{OWNER}/decisions', key,
       {'accept_patch_ids': ['candidate']}) for key in ('d03', 'c01')),
])
async def test_denied_engine_admission_precedes_database_and_dispatch(method, path, key, body, engine_policy_app):
    app, db = engine_policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=body)
    assert response.status_code == 403, response.text
    assert key in response.text
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("path", ['/public/engine/document', '/public/engine/document/patch'])
async def test_anonymous_engine_operations_obey_studio_admission(path, engine_policy_app):
    app, db = engine_policy_app
    app.dependency_overrides[get_current_user_optional] = lambda: None
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != 'a09'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={})
    assert response.status_code == 403
    assert 'a09' in response.text
    db.execute.assert_not_awaited()


def test_candidate_rejection_is_recovery_but_acceptance_is_a_source_write():
    assert payload_capabilities('resume_engine_routes', 'decide_run',
                                {'reject_patch_ids': ['candidate']}, {}, {}) == ()
    assert payload_capabilities('resume_engine_routes', 'decide_run',
                                {'accept_patch_ids': ['candidate']}, {}, {}) == ('d03', 'c01')


async def test_candidate_rejection_does_not_query_capabilities(monkeypatch):
    lookup = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, 'has_feature', lookup)
    request = SimpleNamespace(headers={'content-type': 'application/json'}, path_params={}, query_params={},
                              json=AsyncMock(return_value={'reject_patch_ids': ['candidate']}))
    await _route_gate('resume_engine_routes', 'decide_run')(request, OWNER)
    lookup.assert_not_awaited()


def test_engine_metadata_and_artifact_recovery_have_no_admission_gate():
    def walk(current):
        for route in current.routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, 'original_router'):
                yield from walk(route.original_router)
    recovery = {
        ('resume_engine_routes', name) for name in ('engine_capabilities', 'engine_providers', 'get_document', 'get_run')
    } | {('pdf_import_routes', name) for name in ('get_import', 'original_pdf', 'discard_import', 'resume_import')} | {
        ('render_artifact_routes', name) for name in ('preview_pdf', 'preview_geometry', 'preview_synctex')
    }
    found = set()
    for route in walk(router):
        pair = route.endpoint.__module__.rsplit('.', 1)[-1], route.endpoint.__name__
        if pair in recovery:
            found.add(pair)
            assert not any(getattr(d.call, '__name__', '').startswith('capability_')
                           for d in route.dependant.dependencies), pair
    assert found == recovery


async def test_protocol_discovery_survives_disabled_capabilities(engine_policy_app):
    app, db = engine_policy_app
    entitlement_service.has_feature.return_value = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get('/public/engine/capabilities')
    assert response.status_code == 200
    assert response.json() == {'resume_engine_version': 1}
    assert response.headers['cache-control'] == 'no-store'
    db.execute.assert_not_awaited()


async def test_provider_discovery_never_decrypts_disabled_stored_byok(monkeypatch):
    from app.api.resume_engine_routes import engine_providers
    from app.services.api_key_service import api_key_service

    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: ['openai', 'anthropic'])
    decrypt = AsyncMock(side_effect=AssertionError('Discovery must not load credentials'))
    monkeypatch.setattr(api_key_service, 'get_user_provider', decrypt)
    monkeypatch.setattr(entitlement_service, 'has_feature', AsyncMock(return_value=False))
    result = await engine_providers(db, OWNER)
    assert result['default']['source'] == 'byok'
    assert result['default']['ready'] is False
    assert all(not provider['key_available'] for provider in result['providers'])
    decrypt.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_enabled_provider_discovery_preserves_existing_key_resolution(monkeypatch):
    from app.api.resume_engine_routes import engine_providers
    from app.core.config import settings
    from app.services.api_key_service import api_key_service

    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: ['openai'])
    key_loader = AsyncMock(return_value='synthetic-owner-key')
    monkeypatch.setattr(api_key_service, 'get_user_provider', key_loader)
    monkeypatch.setattr(entitlement_service, 'has_feature', AsyncMock(return_value=True))
    monkeypatch.setattr(settings, 'OPENAI_API_KEY', 'synthetic-platform-key')
    monkeypatch.setattr(settings, 'OPENAI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai')
    monkeypatch.setattr(settings, 'RESUME_ENGINE_MODEL_PRICING', {
        'openai:gpt-4o-mini': {'input_per_million': .15, 'output_per_million': .60},
    })
    result = await engine_providers(db, OWNER)
    assert result['default'] == {'provider': 'openai', 'model': 'gpt-4o-mini', 'source': 'byok', 'ready': True}
    key_loader.assert_awaited_once_with(db, OWNER, 'openai')
    assert 'synthetic-owner-key' not in str(result)
