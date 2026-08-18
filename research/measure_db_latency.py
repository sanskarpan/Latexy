"""
Measure database latency from INSIDE a Modal container.

Read-only. Research instrument for research/COMPETITIVE-ANALYSIS.md — not part of
the deployed app, and not imported by it.

    modal run research/measure_db_latency.py

Why from inside Modal: measuring from a laptop conflates three things — the
~0.55s TCP+TLS setup to Modal from outside the region, Modal's own request
overhead, and the container-to-Neon round trip. Only the last is actionable, and
only a container can see it in isolation.

The hypothesis under test: authenticated reads cost ~1.3s more than an endpoint
that touches no database (/byok/providers 1.2s TTFB vs /me 2.5s). If a warm,
pooled query is single-digit milliseconds, that 1.3s is connection establishment
per request, not query time — a very different fix.
"""

from pathlib import Path
import sys

import modal

_BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))
from modal_app import _secrets, worker_image  # noqa: E402

app = modal.App("latexy-research-db-latency")


@app.function(image=worker_image, secrets=_secrets, timeout=300)
def measure() -> dict:
    import os
    import statistics
    import sys
    import time

    sys.path.insert(0, "/backend")
    import asyncio

    import asyncpg

    raw = os.environ.get("DATABASE_URL", "")
    url = raw.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("+asyncpg", "")
    for junk in ("&channel_binding=require", "?channel_binding=require"):
        url = url.replace(junk, "")

    out: dict = {"host": url.split("@")[-1].split("/")[0] if "@" in url else "?"}

    async def run() -> None:
        # 1. Cost of establishing a brand-new connection, which is what a request
        #    pays if nothing is pooled.
        fresh = []
        for _ in range(5):
            t = time.perf_counter()
            c = await asyncpg.connect(url, timeout=30)
            await c.fetchval("SELECT 1")
            fresh.append((time.perf_counter() - t) * 1000)
            await c.close()
        out["fresh_connect_plus_query_ms"] = [round(x, 1) for x in fresh]
        out["fresh_median_ms"] = round(statistics.median(fresh), 1)

        # 2. Query time on an already-open connection — the true floor.
        c = await asyncpg.connect(url, timeout=30)
        warm = []
        for _ in range(20):
            t = time.perf_counter()
            await c.fetchval("SELECT 1")
            warm.append((time.perf_counter() - t) * 1000)
        out["warm_query_ms_median"] = round(statistics.median(warm), 2)
        out["warm_query_ms_p95"] = round(sorted(warm)[18], 2)

        # 3. Representative real queries, warm, to separate query cost from
        #    connection cost for the endpoints measured from outside.
        real = {}
        for label, sql in (
            ("session_lookup_by_token", 'SELECT 1 FROM session WHERE token = $1 LIMIT 1'),
            ("templates_list_147", "SELECT id, name, category FROM resume_templates WHERE is_active LIMIT 200"),
            ("count_templates", "SELECT count(*) FROM resume_templates"),
        ):
            t = time.perf_counter()
            if "$1" in sql:
                await c.fetch(sql, "definitely-not-a-real-token")
            else:
                await c.fetch(sql)
            real[label] = round((time.perf_counter() - t) * 1000, 2)
        out["warm_real_queries_ms"] = real

        # 4. Is a pool actually cheap once established?
        t = time.perf_counter()
        pool = await asyncpg.create_pool(url, min_size=1, max_size=4, timeout=30)
        out["pool_create_ms"] = round((time.perf_counter() - t) * 1000, 1)
        acq = []
        for _ in range(10):
            t = time.perf_counter()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            acq.append((time.perf_counter() - t) * 1000)
        out["pooled_acquire_plus_query_ms_median"] = round(statistics.median(acq), 2)
        await pool.close()
        await c.close()

    asyncio.run(run())
    return out


@app.local_entrypoint()
def main() -> None:
    import json

    print(json.dumps(measure.remote(), indent=2))


@app.function(image=worker_image, secrets=_secrets, timeout=300)
def measure_redis_and_middleware() -> dict:
    """Redis round-trip from inside Modal, plus the per-request middleware cost."""
    import os
    import statistics
    import sys
    import time

    sys.path.insert(0, "/backend")
    out: dict = {}
    url = os.environ.get("REDIS_URL", "")
    # Never print credentials.
    out["redis_host"] = url.split("@")[-1] if "@" in url else url.split("//")[-1]

    try:
        import redis as sync_redis

        t = time.perf_counter()
        r = sync_redis.from_url(url, socket_connect_timeout=10, socket_timeout=10)
        r.ping()
        out["connect_plus_ping_ms"] = round((time.perf_counter() - t) * 1000, 1)

        pings = []
        for _ in range(20):
            t = time.perf_counter()
            r.ping()
            pings.append((time.perf_counter() - t) * 1000)
        out["warm_ping_ms_median"] = round(statistics.median(pings), 2)
        out["warm_ping_ms_p95"] = round(sorted(pings)[18], 2)

        # The rate limiter runs a Lua script on EVERY request (two INCRs + EXPIREs).
        script = r.register_script(
            "local m = redis.call('INCR', KEYS[1])\n"
            "if m == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end\n"
            "local h = redis.call('INCR', KEYS[2])\n"
            "if h == 1 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end\n"
            "return {m, h}"
        )
        evals = []
        for i in range(10):
            t = time.perf_counter()
            script(keys=[f"research:probe:m:{i}", f"research:probe:h:{i}"], args=[60, 3600])
            evals.append((time.perf_counter() - t) * 1000)
        out["ratelimit_lua_ms_median"] = round(statistics.median(evals), 2)
        for i in range(10):
            r.delete(f"research:probe:m:{i}", f"research:probe:h:{i}")
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]

    return out


@app.local_entrypoint()
def redis_probe() -> None:
    import json

    print(json.dumps(measure_redis_and_middleware.remote(), indent=2))


@app.function(image=worker_image, secrets=_secrets, timeout=600)
def measure_api_from_region(token: str) -> dict:
    """
    Time the production API from inside Modal, i.e. same region as the app.

    Removes the ~0.55s TCP+TLS setup a laptop outside the region pays, so what
    remains is Modal's ingress plus the application itself.
    """
    import statistics
    import time
    import urllib.request

    base = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
    out: dict = {}
    for ep in ["/health", "/me", "/templates/", "/analytics/me?days=30", "/byok/providers"]:
        times = []
        for _ in range(5):
            req = urllib.request.Request(base + ep, headers={"Authorization": f"Bearer {token}"})
            t = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    r.read()
                times.append((time.perf_counter() - t) * 1000)
            except Exception as exc:
                times.append(-1.0)
                out[ep + "_error"] = type(exc).__name__
        good = [x for x in times if x > 0]
        out[ep] = {
            "median_ms": round(statistics.median(good), 0) if good else None,
            "min_ms": round(min(good), 0) if good else None,
        }
    return out


@app.local_entrypoint()
def api_probe(token: str = "") -> None:
    import json

    print(json.dumps(measure_api_from_region.remote(token), indent=2))
