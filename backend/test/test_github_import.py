"""Tests for GitHub project import (Feature 1 — external sources to resume)."""

import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import text

from app.services import github_projects_service as gh
from app.services.encryption_service import encryption_service
from app.workers.github_import_worker import _store_result

# ── rank_repos (pure, no network) ────────────────────────────────────────────


def _repo(
    name,
    *,
    stars=0,
    forks=0,
    pinned=False,
    archived=False,
    readme_bytes=500,
    topics=None,
    description="A project",
    pushed_at="2026-07-01T00:00:00Z",
):
    return {
        "name": name,
        "owner": "octocat",
        "description": description,
        "url": f"https://github.com/octocat/{name}",
        "stars": stars,
        "forks": forks,
        "primary_language": "Python",
        "topics": topics or [],
        "pushed_at": pushed_at,
        "is_archived": archived,
        "readme_bytes": readme_bytes,
        "pinned": pinned,
    }


class TestRankRepos:
    def test_orders_by_score_stars_dominate(self):
        repos = [
            _repo("low", stars=1, forks=0),
            _repo("high", stars=5000, forks=800),
            _repo("mid", stars=100, forks=20),
        ]
        ranked = gh.rank_repos(repos)
        assert [r["name"] for r in ranked] == ["high", "mid", "low"]
        # scores are attached and monotonically non-increasing
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_pinned_boost_beats_a_more_popular_organic_repo(self):
        repos = [
            _repo("popular", stars=100000, forks=50000, pinned=False),
            _repo("pinned", stars=3, forks=1, pinned=True),
        ]
        ranked = gh.rank_repos(repos)
        assert ranked[0]["name"] == "pinned"

    def test_excludes_archived_and_short_readme(self):
        repos = [
            _repo("good", stars=10),
            _repo("archived", stars=999, archived=True),
            _repo("stub", stars=999, readme_bytes=40),  # README < 100 chars
        ]
        ranked = gh.rank_repos(repos)
        names = {r["name"] for r in ranked}
        assert names == {"good"}

    def test_returns_at_most_six(self):
        repos = [_repo(f"r{i}", stars=i) for i in range(20)]
        ranked = gh.rank_repos(repos)
        assert len(ranked) == 6


# ── build_project_evidence (pure) ────────────────────────────────────────────


class TestBuildProjectEvidence:
    def test_shape(self):
        repo = _repo("acme", stars=42, forks=7, pushed_at="2026-06-15T00:00:00Z")
        repo["raw_excerpt"] = "# Acme\nDoes things." * 5
        summary = {
            "summary": "Acme does things well.",
            "suggested_bullets": ["Built X", "Shipped Y"],
            "tech": ["Python", "Redis"],
        }
        ev = gh.build_project_evidence(repo, summary)

        assert ev["source"] == "github"
        assert ev["title"] == "acme"
        assert ev["description"] == "Acme does things well."
        assert ev["tech"] == ["Python", "Redis"]
        assert ev["metrics"] == {"stars": 42, "forks": 7}
        assert ev["dates"] == {"last_active": "2026-06-15T00:00:00Z"}
        assert ev["url"] == "https://github.com/octocat/acme"
        assert ev["suggested_bullets"] == ["Built X", "Shipped Y"]
        assert "raw_excerpt" in ev
        # required keys, exactly
        assert set(ev.keys()) == {
            "source",
            "title",
            "description",
            "tech",
            "metrics",
            "dates",
            "url",
            "suggested_bullets",
            "raw_excerpt",
        }

    def test_falls_back_to_repo_description_when_summary_blank(self):
        repo = _repo("acme", description="Fallback desc")
        ev = gh.build_project_evidence(repo, {"summary": "", "tech": [], "suggested_bullets": []})
        assert ev["description"] == "Fallback desc"


# ── result envelope round-trip ───────────────────────────────────────────────


def test_result_envelope_round_trip():
    payload = {"status": "completed", "projects": [{"title": "x"}]}
    encoded = gh.encode_result(payload)
    assert gh.decode_result(encoded) == payload
    assert gh.decode_result(None) is None
    assert gh.decode_result("!!not-base64!!") is None


def test_worker_result_envelope_is_owner_bound():
    redis = MagicMock()
    with patch(
        "app.workers.github_import_worker.get_worker_redis",
        return_value=redis,
    ):
        _store_result(
            "job-1",
            "user-1",
            {"status": "completed", "projects": [{"title": "safe"}]},
        )

    key, ttl, raw = redis.setex.call_args.args
    assert key == gh.import_result_key("job-1")
    assert ttl == gh.IMPORT_RESULT_TTL
    assert gh.decode_result(raw) == {
        "user_id": "user-1",
        "status": "completed",
        "projects": [{"title": "safe"}],
    }


# ── Endpoint tests ───────────────────────────────────────────────────────────


async def _user_id_for_headers(db_session, headers) -> str:
    row = await db_session.execute(
        text('SELECT "userId" FROM session WHERE token = :t'),
        {"t": headers["Authorization"].replace("Bearer ", "")},
    )
    return row.scalar_one()


async def _connect_github(db_session, headers) -> str:
    """Set an encrypted GitHub token on the auth_headers user; return user_id."""
    user_id = await _user_id_for_headers(db_session, headers)
    await db_session.execute(
        text("UPDATE users SET github_access_token = :tok, github_username = 'octocat' WHERE id = :id"),
        {"tok": encryption_service.encrypt("gho_testtoken"), "id": user_id},
    )
    await db_session.commit()
    return user_id


