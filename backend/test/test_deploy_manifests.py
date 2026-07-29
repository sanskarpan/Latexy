"""Consistency tests for the production deploy path.

These guard the class of failure where the image, the reverse proxy, the compose
healthcheck and the k8s probes each pick a different port / env var name and the
whole stack silently fails to come up. Nothing here needs a running cluster.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

BACKEND_PORT = "8030"
FRONTEND_PORT = "5180"


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text()


def _load_all(relative: str) -> list:
    return [doc for doc in yaml.safe_load_all(_read(relative)) if doc]


def _k8s_manifests() -> list:
    docs = []
    for path in sorted((REPO_ROOT / "k8s").rglob("*.yaml")):
        docs.extend(doc for doc in yaml.safe_load_all(path.read_text()) if doc)
    return docs


def _containers(doc: dict) -> list:
    if doc.get("kind") != "Deployment":
        return []
    return doc["spec"]["template"]["spec"]["containers"]


def _env_names(container: dict) -> set:
    return {entry["name"] for entry in container.get("env", [])}


# --------------------------------------------------------------------------- #
#  Ports                                                                       #
# --------------------------------------------------------------------------- #


def test_backend_image_listens_on_the_port_everyone_targets():
    dockerfile = _read("backend/Dockerfile.prod")
    assert f"ENV PORT={BACKEND_PORT}" in dockerfile
    assert f"EXPOSE {BACKEND_PORT}" in dockerfile
    # uvicorn must take the port from the env var, not a second hardcoded value.
    assert '--port \\"${PORT}\\"' in dockerfile
    assert "8000" not in dockerfile


def test_frontend_image_listens_on_the_port_nginx_proxies_to():
    dockerfile = _read("frontend/Dockerfile.prod")
    assert f"PORT={FRONTEND_PORT}" in dockerfile
    assert f"EXPOSE {FRONTEND_PORT}" in dockerfile
    assert "3000" not in dockerfile


def test_nginx_upstreams_match_the_container_ports():
    conf = _read("nginx/nginx.conf")
    assert f"server backend:{BACKEND_PORT}" in conf
    assert f"server frontend:{FRONTEND_PORT}" in conf


@pytest.mark.parametrize(
    "deployment,port",
    [("latexy-backend", BACKEND_PORT), ("latexy-frontend", FRONTEND_PORT)],
)
def test_k8s_container_ports_and_probes_agree(deployment, port):
    doc = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == deployment
    )
    container = _containers(doc)[0]
    assert container["ports"][0]["containerPort"] == int(port)
    for probe in ("livenessProbe", "readinessProbe"):
        assert container[probe]["httpGet"]["port"] == int(port)
    assert {"name": "PORT", "value": port} in container["env"]


# --------------------------------------------------------------------------- #
#  Required settings                                                           #
# --------------------------------------------------------------------------- #

# Settings.model_post_init raises at import time without these.
REQUIRED_BACKEND_ENV = {
    "DATABASE_URL",
    "BETTER_AUTH_SECRET",
    "JWT_SECRET_KEY",
    "API_KEY_ENCRYPTION_KEY",
}

# Every service that imports app.core.config.
PYTHON_COMPOSE_SERVICES = ["backend", "celery-worker", "celery-beat", "flower"]
PYTHON_K8S_DEPLOYMENTS = ["latexy-backend", "celery-worker", "celery-beat", "flower"]


# The API pod enqueues compile/optimize/ATS work itself. Without an explicit
# broker it falls back to config.py's redis://localhost:6379 defaults, which
# point at nothing inside a k8s pod.
REQUIRED_BROKER_ENV = {
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "REDIS_URL",
    "REDIS_CACHE_URL",
}


@pytest.mark.parametrize("service", PYTHON_COMPOSE_SERVICES)
def test_compose_services_pass_every_required_setting(service):
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    env = {
        entry.split("=", 1)[0]
        for entry in compose["services"][service]["environment"]
    }
    assert REQUIRED_BACKEND_ENV <= env


def test_api_pod_points_celery_at_the_shared_broker():
    """The API enqueues tasks itself; the localhost defaults are a dead broker."""
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    env = {
        entry.split("=", 1)[0]
        for entry in compose["services"]["backend"]["environment"]
    }
    assert REQUIRED_BROKER_ENV <= env

    doc = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "latexy-backend"
    )
    assert REQUIRED_BROKER_ENV <= _env_names(_containers(doc)[0])


def test_k8s_broker_env_references_a_secret_key_deploy_sh_creates():
    """A secretKeyRef to a missing key leaves the pod stuck in CreateContainerConfigError."""
    deploy_sh = _read("k8s/deploy.sh")
    referenced = {
        entry["valueFrom"]["secretKeyRef"]["key"]
        for doc in _k8s_manifests()
        for container in _containers(doc)
        for entry in container.get("env", [])
        if entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
        == "latexy-secrets"
    }
    for key in sorted(referenced):
        assert f"--from-literal={key}=" in deploy_sh, key


@pytest.mark.parametrize("deployment", PYTHON_K8S_DEPLOYMENTS)
def test_k8s_python_deployments_pass_every_required_setting(deployment):
    doc = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == deployment
    )
    assert REQUIRED_BACKEND_ENV <= _env_names(_containers(doc)[0])


# The frontend container *is* the auth server: nginx proxies /api/auth/ and
# /api/byok/ to it. frontend/src/lib/auth.ts throws without BETTER_AUTH_SECRET
# in production and opens a pg Pool straight from DATABASE_URL; middleware.ts
# and app/api/byok/_forward.ts fetch() BACKEND_URL server-side, which must be an
# absolute URL (NEXT_PUBLIC_API_URL is the same-origin path "/api").
REQUIRED_FRONTEND_ENV = {
    "BETTER_AUTH_SECRET",
    "DATABASE_URL",
    "BETTER_AUTH_URL",
    "BACKEND_URL",
    # lib/email.ts refuses the console-logging fallback in production, so
    # sign-up and password reset throw without a provider key.
    "RESEND_API_KEY",
}


def test_compose_frontend_can_actually_serve_auth():
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    env = {
        entry.split("=", 1)[0]
        for entry in compose["services"]["frontend"]["environment"]
    }
    assert REQUIRED_FRONTEND_ENV <= env


def test_k8s_frontend_can_actually_serve_auth():
    doc = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "latexy-frontend"
    )
    assert REQUIRED_FRONTEND_ENV <= _env_names(_containers(doc)[0])


def test_frontend_backend_url_is_absolute_and_reachable_in_network():
    """`fetch('/api/...')` from Node throws 'Failed to parse URL'."""
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    compose_value = next(
        entry.split("=", 1)[1]
        for entry in compose["services"]["frontend"]["environment"]
        if entry.startswith("BACKEND_URL=")
    )
    assert compose_value == f"http://backend:{BACKEND_PORT}"

    doc = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "latexy-frontend"
    )
    k8s_value = next(
        entry["value"]
        for entry in _containers(doc)[0]["env"]
        if entry["name"] == "BACKEND_URL"
    )
    assert k8s_value == f"http://latexy-backend-service:{BACKEND_PORT}"


def test_production_flag_uses_the_variable_config_actually_reads():
    """FASTAPI_ENV is read nowhere; Settings reads ENVIRONMENT."""
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    for service in PYTHON_COMPOSE_SERVICES:
        env = compose["services"][service]["environment"]
        assert "ENVIRONMENT=production" in env
        assert not any(entry.startswith("FASTAPI_ENV=") for entry in env)

    for deployment in PYTHON_K8S_DEPLOYMENTS:
        doc = next(
            d
            for d in _k8s_manifests()
            if d.get("kind") == "Deployment" and d["metadata"]["name"] == deployment
        )
        names = _env_names(_containers(doc)[0])
        assert "ENVIRONMENT" in names
        assert "FASTAPI_ENV" not in names


def test_backend_trusts_the_bundled_nginx_for_client_ips():
    """Without this, every real user shares one 'untrusted proxy' rate-limit bucket.

    nginx always sets X-Forwarded-For, so with TRUST_PROXY_HEADERS unset the whole
    user base lands in a single bucket and one caller can 429 the site.
    """
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    assert "TRUST_PROXY_HEADERS=true" in compose["services"]["backend"]["environment"]

    backend = next(
        d
        for d in _k8s_manifests()
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "latexy-backend"
    )
    assert "TRUST_PROXY_HEADERS" in _env_names(_containers(backend)[0])

    # …and it is only trustworthy because nginx overwrites X-Real-IP itself.
    for conf in _nginx_configs().values():
        assert "proxy_set_header X-Real-IP $remote_addr;" in conf


def test_k8s_nginx_service_preserves_the_client_source_address():
    """X-Real-IP is only worth trusting if $remote_addr is the client.

    A type: LoadBalancer Service without externalTrafficPolicy: Local is SNAT'd by
    kube-proxy, so $remote_addr — and therefore the X-Real-IP the backend trusts and
    nginx's own $binary_remote_addr limit_req zones — is the node IP. Every anonymous
    user behind a node would then share one rate-limit bucket, which is exactly the
    shared-bucket DoS TRUST_PROXY_HEADERS was supposed to remove. The alternative, for
    an L7 cloud LB in front, is recovering the client with the real_ip module.
    """
    service = next(
        d
        for d in _load_all("k8s/nginx/nginx.yaml")
        if d.get("kind") == "Service" and d["metadata"]["name"] == "nginx-service"
    )
    conf = _nginx_configs()["k8s"]
    assert (
        service["spec"].get("externalTrafficPolicy") == "Local"
        or ("set_real_ip_from" in conf and "real_ip_header" in conf)
    ), "nginx sees the node IP, not the client IP"


# --------------------------------------------------------------------------- #
#  Routing                                                                     #
# --------------------------------------------------------------------------- #


def _nginx_configs() -> dict:
    k8s_nginx = next(
        d
        for d in _load_all("k8s/nginx/nginx.yaml")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "nginx-config"
    )
    return {
        "compose": _read("nginx/nginx.conf"),
        "k8s": k8s_nginx["data"]["nginx.conf"],
    }


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_api_prefix_is_stripped_before_reaching_fastapi(name):
    """`proxy_pass http://backend;` (no trailing slash) keeps the /api prefix
    and 404s on every REST call."""
    conf = _nginx_configs()[name]
    block = re.search(r"location /api/ \{(.*?)\n(\s*)\}", conf, re.S).group(1)
    assert "proxy_pass http://backend/;" in block


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_next_route_handlers_stay_on_the_frontend(name):
    conf = _nginx_configs()[name]
    for prefix in ("/api/auth/", "/api/byok/"):
        block = re.search(
            rf"location {re.escape(prefix)} \{{(.*?)\n(\s*)\}}", conf, re.S
        ).group(1)
        assert "proxy_pass http://frontend;" in block


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_auth_prefix_is_not_under_the_strict_login_rate_limit(name):
    """`/api/auth/` also carries get-session, which useSession() fires on every
    page load from every page. Putting the whole prefix in the 5r/m `login`
    zone made the app unusable behind any shared/NAT IP."""
    conf = _nginx_configs()[name]
    block = re.search(r"location /api/auth/ \{(.*?)\n(\s*)\}", conf, re.S).group(1)
    assert "zone=api" in block
    assert "zone=login" not in block


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_credential_endpoints_keep_a_strict_rate_limit(name):
    """Brute-force protection must survive the get-session fix: the actual
    credential-submitting endpoints get exact-match blocks in `login`."""
    conf = _nginx_configs()[name]
    assert "zone=login" in conf
    for path in (
        "/api/auth/sign-in/email",
        "/api/auth/sign-up/email",
        "/api/auth/request-password-reset",
        "/api/auth/reset-password",
    ):
        block = re.search(
            rf"location = {re.escape(path)} \{{(.*?)\n(\s*)\}}", conf, re.S
        )
        assert block, f"{name}: no exact-match block for {path}"
        assert "zone=login" in block.group(1)
        assert "proxy_pass http://frontend;" in block.group(1)


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_websocket_location_matches_the_backend_route(name):
    """Backend serves /ws/jobs; the old /jobs/ws/ block was dead config."""
    conf = _nginx_configs()[name]
    assert "location /ws/ {" in conf
    assert "/jobs/ws/" not in conf


@pytest.mark.parametrize("name", ["compose", "k8s"])
def test_collab_socket_never_lands_in_the_rest_api_location(name):
    """`location /api/` carries `limit_conn 10` and a short read timeout.

    A permanently-open editor socket routed there burns one of ten per-IP
    connection slots per tab, so a handful of collaborators behind one NAT
    503s every REST call for that IP.
    """
    conf = _nginx_configs()[name]
    block = re.search(r"location /api/ws/ \{(.*?)\n(\s*)\}", conf, re.S)
    assert block, f"{name}: no websocket-capable location for /api/ws/"
    body = block.group(1)
    # Trailing slash: /api/ws/collab/<id> must reach the backend as /ws/collab/<id>.
    assert "proxy_pass http://backend/ws/;" in body
    assert 'proxy_set_header Upgrade $http_upgrade;' in body
    assert 'proxy_set_header Connection "upgrade";' in body
    assert "limit_conn" not in body
    assert int(re.search(r"proxy_read_timeout (\d+)", body).group(1)) >= 3600


def test_collab_client_uses_the_websocket_origin_not_the_api_path():
    """In production NEXT_PUBLIC_API_URL is the same-origin path '/api', so
    deriving the collab socket from it produced wss://host/api/ws/collab."""
    editor = _read("frontend/src/components/LaTeXEditor.tsx")
    assert "getCollabWebSocketUrl()" in editor
    assert "NEXT_PUBLIC_API_URL" not in editor

    api_client = _read("frontend/src/lib/api-client.ts")
    builder = re.search(
        r"export function getCollabWebSocketUrl\(\): string \{(.*?)\n\}",
        api_client,
        re.S,
    )
    assert builder, "getCollabWebSocketUrl() is gone"
    assert "getWebSocketBase()}/ws/collab" in builder.group(1)


