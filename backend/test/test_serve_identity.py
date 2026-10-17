"""Serving-revision attestation: validation, /health publication and images.

The backend used to report only the static ``APP_VERSION`` ("1.0.0"), so a
frontend and backend serving different commits were indistinguishable from the
response itself while both looked healthy. These tests pin the validation rules
that keep an unvalidated environment value from ever reaching a public endpoint.
"""

from unittest.mock import patch

from httpx import AsyncClient

from app.core.serve_identity import deployment_target, serving_revision

VALID_SHA = "fc3e3df9484d8c750bcbf178a04c3013640e113a"


class TestServingRevision:
    def test_returns_validated_lowercase_sha(self):
        assert serving_revision({"DEPLOY_SHA": VALID_SHA}) == VALID_SHA

    def test_normalizes_surrounding_whitespace_and_case(self):
        assert serving_revision({"DEPLOY_SHA": f"  {VALID_SHA.upper()}  "}) == VALID_SHA

    def test_unset_is_unattested(self):
        assert serving_revision({}) is None

    def test_blank_is_unattested(self):
        assert serving_revision({"DEPLOY_SHA": "   "}) is None

    def test_short_value_is_unattested(self):
        assert serving_revision({"DEPLOY_SHA": VALID_SHA[:39]}) is None

    def test_overlong_value_is_unattested(self):
        assert serving_revision({"DEPLOY_SHA": VALID_SHA + "a"}) is None

    def test_non_hex_value_is_unattested(self):
        assert serving_revision({"DEPLOY_SHA": "z" * 40}) is None

    def test_injected_markup_is_unattested(self):
        """A hostile environment value must never be echoed onto /health."""
        assert serving_revision({"DEPLOY_SHA": "<script>alert(1)</script>"}) is None

    def test_pinned_known_answer_vector(self):
        """Frozen vector: any change to normalization must fail this test."""
        environment = {"DEPLOY_SHA": "  FC3E3DF9484D8C750BCBF178A04C3013640E113A "}
        assert serving_revision(environment) == VALID_SHA


class TestDeploymentTarget:
    def test_modal_wins(self):
        assert deployment_target({"DEPLOY_TARGET": "modal"}) == "modal"

    def test_production_environment(self):
        assert deployment_target({"ENVIRONMENT": "production"}) == "production"

    def test_prod_environment(self):
        assert deployment_target({"ENVIRONMENT": "prod"}) == "production"

    def test_default_local(self):
        assert deployment_target({}) == "local"

    def test_unknown_environment_is_local(self):
        assert deployment_target({"ENVIRONMENT": "staging"}) == "local"


class TestHealthAttestation:
    async def test_health_reports_validated_revision(self, client: AsyncClient):
        from app.api import routes

        with patch.object(routes, "serving_revision", return_value=VALID_SHA):
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["commit_sha"] == VALID_SHA

    async def test_health_reports_unattested_when_unknown(self, client: AsyncClient):
        from app.api import routes

        with patch.object(routes, "serving_revision", return_value=None):
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["commit_sha"] is None

    async def test_health_reports_deployment_target(self, client: AsyncClient):
        from app.api import routes

        with patch.object(routes, "deployment_target", return_value="modal"):
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["deployment_target"] == "modal"

    async def test_unvalidated_environment_never_reaches_response(self, client: AsyncClient):
        """A malformed DEPLOY_SHA must surface as null, not as the raw value."""
        with patch.dict("os.environ", {"DEPLOY_SHA": "not-a-sha"}, clear=False):
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["commit_sha"] is None
