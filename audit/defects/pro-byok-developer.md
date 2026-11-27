# Defect records — Pro / Pro Annual / BYOK / Developer API

- **Audit window:** 2026-11-27T10:46:45Z – 2026-11-27T11:05:29Z
- **Environment:** production (`sanskarpandey2004--latexy-backend-fastapi-app.modal.run`, backend `ee1a405d…`)
- **Identities:** `audit+pro-monthly…`, `audit+pro-annual…`, `audit+byok-monthly…`, `audit+developer-api…` (suffix `20261127103328`)
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\audit_probe_results.json` (140 request/response captures with `X-Request-Id` and `Date` headers). Full keys are redacted from this file and remain only in the temp capture.
- **Status:** all records are open; no fixes were attempted.

| ID | Sev | Title | Cohort |
|---|---|---|---|
| PB-D03 | **P0** | BYOK OpenAI credentials are routed to the platform `OPENAI_BASE_URL`, not OpenAI | BYOK |
| PB-D01 | **P1** | LLM optimization fails with `llm_error` after retry on the platform key | Developer API, Pro, Pro Annual, BYOK-without-key |
| PB-D02 | **P2** | `POST /byok/api-keys` returns 500 when provider validation rejects the key | BYOK |
| PB-D04 | P3 | Developer key input validation: empty `scopes` grants all scopes; whitespace name stores empty | Developer API, Pro |
| PB-D05 | P3 | Developer API exposes no rate-limit headers; `/developer/usage` takes 2.5–3.3 s | Developer API |
| PB-D06 | P3 | BYOK model catalog disagrees with the resume-engine model catalog | BYOK, Pro |
| PB-H01 | P3 | Matrix-provisioned developer key can never authenticate (harness fixture) | Audit tooling |

---

## PB-D03 — P0 — BYOK OpenAI credentials are routed to the platform `OPENAI_BASE_URL`, not OpenAI

**Surface:** BYOK key validation and generation; every code path that builds an OpenAI client with the caller's BYOK key. At least: `POST /byok/validate`, `POST /byok/test/{provider}`, `POST /byok/generate`, `POST /ai/*` (platform/BYOK resolution), `llm_optimization`, `cover_letter_generation`, `interview_prep`, and `RESUME_ENGINE` OpenAI BYOK runs.

**Cohort / user:** `byok-monthly`, user `373bf051-a804-4ae5-a10e-46970964c508`. Any user who stores an OpenAI key is affected.

**Repro (observed):**

1. With an OpenAI key stored (or via `POST /byok/validate`), submit a plausible but invalid key such as `sk-proj-…`.
2. Observe `POST /byok/validate` → 200 `{valid:false, error:"The provider validation failed unexpectedly.", error_kind:"unknown"}`.
3. Observe `POST /byok/test/openai` → 200 `{success:false, validation_details:{valid:false, error_kind:"unknown"}}`.
4. Observe `GET /resumes/engine/providers` → `default.source:"platform"`, `ready:false` even though the platform LLM works (`POST /ai/rewrite` returned 200 at 10:51:51Z).

**Expected:** a BYOK OpenAI key is sent only to `https://api.openai.com/v1`. A 401 from OpenAI is classified as `rejected`; a valid key validates and generates.

**Actual:** the OpenAI SDK is constructed without `base_url`, so it inherits the deployment's `OPENAI_BASE_URL` (the platform's OpenAI-compatible provider, identified as Gemini in source comments). The user's `sk-…` key is sent there as a Bearer token. A 400/403 from that endpoint falls into the generic `except`, producing `error_kind:"unknown"` rather than `rejected`. A valid OpenAI key would be rejected or misrouted, so BYOK OpenAI is unusable.

**Evidence:**

| Time (UTC) | Request | Result | Request id |
|---|---|---|---|
| 10:58:42 | `POST /byok/validate` `sk-proj-…` | 200 `valid:false`, `error_kind:"unknown"` | `1bde83b3-9938-43be-b777-e6ae14b89d07` |
| 10:57:21 | `POST /byok/test/openai` stored invalid key | 200 `success:false`, `error_kind:"unknown"` | `2476b989-3a2d-404d-a47f-710a2e8b778f` |
| 10:47:06 | `GET /resumes/engine/providers` before key | `source:"platform"`, `ready:false` | `ad2c3577-3fd4-4cd4-85da-30b7df4049ba` |
| 10:57:24 | `GET /resumes/engine/providers` with key | `source:"byok"`, `ready:true`, model `gpt-4o-mini` | `af372c84-6cf1-4763-824e-0a329c77a83f` |
| 10:51:51 | control `POST /ai/rewrite` (no BYOK, platform key) | 200 rewritten text, 7.63 s | `e9487190-aa08-45f4-b3a4-21a94551cbb2` |
| 10:57:26 | `POST /ai/rewrite` with stored invalid BYOK key | 502, generic provider error | `0650fc0d-5ac7-4bc4-b695-94989466da75` |

Code at the deployed SHA:

- `backend/app/services/llm_provider_service.py:193-195` — `OpenAIProvider.__init__` calls `AsyncOpenAI(api_key=api_key)` with no `base_url`.
- `backend/app/workers/cover_letter_worker.py:228-234` — comment: the worker "only reached Gemini because the openai SDK falls back to reading OPENAI_BASE_URL from the process environment when the constructor arg is omitted".
- `backend/app/workers/llm_worker.py:247-255` — comment: "Gemini's OpenAI-compat models 'think' by default … confirmed live in production, a real call spent 4,146 tokens and produced zero visible output." This identifies the production platform endpoint as Gemini.
- `backend/app/workers/converter_worker.py:170-172` — forces `https://api.openai.com/v1` for BYOK "including when OPENAI_BASE_URL is also set in the process environment" (the leak is known and fixed in this worker only).
- `backend/app/services/resume_engine/provider.py:92-122` — when the platform base URL is set to a non-OpenAI host, the implicit provider becomes `openai_compatible`; without pricing the call raises `BudgetExceeded`, which is consistent with the observed `ready:false`. With a BYOK OpenAI key the spec has `base_url=None`, so `SemanticProvider._client` also lets the SDK inherit the env base URL.
- Other unpinned clients: `backend/app/api/ai_routes.py:496` and `:1833`, `backend/app/workers/llm_worker.py:245`, `backend/app/workers/orchestrator.py:925`, `backend/app/workers/interview_prep_worker.py:233`.

**Impact:**

- **Security/privacy:** a user's OpenAI API key is transmitted to the platform's configured third-party compatible endpoint (Gemini per the deployed source comments). That is a credential disclosure to a processor the user did not select for their own key.
- **Functional:** BYOK OpenAI validation fails with a misleading "unexpected" error; valid keys cannot be distinguished from invalid ones; OpenAI custom-model routing cannot work.
- **Scope:** every BYOK OpenAI path except `converter_worker` (which pins the origin). Anthropic uses an explicit httpx URL; OpenRouter has an explicit base URL, so they are less exposed.

**Confidence:** high. The live host string is not returned by any endpoint; confirm with the API function's environment (`OPENAI_BASE_URL`) and an outbound-request log. The code path, the `ready:false` metadata, the known env-fallback comment, and the `unknown` (non-401) classification all agree; no alternative explanation covers all four.

**Proposed fix:**

1. Centralize a BYOK client factory that always passes `base_url="https://api.openai.com/v1"` for provider `openai` (and explicit provider URLs for Anthropic/OpenRouter), regardless of `OPENAI_BASE_URL`.
2. Apply it to every path listed above, including `OpenAIProvider`, `ai_routes`, `llm_worker`, `orchestrator`, `interview_prep_worker`, and `SemanticProvider`.
3. Add a regression test that sets `OPENAI_BASE_URL=https://example.invalid` and asserts every BYOK OpenAI request targets `api.openai.com`.
4. Add a startup assertion/log that never prints the key: `provider=openai, base_url=api.openai.com` for BYOK, and `provider=openai_compatible, base_url=<platform>` for the platform key.
5. Re-test `POST /byok/validate` with an invalid `sk-` key: expected `error_kind:"rejected"` and HTTP 200 `valid:false` (plus the PB-D02 fix for `POST /byok/api-keys`).

**Owner:** AI platform / LLM integration. **Status:** open.

---

## PB-D01 — P1 — LLM optimization fails with `llm_error` after retry on the platform key

**Surface:** `POST /api/v1/optimize`, `POST /jobs/submit` (`job_type:"llm_optimization"`), worker stage `llm_optimization`.

**Cohorts / users:** `developer-api` `dc001b15-2133-4c18-a1a1-d0af1952835c`; `pro-monthly` `2c27be6f-138f-4e98-b311-38892520b1eb`. Any plan using the platform key (Pro, Pro Annual, BYOK without a usable key).

**Repro:**

1. `POST /api/v1/optimize` with a valid 1-page LaTeX resume, a short job description, `optimization_level:"conservative"`, and a full-scope developer key.
2. Poll `GET /api/v1/jobs/{id}` every 2 s.
3. Independently repeat with a first-party session: `POST /jobs/submit` `{job_type:"llm_optimization", …}` and `GET /jobs/{id}/state`.
4. Read `GET /jobs/{id}/stream` for the event-level error.

**Expected:** the job completes with `optimized_latex`/changes, or fails with a specific provider error and does not present a generic "Job failed".

**Actual:** both paths return a queued job, then `job.failed`:

```json
{"type":"job.failed","stage":"llm_optimization","error_code":"llm_error",
 "error_message":"The AI didn't return a usable result after retrying.",
 "retryable":true,"percent":0}
```

`GET /api/v1/jobs/{id}` returns `status:"failed"`, `error:"Job failed"`, `result:null`. `GET /jobs/{id}/result` also returns only `"Job failed"`. The run took ~15–25 s and the quota unit was refunded (`optimizations.used` remained 0 on the clean `developer-api` identity).

**Evidence:**

| Time (UTC) | Path | Job id | Event evidence | Request id |
|---|---|---|---|---|
| 10:50:36–10:51:01 | Developer API optimize | `a53dc32a-4a7f-4530-b669-548d774cde6b` | `job.started` 10:50:51.765; "Streaming LLM response" 10:50:52.035; "Retrying — first attempt produced no usable output" 10:50:55.555; `job.failed` 10:51:01.284 | submit `beda609e-cf99-42e5-9558-04918c75fb8c`; stream `4e94bd22-6c6f-4c74-8cd6-c3f648488bc1` |
| 10:53:58–10:54:13 | First-party `jobs/submit` optimize | `9f28dc4b-a174-4edd-8cd3-325f905d70be` | `job.started` 10:54:08.674; retry 10:54:10.766; `job.failed` 10:54:13.388 | submit `d60b5560-1876-43bc-b4da-f40453136c41`; stream `3db6aea0-ff40-4bc8-b7cc-83ad4df36de3` |

Controls: `POST /ai/rewrite` on the platform key succeeded in 7.63 s at 10:51:51 (`e9487190-…`), so provider credentials and the model are reachable. The failure is specific to the optimization worker/delimiter path, not an authentication outage. Source at the deployed SHA documents the Gemini "thinking-token"/missing-delimiter fragility and a one-retry policy: `backend/app/workers/llm_worker.py:247-257`.

**Impact:** optimization is a core paid feature. In this sample, 2/2 attempts failed across two independent identities and two entry points, both on the platform key; users on Pro, Pro Annual, and BYOK-without-a-usable-key are exposed to the same path. The failure is also undiagnosable from the API (generic `"Job failed"`), which increases support load. No charge occurs, so there is no billing-integrity issue in this sample.

**Proposed fix:**

1. Keep the raw provider finish reason and a bounded output prefix in the failure record/telemetry (never in the user response) so "no usable output" can be distinguished from an empty stream, a refusal, a timeout, and a delimiter miss.
2. For the platform base URL, disable provider "thinking" where supported and/or use the JSON-schema/stop-sequence path rather than a delimiter; increase `MAX_ATTEMPTS` only with a bounded deadline and cost cap.
3. Surface a typed error (`llm_output_invalid`, `llm_timeout`, `llm_refused`) plus `request_id`/`job_id` to the client instead of `"Job failed"`.
4. Add a production canary optimization on the platform key and alert when the retry/failure rate rises.

**Owner:** LLM worker / AI platform. **Status:** open.

---

## PB-D02 — P2 — `POST /byok/api-keys` returns 500 when provider validation rejects the key

**Surface:** `POST /byok/api-keys` with `validate_key:true` (default).

**Cohort / user:** `byok-monthly` `373bf051-a804-4ae5-a10e-46970964c508`.

**Repro:**

1. `POST /byok/api-keys` `{provider:"openai", api_key:"sk-…invalid…", validate_key:true}`.
2. Repeat with a well-formed `sk-proj-` fake key.
3. `GET /byok/api-keys` to confirm no row was stored.

**Expected:** the declared response model is `AddAPIKeyResponse{success, message, key_id?, provider?, validated?, error?, validation_details?}`. A rejection should return HTTP 200/400/422 with `success:false`, a user-safe `message`/`error`, and no stored key.

**Actual:** HTTP **500** `{"error":{"code":"http_error","message":"Internal server error"}}`. No row is created. The separate `POST /byok/validate` returns 200 `valid:false`, so the provider validation itself completed; only the persistence route's response construction fails.

**Evidence:**

| Time (UTC) | Input | Status | Request id |
|---|---|---|---|
| 10:57:15 | short `sk-audit-invalid-…` | 500 | `33537266-99d5-4f47-91dd-0c0a876fd9ec` |
| 10:58:44 | well-formed `sk-proj-…` (48 chars) | 500 | `077fa524-ea34-4fb7-b6b2-f8fd048ae682` |
| 10:57:16 | list after failure | 200, empty | `26262aeb-8562-4ee6-aed0-c4341667070c` |

Root cause (code): `APIKeyService.add_api_key` returns `{"success": False, "error": …, "validation_details": …}` without `message` (`backend/app/services/api_key_service.py:97-104`). `AddAPIKeyResponse.message` is required (`backend/app/api/byok_routes.py:38-45`), so `AddAPIKeyResponse(**result)` raises `ValidationError`; the route's broad `except Exception` maps that to 500 (`byok_routes.py:184-186`).

**Impact:** invalid-key UX is broken: the user sees "Internal server error" instead of "The provider rejected this API key." It is safe (no key stored), but it is a poor rejection path and likely causes repeated submissions. It may also mask any other failure in the same route.

**Proposed fix:** include a sanitized `message` in the failure dict (or make `message` optional in the model), and return 400/422 with `success:false` instead of raising through the generic 500 handler. Add a test for `validate_key:true` + provider rejection.

**Owner:** BYOK backend. **Status:** open.

---

## PB-D04 — P3 — Developer key input validation: empty `scopes` grants all scopes; whitespace name stores empty

**Surface:** `POST /developer/keys`.

**Cohort / user:** `developer-api` `dc001b15-2133-4c18-a1a1-d0af1952835c`.

**Repro A (scopes):**

1. `POST /developer/keys` `{name:"audit-empty-scopes", scopes:[]}`.
2. Observe 201 with `scopes:["compile","optimize","ats","export"]`.

**Repro B (name):**

1. `POST /developer/keys` `{name:"   ", scopes:["ats"]}`.
2. Observe 201 with `name:""`.

**Expected:** `scopes:[]` is rejected (422) or yields a zero-scope key, not all four. A whitespace-only name is rejected (422) because `min_length:1` is meant to require a visible name.

**Actual:** empty scopes are treated as "unset" by `scopes = list(dict.fromkeys(body.scopes or DEFAULT_SCOPES))` (`backend/app/api/developer_routes.py:132`), granting maximum scope. The name passes `min_length` before `.strip()`, so `name=""` is persisted (`developer_routes.py:141`). Both keys were revoked immediately.

**Evidence:**

| Time (UTC) | Case | Status | Key id | Request id |
|---|---|---|---|---|
| 11:04:04 | `scopes:[]` | 201, all four scopes | `d489d6c4-a286-4df7-8b9b-3d501d7e0d42` | `6147b38d-3f0d-45b5-bd88-d022003d9e80` |
| 11:04:05 | whitespace name | 201, `name:""` | `afc71455-54db-4735-93cc-f6500086cc63` | `3caf931d-ce3f-4e8e-a127-2968b65774dc` |

**Impact:** a UI that sends an empty scope array (e.g., a user deselects all scopes) silently creates a maximum-privilege key; blank key labels degrade the key list. The creator can already create full-scope keys, so this is not a privilege boundary, but it violates least-privilege intent.

**Proposed fix:** distinguish `None` from `[]` (`body.scopes if body.scopes is not None else DEFAULT_SCOPES`), reject an empty list, and validate `name.strip()` non-empty with a Pydantic validator.

**Owner:** Developer API backend. **Status:** open.

---

## PB-D05 — P3 — Developer API exposes no rate-limit headers; `/developer/usage` takes 2.5–3.3 s

**Surface:** all `/api/v1/*` and `/developer/*` responses; `GET /developer/usage`.

**Cohort / user:** `developer-api`; `pro-annual`; `byok-monthly`.

**Observed:**

- Across 140 captured responses, the only headers were `content-type`, `content-length`, `date`, `x-request-id`, `modal-function-call-id`, CORS/security headers. No `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `RateLimit-*`, or `Retry-After` on success or 403/429-class responses.
- `GET /developer/usage` took 2.48 s, 2.48 s, 2.49 s, 2.49 s, 2.53 s, 2.88 s, 3.08 s, 3.26 s (n=8) while `GET /developer/keys` took 1.14–1.20 s (n=8). `GET /developer/usage` calls `get_usage_history`, which loops 7 days and performs one Redis `GET` per day (`backend/app/services/developer_key_service.py:80-100`).
- The daily meters were correct: Pro/Pro Annual 1000, BYOK 500. The counter advanced 0→5 for `developer-api` across 5 authorized calls, and rejected-scope calls did not consume it.

**Expected:** clients can see the remaining daily budget and a retry hint before hitting 429; the usage endpoint returns in one round trip.

**Actual:** no budget headers, and the usage endpoint is ~2× the cost of a comparable list endpoint. The 429 path itself was not exercised (requires 1,000/500 authorized calls; no burst allowed), so `Retry-After` behavior on 429 is unverified.

**Impact:** SDK/CLI clients must guess when they will be throttled and cannot back off intelligently; the developer dashboard is noticeably slower. This is observability/performance, not a correctness failure.

**Proposed fix:** add `X-RateLimit-Limit/Remaining/Reset` to developer API responses and `Retry-After` to 429; replace the 7 sequential Redis `GET`s with `MGET`/pipeline and a single TTL lookup. Add a test that exhausts a low-limit test plan and asserts the 429 body/headers.

**Owner:** Developer API backend. **Status:** open.

---

## PB-D06 — P3 — BYOK model catalog disagrees with the resume-engine model catalog

**Surface:** `GET /byok/models/openai` versus `GET /resumes/engine/providers`.

**Cohort / user:** `byok-monthly` `373bf051-a804-4ae5-a10e-46970964c508`.

**Observed:**

- `GET /byok/models/openai` → `["gpt-4-turbo-preview","gpt-4-turbo","gpt-4","gpt-3.5-turbo","gpt-3.5-turbo-16k"]` (5 legacy models; request `20e26989-0d16-40a6-86ed-fb8d95e78a2d`).
- `GET /resumes/engine/providers` → OpenAI `["gpt-4o","gpt-4o-2024-08-06","gpt-4o-mini","gpt-4o-mini-2024-07-18"]` (request `af372c84-6cf1-4763-824e-0a329c77a83f`).
- The engine default resolved to `gpt-4o-mini`, which is not offered by `/byok/models/openai`.

**Expected:** both surfaces derive from the same operator-priced model catalog, or the static provider list is clearly marked legacy.

**Actual:** two different lists; the model a user can select in the BYOK provider UI is not the model the engine routes to, and current `gpt-4o*` models are hidden from `/byok/models/openai`. Anthropic and OpenRouter return empty model lists from the engine even though `configured_models` is the source.

**Impact:** custom-model users may pick a stale model, or not see the models the engine supports. This compounds the PB-D03 routing defect.

**Proposed fix:** export one catalog from `RESUME_ENGINE_MODEL_PRICING` (plus provider static defaults only where pricing is not required) and use it in both endpoints; add a contract test that the engine default model is present in the provider model list.

**Owner:** AI platform / BYOK backend. **Status:** open.

---

## PB-H01 — P3 — Matrix-provisioned developer key can never authenticate (harness fixture)

**Surface:** audit identity matrix / `developer_api_keys` provisioning; not a production user path.

**Observed:** the `developer-api` identity was provisioned with key `lxy_audit_20261127103328_…` (id `5066ad7f-d6b3-458c-8776-82416d276ffb`). `GET /developer/keys` lists it as `is_active:true`, but every use returns 401 `Valid developer API key required` (`483a5eb1-1d90-4a91-9bef-a9ceb84da1bc`, 10:47:59Z). `developer_key_service.verify_api_key` and `get_developer_api_key_optional` require the `lx_sk_` prefix (`backend/app/services/developer_key_service.py:41`, `backend/app/middleware/auth_middleware.py:208`).

**Impact:** the matrix key is unusable; this sub-agent minted a real `lx_sk_` key through `POST /developer/keys` for testing. A future auditor following the matrix alone would report a false 401. No production impact.

**Proposed fix:** provision the fixture as `lx_sk_<random>` and store `sha256(full_key)`, or add a matrix flag that the key must be minted through the API. Add a provisioning self-check that calls `GET /api/v1/jobs/{random}` and asserts 404 (not 401) for a provisioned key.

**Owner:** audit tooling (`audit/scripts/provision_identities.py`). **Status:** open.