def test_plain_http_health_endpoint_is_not_a_redirect():
    """The compose healthcheck probes http://localhost:80/health."""
    conf = _read("nginx/nginx.conf")
    http_server = re.search(r"server \{\s*\n\s*listen 80;(.*?)\n    \}", conf, re.S)
    assert http_server, "no plain-HTTP server block found"
    assert "location /health {" in http_server.group(1)


def test_frontend_ws_url_build_arg_must_be_absolute():
    """`${NEXT_PUBLIC_WS_URL}/ws/jobs` is fed to `new URL()`, which rejects
    relative values — a baked '/ws' produced '/ws/ws/jobs' and threw."""
    dockerfile = _read("frontend/Dockerfile.prod")
    assert "ws://*|wss://*" in dockerfile
    assert "NEXT_PUBLIC_WS_URL=/ws" not in dockerfile
    assert "NEXT_PUBLIC_WS_URL=/ws" not in _read(".github/workflows/release.yml")


def test_release_never_passes_an_empty_ws_url_build_arg():
    """A missing `vars.NEXT_PUBLIC_WS_URL` renders empty and the Dockerfile
    guard then aborts the release build. Default to the same public origin
    k8s/namespace.yaml already hardcodes."""
    release = _read(".github/workflows/release.yml")
    line = next(
        ln for ln in release.splitlines() if "NEXT_PUBLIC_WS_URL=${{" in ln
    )
    default = re.search(r"\|\|\s*'(ws{1,2}s?://[^']+)'", line)
    assert default, f"no fallback for an unset repo variable: {line.strip()}"

    namespace = next(
        d
        for d in _load_all("k8s/namespace.yaml")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "latexy-config"
    )
    assert default.group(1) == namespace["data"]["ws-url"]


