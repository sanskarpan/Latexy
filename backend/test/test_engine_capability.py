"""The rollout probe advertises a protocol, never resource authorization."""
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.resume_engine_routes import public_router


async def test_engine_capability_is_public_uncached_and_has_no_database_or_provider_dependencies():
    app = FastAPI()
    app.include_router(public_router)
    route = next(route for route in public_router.routes if route.path == "/public/engine/capabilities")
    assert route.dependant.dependencies == []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/public/engine/capabilities")
    assert response.status_code == 200
    assert response.json() == {"resume_engine_version": 1}
    assert response.headers["cache-control"] == "no-store"


async def test_successful_capability_probe_does_not_authorize_saved_document_access():
    from app.api.resume_engine_routes import router
    from app.database.connection import get_db

    app = FastAPI()
    app.include_router(public_router)
    app.include_router(router)
    # No database access is needed to reject an unauthenticated document read.
    app.dependency_overrides[get_db] = lambda: object()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/public/engine/capabilities")).status_code == 200
        response = await client.get("/resumes/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee/engine/document")
    assert response.status_code == 401
