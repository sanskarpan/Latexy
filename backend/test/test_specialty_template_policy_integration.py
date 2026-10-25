"""B05 HTTP acceptance with the existing disposable PostgreSQL/Redis fixtures.

Only object storage is synthetic: these tests prove route admission, SQL catalog
filtering, and policy restoration, not provider storage or renderer acceptance.
The ordinary Backend Tests job selects this file without an opt-in environment.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

import pytest
from sqlalchemy import delete, select, text

from app.database.models import FeatureFlag, ResumeTemplate, RoleFeature, User
from app.services import storage_service
from app.services.entitlement_service import entitlement_service
from test.test_admin_control_plane_api import _create_session, _create_user

_SPECIALTY_CATEGORIES = ("academic", "regional", "presentation")
_ORDINARY_CATEGORY = "software_engineering"
_ASSETS = {"thumbnail": ("png", "image/png"), "pdf": ("pdf", "application/pdf")}

# This suite must never turn a requested integration run into a green unit-only
# run. conftest also fails when its real Redis/PostgreSQL services are absent.
if os.environ.get("SKIP_INFRA_CHECK", "").lower() in {"1", "true", "yes"}:
    raise pytest.UsageError(
        "B05 route acceptance requires the real isolated PostgreSQL/Redis fixtures; unset SKIP_INFRA_CHECK"
    )


@pytest.fixture
async def policy_cell(db_session, role, policy_axis):
    if policy_axis == "global":
        statement = select(FeatureFlag.enabled).where(FeatureFlag.key == "b05")
    else:
        statement = select(RoleFeature.enabled).where(RoleFeature.role == role, RoleFeature.feature_key == "b05")
    original = (await db_session.execute(statement)).scalar_one()

    async def set_enabled(enabled, *, expected_enabled=None):
        if policy_axis == "global":
            await entitlement_service.set_kill_switch("b05", enabled, db_session, expected_enabled=expected_enabled)
        else:
            await entitlement_service.set_role_cell(role, "b05", enabled, db_session, expected_enabled=expected_enabled)

    try:
        yield set_enabled
    finally:
        await db_session.rollback()
        await set_enabled(original)
        assert (await db_session.execute(statement)).scalar_one() is original


@pytest.fixture
async def actor(db_session, role):
    if role == "anonymous":
        yield {}
        return
    owner, _ = await _create_user(db_session, role=role, plan="pro")
    token = await _create_session(db_session, owner)
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        await db_session.rollback()
        await db_session.execute(text("DELETE FROM session WHERE token = :token"), {"token": token})
        await db_session.execute(delete(User).where(User.id == owner))
        await db_session.commit()


@dataclass
class SyntheticStorage:
    """Call-counted route boundary; no object store or signed URL is contacted."""

    objects: dict[str, bytes]
    calls: list[tuple[str, str]] = field(default_factory=list)
    stream: bool = False

    def file_exists(self, key):
        self.calls.append(("exists", key))
        assert key in self.objects, f"Unexpected storage key: {key}"
        return True

    def generate_presigned_url(self, key, *, ttl):
        self.calls.append(("presign", key))
        assert key in self.objects, f"Unexpected storage key: {key}"
        assert ttl == 86400
        if self.stream:
            raise RuntimeError("Synthetic presigning unavailable; exercise streaming fallback")
        return f"https://synthetic-storage.invalid/{key}"

    def download_bytes(self, key, max_bytes):
        self.calls.append(("download", key))
        assert key in self.objects, f"Unexpected storage key: {key}"
        assert len(self.objects[key]) <= max_bytes
        return self.objects[key]


@pytest.fixture
async def catalog(db_session, monkeypatch):
    name_prefix = f"test_tmpl_b05_{uuid.uuid4().hex}"
    templates = {}
    for category in (*_SPECIALTY_CATEGORIES, _ORDINARY_CATEGORY):
        template = ResumeTemplate(
            name=f"{name_prefix}_{category}",
            description="Synthetic B05 route acceptance fixture",
            category=category,
            tags=[],
            latex_content=r"\documentclass{article}\begin{document}Synthetic fixture\end{document}",
            is_active=True,
            sort_order=0,
            document_type={"academic": "academic_cv", "presentation": "presentation"}.get(category, "resume"),
        )
        db_session.add(template)
        templates[category] = template
    await db_session.commit()
    # Other fixture rollbacks expire ORM attributes before this teardown runs.
    # Keep immutable IDs while the inserted objects are still loaded.
    template_ids = tuple(template.id for template in templates.values())
    storage = SyntheticStorage(
        {
            f"templates/{template.id}.{extension}": f"Synthetic {category} {extension} bytes".encode()
            for category, template in templates.items()
            for extension, _ in _ASSETS.values()
        }
    )
    monkeypatch.setattr(storage_service, "file_exists", storage.file_exists)
    monkeypatch.setattr(storage_service, "generate_presigned_url", storage.generate_presigned_url)
    monkeypatch.setattr(storage_service, "download_bytes", storage.download_bytes)
    try:
        yield name_prefix, templates, storage
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(ResumeTemplate).where(ResumeTemplate.id.in_(template_ids))
        )
        await db_session.commit()


async def _assert_catalog(client, headers, name_prefix, templates, *, enabled):
    response = await client.get("/templates/", params={"search": name_prefix}, headers=headers)
    assert response.status_code == 200, response.text
    expected = set(templates) if enabled else {_ORDINARY_CATEGORY}
    assert {row["id"] for row in response.json()} == {templates[category].id for category in expected}

    categories = await client.get("/templates/categories", headers=headers)
    assert categories.status_code == 200, categories.text
    counts = {row["category"]: row["count"] for row in categories.json()}
    assert counts[_ORDINARY_CATEGORY] >= 1
    for category in _SPECIALTY_CATEGORIES:
        if enabled:
            assert counts[category] >= 1
        else:
            assert category not in counts

        # Explicit category URLs must not defeat the SQL catalog filter.
        filtered = await client.get(
            "/templates/",
            params={"search": name_prefix, "category": category},
            headers=headers,
        )
        assert filtered.status_code == 200, filtered.text
        assert [row["id"] for row in filtered.json()] == ([templates[category].id] if enabled else [])


async def _assert_assets_allowed(client, headers, template, storage):
    for asset, (extension, media_type) in _ASSETS.items():
        path = f"/templates/{template.id}/{asset}"
        key = f"templates/{template.id}.{extension}"
        storage.calls.clear()
        head = await client.head(path, headers=headers)
        assert head.status_code == 200, head.text
        assert head.content == b""
        assert head.headers["content-type"] == media_type
        assert head.headers["cache-control"] == "private, no-store"
        assert storage.calls == [("exists", key)]

        # The same real route is admitted through both delivery paths. The
        # synthetic redirect is inspected only; it is never followed.
        for stream in (False, True):
            storage.stream = stream
            storage.calls.clear()
            response = await client.get(path, headers=headers, follow_redirects=False)
            assert response.headers["cache-control"] == "private, no-store"
            if stream:
                assert response.status_code == 200, response.text
                assert response.headers["content-type"] == media_type
                assert response.content == storage.objects[key]
                assert storage.calls == [("presign", key), ("download", key)]
            else:
                assert response.status_code == 307, response.text
                assert response.headers["location"] == f"https://synthetic-storage.invalid/{key}"
                assert storage.calls == [("presign", key)]


async def _assert_assets_denied(client, headers, template, storage):
    for asset in _ASSETS:
        for method in ("HEAD", "GET"):
            storage.calls.clear()
            response = await client.request(
                method,
                f"/templates/{template.id}/{asset}",
                headers=headers,
                follow_redirects=False,
            )
            assert response.status_code == 403, response.text
            if method == "GET":
                assert response.json()["error"]["code"] == "feature_disabled"
                assert "b05" in response.json()["error"]["message"]
            assert storage.calls == [], "A denied specialty route must not reach storage"


@pytest.mark.parametrize("role", ["anonymous", "user", "support", "admin"])
@pytest.mark.parametrize("policy_axis", ["global", "role"])
async def test_specialty_catalog_assets_revoke_and_restore_via_real_policy(
    client,
    catalog,
    actor,
    policy_cell,
):
    name_prefix, templates, storage = catalog
    headers = actor

    # Warm both the actual policy path and each preview URL before revocation.
    # The OFF and restored requests use the same identity, session, and URLs.
    for phase, enabled in enumerate((True, False, True)):
        if phase:
            await policy_cell(enabled, expected_enabled=not enabled)
        effective = await client.get("/config/entitlements", headers=headers)
        assert effective.status_code == 200, effective.text
        assert effective.json()["features"]["b05"] is enabled
        assert effective.json()["features"]["b04"] is True
        await _assert_catalog(client, headers, name_prefix, templates, enabled=enabled)

        for category, template in templates.items():
            if enabled or category == _ORDINARY_CATEGORY:
                await _assert_assets_allowed(client, headers, template, storage)
            else:
                await _assert_assets_denied(client, headers, template, storage)