class TestImportEndpoints:
    async def test_post_requires_connected_github(self, client, auth_headers):
        """Without a connected GitHub account the POST returns 400."""
        resp = await client.post("/github/import-projects", headers=auth_headers)
        assert resp.status_code == 400
        assert "not connected" in resp.json()["detail"].lower()

    async def test_post_returns_job_id(self, client, auth_headers, db_session, monkeypatch):
        user_id = await _connect_github(db_session, auth_headers)

        captured = {}

        def _fake_submit(*, job_id, user_id, github_token, api_key, user_plan="free"):
            captured.update(
                job_id=job_id,
                user_id=user_id,
                github_token=github_token,
                api_key=api_key,
                user_plan=user_plan,
            )
            return job_id

        monkeypatch.setattr("app.api.github_routes.submit_github_import", _fake_submit)

        resp = await client.post("/github/import-projects", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body and body["job_id"]
        # the decrypted GitHub token is handed to the worker; no BYOK key → None
        assert captured["github_token"] == "gho_testtoken"
        assert captured["api_key"] is None
        assert captured["job_id"] == body["job_id"]

        from app.core.redis import get_redis_client

        redis = await get_redis_client()
        marker = gh.decode_result(await redis.get(gh.import_result_key(body["job_id"])))
        assert marker == {
            "user_id": user_id,
            "status": "pending",
            "projects": [],
        }

    async def test_get_returns_404_when_absent(self, client, auth_headers):
        resp = await client.get(f"/github/import-projects/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_get_returns_pending_for_owned_marker(self, client, auth_headers, db_session):
        from app.core.redis import get_redis_client

        user_id = await _user_id_for_headers(db_session, auth_headers)
        job_id = str(uuid.uuid4())
        redis = await get_redis_client()
        await redis.setex(
            gh.import_result_key(job_id),
            gh.IMPORT_RESULT_TTL,
            gh.encode_result(
                {
                    "user_id": user_id,
                    "status": "pending",
                    "projects": [],
                }
            ),
        )

        resp = await client.get(f"/github/import-projects/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "pending",
            "projects": [],
            "error": None,
        }

    async def test_get_returns_stored_evidence(self, client, auth_headers, db_session):
        from app.core.redis import get_redis_client

        user_id = await _user_id_for_headers(db_session, auth_headers)
        job_id = str(uuid.uuid4())
        projects = [
            {
                "source": "github",
                "title": "acme",
                "description": "does things",
                "tech": ["Python"],
                "metrics": {"stars": 9, "forks": 2},
                "dates": {"last_active": "2026-07-01T00:00:00Z"},
                "url": "https://github.com/octocat/acme",
                "suggested_bullets": ["Built acme"],
                "raw_excerpt": "# acme",
            }
        ]
        redis = await get_redis_client()
        await redis.setex(
            gh.import_result_key(job_id),
            gh.IMPORT_RESULT_TTL,
            gh.encode_result(
                {
                    "user_id": user_id,
                    "status": "completed",
                    "projects": projects,
                }
            ),
        )

        resp = await client.get(f"/github/import-projects/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["projects"] == projects

    async def test_get_returns_owned_failure(self, client, auth_headers, db_session):
        from app.core.redis import get_redis_client

        user_id = await _user_id_for_headers(db_session, auth_headers)
        job_id = str(uuid.uuid4())
        redis = await get_redis_client()
        await redis.setex(
            gh.import_result_key(job_id),
            gh.IMPORT_RESULT_TTL,
            gh.encode_result(
                {
                    "user_id": user_id,
                    "status": "failed",
                    "projects": [],
                    "error": "GitHub unavailable",
                }
            ),
        )

        resp = await client.get(f"/github/import-projects/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "failed",
            "projects": [],
            "error": "GitHub unavailable",
        }

    async def test_get_hides_another_users_job(self, client, auth_headers, auth_headers2, db_session):
        from app.core.redis import get_redis_client

        owner_id = await _user_id_for_headers(db_session, auth_headers)
        job_id = str(uuid.uuid4())
        redis = await get_redis_client()
        await redis.setex(
            gh.import_result_key(job_id),
            gh.IMPORT_RESULT_TTL,
            gh.encode_result(
                {
                    "user_id": owner_id,
                    "status": "completed",
                    "projects": [{"title": "private-to-owner"}],
                }
            ),
        )

        resp = await client.get(f"/github/import-projects/{job_id}", headers=auth_headers2)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Import job not found"

    async def test_get_hides_legacy_ownerless_result(self, client, auth_headers):
        from app.core.redis import get_redis_client

        job_id = str(uuid.uuid4())
        redis = await get_redis_client()
        await redis.setex(
            gh.import_result_key(job_id),
            gh.IMPORT_RESULT_TTL,
            gh.encode_result(
                {
                    "status": "completed",
                    "projects": [{"title": "legacy"}],
                }
            ),
        )

        resp = await client.get(f"/github/import-projects/{job_id}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_submit_failure_removes_pending_marker(self, client, auth_headers, db_session, monkeypatch):
        from app.core.redis import get_redis_client

        await _connect_github(db_session, auth_headers)
        captured_job_id = None

        def _fail_submit(**kwargs):
            nonlocal captured_job_id
            captured_job_id = kwargs["job_id"]
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr("app.api.github_routes.submit_github_import", _fail_submit)

        resp = await client.post("/github/import-projects", headers=auth_headers)
        assert resp.status_code == 503
        assert captured_job_id is not None
        redis = await get_redis_client()
        assert await redis.get(gh.import_result_key(captured_job_id)) is None

    async def test_endpoints_require_auth(self, client):
        assert (await client.post("/github/import-projects")).status_code in (401, 403)
        assert (await client.get(f"/github/import-projects/{uuid.uuid4()}")).status_code in (401, 403)