# --------------------------------------------------------------------------- #
#  Secrets                                                                     #
# --------------------------------------------------------------------------- #


def _env_production() -> dict:
    values = {}
    for line in _read(".env.production").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.split("  #")[0].strip()
    return values


def test_env_production_satisfies_every_hard_compose_guard():
    """release.yml deploys with `--env-file .env.production`; a `${VAR:?}` with
    no key there aborts `docker compose config/pull/up` before anything runs."""
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", _read("docker-compose.prod.yml")))
    assert required, "no ${VAR:?} guards found — did the guards get dropped?"
    assert not required - set(_env_production())


def test_env_production_cors_origins_is_the_json_array_pydantic_expects():
    """pydantic-settings parses List[str] as JSON; a comma-separated value
    raises SettingsError at import and crash-loops every Python service."""
    import json

    raw = _env_production()["CORS_ORIGINS"]
    parsed = json.loads(raw)
    assert isinstance(parsed, list) and parsed
    assert all(origin.startswith("https://") for origin in parsed), parsed


def test_env_production_ws_url_is_an_absolute_websocket_origin():
    """It is baked into the bundle and fed to `new URL()`."""
    assert _env_production()["NEXT_PUBLIC_WS_URL"].startswith(("ws://", "wss://"))


def test_compose_never_falls_back_to_a_default_credential():
    """Every secret must fail at config time rather than ship a guessable value."""
    compose = _read("docker-compose.prod.yml")
    for var in ("POSTGRES_PASSWORD", "GRAFANA_PASSWORD", "FLOWER_PASSWORD"):
        weak = re.findall(rf"\$\{{{var}:-[^}}]*\}}", compose)
        assert not weak, weak
        assert f"${{{var}:?" in compose


def test_unauthenticated_monitoring_ports_are_not_published_publicly():
    """prometheus/alertmanager/tempo ship no auth; grafana is an admin UI."""
    compose = yaml.safe_load(_read("docker-compose.prod.yml"))
    for service in ("prometheus", "alertmanager", "tempo", "grafana"):
        for mapping in compose["services"][service].get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), f"{service}: {mapping}"


def test_no_secret_manifests_are_committed():
    """Secrets are provisioned by k8s/deploy.sh, never checked in."""
    committed = [
        (doc["metadata"]["name"])
        for doc in _k8s_manifests()
        if doc.get("kind") == "Secret"
    ]
    assert committed == []


def test_k8s_images_match_what_the_release_pipeline_publishes():
    release = _read(".github/workflows/release.yml")
    assert "ghcr.io/${{ github.repository_owner }}/latexy-backend" in release
    for doc in _k8s_manifests():
        for container in _containers(doc):
            image = container["image"]
            if "latexy-backend" in image or "latexy-frontend" in image:
                assert image.startswith("ghcr.io/"), image
