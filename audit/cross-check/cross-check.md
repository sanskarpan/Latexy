# Independent cross-check — latency, plan gates, isolation, defect re-test

**Window:** 2026-11-27T11:51:58Z – 11:59:58Z (fresh probes; manual preflight 11:48–11:51Z)
**Repo:** `audit/production-2026-11-27` at `7066b2cf1090383a0fcfbcd9da4b6dbc0fad5afc` (other agents' uncommitted work present; not touched)
**Production:** `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
**Backend commit (live `/health`):** `ee1a405de6058e814c3a6f5ffba5fe3630576421`; `/readyz` 200; `X-Latexy-Deployment-Hold: false`; DB/Redis/cache `ok`
**Vantage:** India (UTC+05:30), single workstation. DNS ≈24 ms, TCP RTT ≈0.25 s, TLS ≈0.49–0.55 s. This is a distant, single-region client, not a user-near-edge measurement.
**Rate:** own 12-request/60 s limiter (limit was 20/min); no compiles, no load ramp, no global/plan/flag/deploy change, no payments, no user creation/deletion. All auth used only the provisioned matrix tokens. The only non-GETs were the two required `POST /ws/ticket` calls (short-lived Redis ticket).

## Method

I did not run the lead's `latency_probe.py` or `probe_http_get.py`. I wrote a separate raw-socket probe that records DNS, TCP connect, TLS, TTFB and total body time per sample, rotates the nine endpoints across three rounds (forward, reverse, rotated), and uses a fresh TCP+TLS connection per sample (matching the lead's per-request transport). I added a keep-alive control on `/health` and `/jobs/health` to separate connection setup from application time, and a separate redirect-chain test for `/resumes`. Correctness checks were fresh requests with status and `X-Request-Id` captured. Raw captures are in the session temp directory (`xcheck_results.json`, `xcheck_followup2.json`); the evidence needed to reproduce the findings is cited below.

## 1. Latency re-run (3 fresh samples per CSV endpoint = 27)

All values are client total (full body) in ms. Status was 200 for every row except `/resumes`, which is a 307 redirect (see below). `Δp50` is fresh median − recorded p50.

| Endpoint (identity) | Fresh samples | p50 | min | max | Recorded p50 / p95 | Δp50 | Recorded p95 vs fresh |
|---|---:|---:|---:|---:|---:|---:|---|
| `/health` (anon) | 3116.7, 1364.1, 1389.8 | 1389.8 | 1364.1 | 3116.7 | 1185.0 / 2926.4 | **+204.8 (+17.3%)** | max 3117 ≈ p95; first sample had a 1.49 s TLS handshake |
| `/readyz` (anon) | 984.2, 951.9, 987.0 | 984.2 | 951.9 | 987.0 | 1177.8 / 1240.3 | **−193.6 (−16.4%)** | all below p95 |
| `/jobs/health` (anon) | 3517.8, 3330.1, 3334.7 | 3334.7 | 3330.1 | 3517.8 | 3553.5 / 4561.6 | **−218.8 (−6.2%)** | all below p95 |
| `/me` (pro) | 995.6, 994.0, 1001.8 | 995.6 | 994.0 | 1001.8 | 1173.1 / 1210.1 | **−177.5 (−15.1%)** | all below p95 |
| `/config/entitlements` (pro) | 1672.0, 1649.5, 1675.3 | 1672.0 | 1649.5 | 1675.3 | 1864.5 / 2331.9 | **−192.5 (−10.3%)** | all below p95 |
| `/subscription/current` (pro) | 1101.7, 1082.1, 1124.9 | 1101.7 | 1082.1 | 1124.9 | 1277.1 / 3446.9 | **−175.4 (−13.7%)** | p95 tail (3.45 s) not seen |
| `/resumes` (pro) | raw 307: 969.5, 975.6, 932.1; **chain**: 9207.6, 2978.6, 4223.0; direct `/resumes/`: 1508.0 | **4223.0 (chain)** | 2978.6 | 9207.6 | 2326.4 / 3219.6 | **+1896.6 (chain; not a like-for-like p50)** | two request cycles; see §1.4 |
| `/resumes/builder/templates` (pro) | 1309.1, 1348.0, 1349.1 | 1348.0 | 1309.1 | 1349.1 | 1290.1 / 1573.5 | **+57.9 (+4.5%)** | all below p95; TTFB p50 1109 ms, body adds ~240 ms |
| `/analytics/admin/overview?days=30` (admin) | 3829.6 (miss), 1196.4 (hit), 3454.1 (miss) | 3454.1 | 1196.4 | 3829.6 | 1405.0 / 3804.5 | **+2049.1** | **bimodal**: hit ≈ recorded p50; miss ≈ recorded p95; both modes reproduced |

Request IDs (sample order; full capture also recorded status and headers):

```
/health              10e80faf-86eb-41ca-a750-524963418537  b6ed0655-4c34-456b-88b2-ba1832eb6f5a  a86fe159-80fc-489d-af3e-3e043412ba0e
/readyz              377ffae5-61c3-4aa0-926e-27856946dd8e  a87a7240-6004-4bae-9779-282bd7548bed  3ecb1fe3-92bd-4f69-b5ed-7e5f02eb0e97
/jobs/health         66c43088-1839-4a56-9212-0762ad3f4cc4  f2507600-ac4d-4d0c-aec8-1cc0058e688c  c0074736-2d17-4cd9-bd45-e7efc3fb3800
/me                  38baf447-38aa-47f3-b1bd-01d57295861f  2c6a2d90-119a-4c68-8df3-b98323c7b4b9  5facf2d1-3634-4b6e-a541-e464651660b9
/config/entitlements 2507a696-abf2-4ac3-8a41-06dd54eba3d2  239dd4f2-dced-4841-9793-8ed61e825d0d  59e9862d-816c-4ddf-93f1-b186fd82fbc4
/subscription/current eaf44057-7a92-481d-b9fd-a49ed7c754cc  57dc5df5-7952-4e87-8f13-8119f39ec8fb  b30eae18-7fc7-473b-a287-5a175b116f07
/resumes (307 hop)   ba613642-f43a-4d57-94fb-0d2fee783c66  b3602ccd-96cf-4f5f-8ef0-dbfe4443e92b  06aa3b17-17f2-415b-a88f-695899ce5b53
/resumes chain hop2  08c21c53-630c-4b37-8bbe-1c8691f7b1cb  957f9342-0995-4b6c-ae73-8e33a86197db  59e0b015-9dd6-4044-980e-632e4b7abcb0
/resumes direct      a9219a26-1d03-4a06-9ee5-a052bb4f00c6
/templates           f00bd7f5-357e-456f-9b99-6b8d40d799a0  774f7d35-dcb4-4970-a623-33bd0cffa2bf  812bfa19-5236-44ee-bc83-b6dedafe2105
/admin overview      37c2793a-abcf-429e-8620-662c001f37e2  0eb92ff1-254f-446f-9fa7-8271ff938f99  181e1b66-1d82-41b6-9f9c-7270e80947bb
```

### 1.1 The ~1.2 s floor: mostly transport, not application

Fresh `/readyz` was 952–987 ms: TCP connect ≈230–253 ms, TLS ≈490–508 ms, so TLS+TCP is ≈0.5 s; the remaining ≈0.45–0.49 s is request RTT plus handler work. Keep-alive on one TLS connection cut `/health` from 988–1389 ms fresh to **693–724 ms steady-state** (seq 2–4; seq 1 on the new connection was 988 ms). An independent `curl` check showed the same shape: 1193 ms fresh vs 682–692 ms reused. The 1.2 s figure is therefore a **fresh-connection** cost: ≈0.5 s handshake + ≈0.25 s RTT + handler/admission time. It is not a 1.2 s application floor.

The per-endpoint residual is not uniform:

- `/readyz`, `/me`: ≈0.25 s residual app + ≈0.24 s RTT.
- `/health`: ≈0.45–0.62 s residual (the `/health` handler is ~0.4 s slower than `/readyz` in this run; `/health` p50 rose +17% while `/readyz`/`/me` fell 15–16%).
- `/config/entitlements`: ≈0.9 s residual.
- `/jobs/health`: **≈2.6–2.8 s residual**; keep-alive steady-state was 3.02–3.88 s. The handler does a 1 s Celery `inspect().ping()` plus Redis health and a DB queue snapshot (`job_routes.py:2030-2088`). This is application cost, not edge.
- `/analytics/admin/overview`: cache hit ≈0.45 s residual; cache miss ≈2.7 s residual.

So P-01's blanket “edge latency” framing is only partly right: the 1.2 s floor is mostly the audit client's transport, but the 3.3 s `/jobs/health` and 1.7 s `/config/entitlements` contain substantial application time.

### 1.2 Warm/cold labeling is unsupported

The CSV has no warm/cold or region column. The lead's script says “warm”, but it opens a fresh TCP+TLS connection for every sample, so every sample is transport-cold; the app container is presumed warm (Modal min containers) but no cold-start marker or container-age evidence is recorded. There are **no cold samples**, although the spec asks for 10 where controllable. The first sample of my `/health` run paid a 1.49 s TLS handshake (total 3.12 s) with no app difference, which is exactly the kind of transport event that can masquerade as a cold start. The 60 s `/analytics` cache is also uncontrolled: hit/miss state changes the p50 by ~2.3 s.

### 1.3 Is 30 samples enough?

No for tails. With n=30, the 90% CI for p95 spans the 27th–30th order statistics; p99 is the maximum by construction (the lead's `round(0.99×29)` indexes the max) and has a 26% chance of being below the true p99 (`0.99^30 ≈ 0.74`). The CSV's p95/p99 are single order statistics, not stable percentiles. `/subscription/current` p95 3447 ms and `/resumes` p99 23,374 ms are each driven by one outlier and did not reproduce in three fresh samples. 30 sequential samples are adequate to screen the median (the five “core” endpoints moved only −175 to −219 ms, median −193 ms, consistent with a ~0.19 s faster transport floor today), but not to certify a p95 SLO or a p99. My n=3 re-run is deliberately only a sanity check of the median/floor; it cannot re-estimate the tails.

### 1.4 Two measurement artifacts in the baseline

- **`/resumes` is a redirect chain, not one call.** `GET /resumes` returns **307** with `Location: https://…/resumes/`; the lead's `urllib` follows it, so the recorded 200 and 2326 ms p50 are two request cycles. The raw 307 hop alone is 932–976 ms; the chain in this run was 2.98–9.21 s (median 4.22 s, high variance); the canonical `/resumes/` was **1508 ms**. The payload is now empty (54 B) because the pro fixtures were cleaned, so the baseline's 707.6 B mean is not comparable. The CSV's `status_codes=200` hides the 307 step. Either measure `/resumes/` or label the chain explicitly.
- **`/analytics/admin/overview` is cache-bimodal.** The 60 s cache produces ~1.2 s hits and ~3.5–3.8 s misses. The baseline p50 1405 ms is a hit; p95 3805 ms is a miss. Both modes reproduced (hit 1196.4 ms, misses 3454.1/3829.6 ms). A single p50/p95 without cache state is not a stable latency estimate. The response also reports `metrics_freshness: {fresh:false, reason:"no_rollup", rollup_rows:0, source:"base_tables"}`, confirming AN-05/CRON-01 on every sample.

## 2. Correctness re-run (fresh requests, status + request ID)

| Check | Observed | Request IDs |
|---|---|---|
| `GET /config/entitlements` anon / free / pro | **200 / 200 / 200**; `features` map has **165 keys, 165 true, 0 false** in all three; anon has only `features`; free/pro add `quotas` | `62a0165c-fc12-442e-9abc-1b8dd2667ea7` / `72bc165c-c7d4-4c85-9575-95c2965ed296` / `b38939e8-2168-4644-9bd9-092207fa0324` |
| `GET /byok/api-keys` as free | **200**, `success:true`, `api_keys:[]`, `total_count:0`; GET route has no `require_feature("byok")` dependency | `8e133a62-7f76-4cbd-976e-4342a77e7839` |
| `GET /developer/keys` pro / free | **200 / 200**; pro has 1 revoked key, free has 0; no plan 403 boundary | `cf4976a6-a065-4e96-bc9d-72a6a0a0c186` / `f868d8a1-4965-4570-b44e-2edc864b2856` |
| Cross-user resume: free-owned `d0e35c34…` as free / pro | **200 / 404** `“Resume not found”` (anti-enumeration) | `eafbac85-d47c-4b56-a3d4-6d60a20d5eb6` / `64f28ff5-f3f0-4eef-a6d8-2ceeeeee069d` |
| `GET /tenants/{A}/stats` owner / member / outsider / random / former B | **200 / 403 / 403 / 404 / 404**; owner A (`577149dd…`) sees member_count 2; admin-support is a non-member and gets 403; random and deleted `3f98ed40…` get 404 | `4b91fd7d-ca64-4bf0-aa9c-9d6c22f368a9` / `520894a4-27fe-47d5-97a5-e4d212532d5b` / `eba46eec-8b24-4671-9cba-8a13475b272a` / `9ab61328-3a79-4dee-b5c0-c3936e6a0234` / `4bf26655-3bef-48b2-81e5-b35a4abd0bec` |
| `GET /admin/analytics/overview` literal (task path) pro / admin | **404 / 404** (path does not exist) | `ed0589b7-7cd7-491a-b398-0994a9dd0ddd` / `c200611a-9a92-4d6a-bf76-229773dd5316` |
| `GET /analytics/admin/overview?days=30` (canonical) pro / admin | **403** `“Admin privileges required”` / **200** full overview (3.36 s, cache miss) | `a307d4f7-7913-4c3f-a846-747cb9bfae39` / `1c864fff-b016-4883-b4da-40f22ff2825c` |
| `POST /ws/ticket` anon / free | **401** `“Authentication required”` / **200** ticket, `expires_in:60` | `e68b4664-8a84-45db-9444-9d73aa6dc969` / `5f51bc9e-83a8-4bed-979d-7891a523fe82` |
| `GET /jobs/{id}/stream` owner pro / cross free | **200**, 75 events (`job_id 8cc6cf5f-a580-4ccd-b81a-5ac7d154f007`) / **403** `“Access denied”` | `00a59123-4bbd-4f32-aa5b-8723f0cc01d4` / `2723a60f-c77b-4844-aa08-3ceb258793d7` |
| `GET /account/gdpr/policy` / `requests` as free | **200** policy keys `deletion_confirmation, export_ttl_minutes(30), reauth_max_age_minutes(15), retention_exceptions, export_scope`; **200** `{items:[…3…], total:3}` with the documented request fields | `e04c58c0-6fad-49ef-bab3-2fcf556ae45c` / `8b411125-3f41-4639-8525-80d3acf48d5b` |
| `GET /zotero/connect` as free | **405** `“Method Not Allowed”` (backend route is POST-only) | `a8568985-928f-4177-80b9-a681c5fce6fd` |
| `GET /byok/models/openai` vs `/resumes/engine/providers` (byok) | **200** 5 legacy models (`gpt-4-turbo-preview…gpt-3.5-turbo-16k`) / **200** OpenAI list is 4 `gpt-4o*` models; no overlap; engine default `null/platform/ready:false` (no stored key now) | `c3d0defd-fd31-4fca-8cb0-f6b8cb0eca6b` / `d0bac929-ddd8-43ec-90f6-416e045eb7b8` |

`/tenants/my` as team-owner returned only tenant A (`9d7094cc-0a2b-4711-8f79-779195ad9f63`), which is why the exact “owner A vs tenant B” pair could not be reconstructed.

## 3. Defect falsification (5 selected rows)

| ID | Baseline claim | Result | Fresh evidence |
|---|---|---|---|
| **CAP-01** | Live export: 165/165 features true for every plan, including anonymous | **CONFIRMED** | 165 keys / 165 true for anon, free, pro; IDs above. Caveat: this is the 165-key feature map, not 149 gateable or 129 product IDs; an all-true map does not by itself prove each gate is enforced. |
| **CAP-02** | `/byok/api-keys` stays 200 when `d25` is denied for free | **CONFIRMED (structural)** | Free GET → 200, 0 keys; the GET route has no feature dependency. The specific `d25=false` state was not re-flipped (would be a global mutation), so the denial-state re-run is **UNVERIFIABLE read-only**; the code path makes the 200 independent of `d25`. |
| **PB-D05** | No rate-limit headers; `/developer/usage` 2.5–3.3 s | **CONFIRMED** | No `RateLimit-*`/`X-RateLimit-*`/`Retry-After` headers on `/developer/usage` or `/developer/keys`; usage 2262 ms vs keys 989 ms (~2.3×). The absolute range is network-dependent and slightly lower here (floor 0.98 s vs baseline 1.18 s); the ratio and missing headers hold. |
| **REF-01** | References tab calls GET `/zotero/connect`; backend is POST-only → 405 | **CONFIRMED** | GET → 405 (`a8568985…`). |
| **ST-D05** | Existing tenant → 403, nonexistent → 404 for a non-member (existence oracle) | **CONFIRMED (oracle) / UNVERIFIABLE (original owner-vs-tenant-B fixture)** | admin-support on live tenant A → 403 (`eba46eec…`); random UUID → 404 (`9ab61328…`). Tenant B/C no longer exist: `/tenants/my` has only A, and former `3f98ed40…` → 404 (`4bf26655…`). The oracle is real; the exact “owner A on tenant B” claim cannot be re-run. |

**Additional checks (not counted in the five):**

- **PB-D06 — CONFIRMED:** model catalogs disagree (5 legacy OpenAI models vs 4 `gpt-4o*` engine models). The engine’s “default gpt-4o-mini” state is not reproducible now because the stored BYOK key was deleted.
- **Q-01 — CONFIRMED:** `/jobs/health` body has six zero queue depths and **no `sampled_at` and no `worker_count`** (sample `66c43088…`), matching the claim.
- **Inventory row — DISAGREE:** `audit/inventory/http-disposition.csv` says `GET /analytics/admin/overview | pro-monthly | tested 200` (request `7698d74c…`). Fresh canonical request as pro is **403** (`a307d4f7…`); as admin it is 200 (`1c864fff…`). The row’s identity (or status) is wrong; the endpoint is admin-only.

## 4. Disagreements with the baseline

1. **The 1.2 s floor is not an application floor.** It is ≈0.5 s TLS/TCP + ≈0.25 s RTT + handler work; a warm keep-alive `/health` is ≈0.69–0.72 s. The blanket “edge latency” label is incomplete: `/jobs/health` is ≈2.6–2.8 s application, and `/config/entitlements` ≈0.9 s application.
2. **“Warm” is not evidenced.** The CSV has no warm/cold or region column, every sample is a fresh connection, and there are no cold samples. The 3.12 s `/health` sample with a 1.49 s TLS handshake shows how transport noise can look like a cold start.
3. **p95/p99 are not statistically usable at n=30.** p99 is the max by construction; p95 is one order statistic with a 90% CI spanning ranks 27–30. The `/subscription` p95 3.45 s and `/resumes` p99 23.4 s are single outliers and did not reproduce.
4. **`/resumes` p50 2326 ms is a redirect chain.** `GET /resumes` → 307 → `/resumes/`; the lead's client followed it. Raw 307 hop ≈0.97 s; canonical `/resumes/` 1.51 s; chain 2.98–9.21 s here (high variance). The CSV hides the 307 and the second request.
5. **`/analytics/admin/overview` p50 is cache-phase dependent.** Hit ≈1.2 s, miss ≈3.5–3.8 s; the recorded p50 is a hit and p95 a miss. Both modes are real; one p50/p95 without cache state is misleading.
6. **The disposition CSV’s pro→200 row for `/analytics/admin/overview` is wrong.** Live pro → 403, admin → 200. The task’s literal `/admin/analytics/overview` is 404; the live route is `/analytics/admin/overview`.
7. **`/developer/keys` has no pro-vs-free plan boundary.** Free → 200 with an empty list. Source says the free-tier developer API is intentional, with a per-plan daily limit; the pricing copy’s `apiAccess:false` is the inconsistency already captured by CAP-01. This is not a new auth defect, but the expected “plan boundary” was not observed.

## 5. Verdict

- **Central tendency: trustworthy within about ±0.2 s.** Seven of nine endpoints’ fresh medians are within 0.22 s of the recorded p50 (five moved −175 to −219 ms together, consistent with a faster transport window today); `/health` moved +0.20 s, `/templates` +0.06 s. The baseline is a reasonable coarse regression reference.
- **Tails and warm/cold claims: not trustworthy.** n=30, p99=max, no cold samples, uncontrolled cache state, and transport-dominated outliers. Do not use these p95/p99 values as an SLO sign-off or as proof of a cold-start problem.
- **Root-cause attribution: mixed.** The floor is mostly the audit client’s transport; `/jobs/health` and `/config/entitlements` have real application cost. The blanket “edge” label should be replaced by per-endpoint decomposition.
- **Correctness/security: the sampled defect claims hold.** CAP-01, CAP-02 (structural), PB-D05, REF-01, ST-D05 (oracle), PB-D06 and Q-01 reproduced. The main evidence defects are the mislabeled admin-overview row and the deleted tenant-B fixture, not the product behavior.
- **Overall:** the baseline numbers are directionally useful but are a **screening baseline**, not a signed-off SLO baseline. Re-run with ≥100 interleaved samples per endpoint, record connection reuse/cache state/region, add cold-start markers and server traces, and preserve or recreate the second tenant before signing the latency or tenant-isolation claims.

## 6. Residual gaps

- No cold-start samples; Modal cold-vs-warm and the 4.1 s `/health` max remain unverified.
- One vantage (India); no multi-region, HTTP/2/3, browser, or mobile measurement. RTT ≈0.25 s is not representative of users near the Modal region.
- Server processing is inferred by subtraction; no `Server-Timing` or trace spans, so “app” includes admission/queue/DB/Redis.
- n=3 cannot re-estimate p95/p99; the 30-sample baseline’s tails are not independently confirmed.
- No second live tenant: exact owner-A-vs-tenant-B isolation is unverifiable; the 403-vs-404 oracle is confirmed with a non-member outsider.
- BYOK routing (PB-D03) cannot be independently verified without a valid key and outbound-request logging; only the `error_kind:"unknown"` symptom is observable.
- `/resumes` data was cleaned between runs (707.6 B → 54 B), so its latency/payload is not fully comparable.
- The `/analytics/admin/overview` cache hit rate is uncontrolled; p50 depends on the sampling window.
