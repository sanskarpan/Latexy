"""
Tests for Feature 83 — Keyboard Macro System CRUD API.

Covers:
  1. Unauthenticated request → 401
  2. Create macro → 201 with id and actions
  3. List macros → returns created macro in the list
  4. Update macro name → 200 with new name
  5. Delete macro → 204, subsequent GET → 404
"""

from __future__ import annotations

from httpx import AsyncClient

# ── Helpers ────────────────────────────────────────────────────────────────────

_SAMPLE_ACTIONS = [
    {"type": "insert", "text": "Hello, world!"},
    {"type": "move", "position": {"lineNumber": 1, "column": 1}},
]


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestMacroCRUD:
    """End-to-end CRUD tests against the /macros endpoints."""

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """All macro endpoints require authentication."""
        resp = await client.get("/macros")
        assert resp.status_code == 401

    async def test_create_macro_returns_201_with_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        """POST /macros creates a new macro and returns its full detail."""
        payload = {
            "name": "My Test Macro",
            "description": "A macro created in tests",
            "shortcut": "Ctrl+Shift+1",
            "actions": _SAMPLE_ACTIONS,
        }
        resp = await client.post("/macros", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["name"] == "My Test Macro"
        assert data["shortcut"] == "Ctrl+Shift+1"
        assert len(data["actions"]) == len(_SAMPLE_ACTIONS)

    async def test_list_macros_contains_created_macro(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /macros returns the macro we just created."""
        # Create one
        create_resp = await client.post(
            "/macros",
            json={"name": "List Test Macro", "actions": _SAMPLE_ACTIONS},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        created_id = create_resp.json()["id"]

        # List
        list_resp = await client.get("/macros", headers=auth_headers)
        assert list_resp.status_code == 200
        ids = [m["id"] for m in list_resp.json()]
        assert created_id in ids

    async def test_update_macro_name(
        self, client: AsyncClient, auth_headers: dict
    ):
        """PATCH /macros/{id} updates the macro name and returns updated data."""
        # Create
        create_resp = await client.post(
            "/macros",
            json={"name": "Old Name", "actions": _SAMPLE_ACTIONS},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        macro_id = create_resp.json()["id"]

        # Update
        patch_resp = await client.patch(
            f"/macros/{macro_id}",
            json={"name": "New Name"},
            headers=auth_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "New Name"

    async def test_delete_macro_then_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """DELETE /macros/{id} returns 204; subsequent GET returns 404."""
        # Create
        create_resp = await client.post(
            "/macros",
            json={"name": "To Delete", "actions": _SAMPLE_ACTIONS},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        macro_id = create_resp.json()["id"]

        # Delete
        del_resp = await client.delete(f"/macros/{macro_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        # Should now 404
        get_resp = await client.get(f"/macros/{macro_id}", headers=auth_headers)
        assert get_resp.status_code == 404
