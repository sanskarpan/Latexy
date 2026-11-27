# Cohort report — Pro monthly, Pro annual, BYOK monthly, Developer API

- **Audit window:** 2026-11-27T10:46:45Z – 2026-11-27T11:05:29Z
- **Environment:** production, `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
- **Backend commit:** `ee1a405de6058e814c3a6f5ffba5fe3630576421` (`/health`, 10:46:45Z)
- **Identity suffix:** `20261127103328`; users/keys from `audit/plans/identity-matrix.json`
- **Method:** direct HTTPS from the audit workstation, one request at a time (~1.05 s spacing, <20 req/min), no global configuration changes. Raw evidence: `C:\Users\Sansk\AppData\Local\Temp\opencode\audit_probe_results.json` (request/response captures with headers, timestamps, bodies). Full keys are redacted here; they remain in the temp capture only.

## Verdict

| Area | Result | One-line evidence |
|---|---|---|
| Pro monthly unlimited compile | **PASS** | compilations `limit:null`; job `abef97e3…` completed, 1 page / 49,641 B PDF |
| Pro annual parity | **PASS** | `planId:pro_annual`, `limit:null`, `apiDailyLimit:1000`; job `495f65f0…` completed |
| BYOK unlimited platform quotas | **PASS** | compilations `limit:null`; job `d1197a00…` completed |
| Developer API key create/list/rename/revoke | **PASS** | 201 → 200 → 200 → 204; revoked key 401; 6th active key 400 |
| Developer API compile / ATS / job / PDF | **PASS** | ATS 200; compile queued→completed; PDF 200 `%PDF-`, 49,641 B |
| Developer API optimize | **FAIL** | `job.failed` `llm_error` after retry, 2/2 attempts (PB-D01) |
| Key scoping | **PASS** | missing `compile`/`optimize`/`export` scope → 403; `ats` works |
| Cross-user job/PDF isolation | **PASS** | second user's key → 404 for another user's job and PDF |
| Rate limits | **PARTIAL** | limits + meter increments verified; 429 ceiling not reached (1000/day) |
| BYOK key create/list/delete | **PASS** | add(unvalidated) 200, list masked, delete 200, list empty |
| BYOK invalid-key rejection | **FAIL** | `POST /byok/api-keys` `validate_key:true` → **500** (PB-D02) |
| BYOK no silent platform fallback | **PASS** | stored invalid key → `/ai/rewrite` 502; absent provider → 400; no platform spend |
| BYOK OpenAI credential routing | **FAIL (P0)** | BYOK OpenAI validation uses the platform `OPENAI_BASE_URL` (non-OpenAI host), so the user's key is sent to the platform proxy (PB-D03) |
| Custom model routing | **PARTIAL / BLOCKED** | provider metadata observed; end-to-end routing affected by PB-D03 and blocked by PB-D01 |
| Quota refund on failed job | **PASS** | `optimizations.used` stayed `0` after the failed optimize |

## 1. Baseline (observed, not pricing copy)

All four cohorts had `status: active`, role `user`, and `/me` returned the expected plan.

| Cohort | `planId` | Compilations | Optimizations | AI assists | `apiAccess` | `apiDailyLimit` | Other |
|---|---|---|---|---|---|---|---|
| pro-monthly | `pro` | `null` (unlimited) | `null` | `null` | true | 1000 | history 365 d, priority support |
| pro-annual | `pro_annual` | `null` | `null` | `null` | true | 1000 | same as monthly |
| byok-monthly | `byok` | `null` | `null` | `null` | true | 500 | `customModels:true` |
| developer-api | `pro` | `null` | `null` | `null` | true | 1000 | same as Pro |

Evidence: `GET /config/entitlements` and `GET /subscription/current` for each identity, 10:46:51Z–10:47:18Z, e.g. request ids `54458490-a706-4fee-911c-d267c52146fd`, `1ec9210c-5c42-4d1d-8ed6-9e4b9cef0087`, `2caaf4b7-cd7b-4e33-a26a-dd85a2ad1e32`, `8bdf36ed-d37d-4c6b-a38d-53cc66a3f5a0`.

`GET /resumes/engine/providers` before any BYOK key: `default.source="platform"`, `ready:false`, OpenAI models `gpt-4o / gpt-4o-2024-08-06 / gpt-4o-mini / gpt-4o-mini-2024-07-18`; Anthropic/OpenRouter model lists empty. See §7 and §8 for why `ready:false` matters.

## 2. Unlimited paths

| Test | Cohort | Observed | Evidence |
|---|---|---|---|
| First-party compile, 1-page PDF | pro-monthly | 200 submit; completed; internal `compilation_time` 6.560 s; 49,641 B | `97bc321e-ed40-45a8-af08-f36efef33a38`; job `abef97e3-d9ed-4b13-a66d-3653e6e95250` |
| First-party compile | pro-annual | 200 submit; completed; 6.558 s; 49,641 B | `5c263508-1954-46fe-806e-f3a3fbc149ea`; job `495f65f0-a231-4fc9-b22a-65f689762df4` |
| First-party compile | byok-monthly | 200 submit; completed; 6.561 s; 49,641 B | `f7f7d824-0a99-4463-b4e2-7c3b63be5790`; job `d1197a00-0e42-4f69-848a-d3b635fab28b` |
| Developer API compile | developer-api | 200 `{job_id,status:"queued",estimated_seconds:20}`; completed; 6.547 s | `0c931daa-d73c-4049-b1a9-3dfaf5b71bb8`; job `bf439cb9-7a29-427f-83b8-14d7643276d8` |
| AI assist on platform key | pro-monthly | 200, returned rewritten text in 7.63 s | `e9487190-aa08-45f4-b3a4-21a94551cbb2` |
| Optimize (first-party and API) | pro-monthly, developer-api | **FAIL** — see PB-D01 | jobs `9f28dc4b…`, `a53dc32a…` |

Wall-clock compile time (submit → final poll) was 16–20 s: submit request 5.28–5.58 s, internal pdflatex 6.55–6.56 s, remainder queue wait and 2 s polling granularity. This is a coarse observation; stage instrumentation belongs to the performance auditor.

`optimizations.used` was `0` for both identities after the failed optimize, and `compilations.used` for the clean cohorts (`pro-annual`, `byok-monthly`, `developer-api`) was exactly `1` after one compile. That confirms quota refund on failure and metering of successful work.

## 3. Developer API key lifecycle

All calls used `developer-api` session token unless noted.

| Step | Request | Result | Evidence |
|---|---|---|---|
| Provisioned matrix key used as API key | `GET /api/v1/jobs/…` | **401** `Valid developer API key required` | `483a5eb1-1d90-4a91-9bef-a9ceb84da1bc` (see Harness finding) |
| Bogus `lx_sk_…` key | same | 401 | `d43adff8-f6de-40a6-8fea-c61d60faada3` |
| Missing key | same | 401 | `916ec4b5-361a-4d54-b91f-febf8120ba02` |
| Create full-scope key | `POST /developer/keys` | 201, `full_key` returned once; scopes `[compile,optimize,ats,export]` | `3485ae6d-d3f3-4b96-b27f-006e2309c4f1` |
| List | `GET /developer/keys` | 200, two records, no `full_key` field | `b7a8904e-23bf-40ce-9815-f03334cb838e` |
| Rename | `PATCH /developer/keys/{id}` | 200, name changed | `40a0376c-9ad6-4f05-95a8-01cd2e952a4c` |
| 5-active-key cap | `POST /developer/keys` ×5 then ×1 | 5×201, 6th **400** `Maximum of 5 active developer API keys reached` | `2209f7a5-b42a-47ea-a4b7-4e0761ff2674` |
| Revoke | `DELETE /developer/keys/{id}` | 204 | `c254b3c4-873a-4bce-af4d-3956e6975830` (6.5 s cold), later 1.17–1.24 s |
| Revoked key reuse | `GET /api/v1/jobs/…` | 401 | `2af48579-515c-4437-b578-fee3a10ea9ce` |
| Unknown key id | `DELETE /developer/keys/000…` | 404 | `ada5ec9a-4d69-432a-a3ab-9b6673387e0a` |

`GET /developer/keys` includes inactive records (`is_active:false`) as well as active ones; the cap only counts active keys. This is a UI/response-shape choice, not counted as a defect.

### Key scoping

| Key scopes | Operation | Result |
|---|---|---|
| `[ats]` | `POST /api/v1/ats/score` | 200, score 80.8 (`5503e029-d490-4a06-9049-11b5fafd3b1b`) |
| `[ats]` | `POST /api/v1/compile` | **403** `API key lacks 'compile' scope` (`76d515c8-e721-481b-9db5-43a721aa06d5`) |
| `[ats]` | `GET /api/v1/jobs/{id}/pdf` | **403** `API key lacks 'export' scope` (`ac743505-ec04-4bb5-aee3-664cb3f979f9`) |
| `[compile,ats,export]` | `POST /api/v1/optimize` | **403** `API key lacks 'optimize' scope` (`59c07e77-bed9-4fbf-99d8-b28e769c2346`) |
| full | job status/PDF of own job | 200 / 200 |

Job status reads are intentionally not scope-gated; only submit/export operations are. Confirmed by the `[ats]` key reading its owner's completed job (`032312eb-7d5f-4e5a-92c4-12e356975a7d`).

### Cross-user isolation

A full-scope key created on `pro-monthly` was used against the `developer-api` user's job:

- `GET /api/v1/jobs/bf439cb9…` → **404** (`59fbe8af-fff7-4e4d-9032-5e839fc56d0c`)
- `GET /api/v1/jobs/bf439cb9…/pdf` → **404** (`eedf7225-45d9-4a99-8f08-9ffd6b541480`)
- A pro-monthly session token against the same job/results/stream → **403 Access denied** (`212d5165…`, `1fe16d2a…`, `e09fe935…`)

## 4. Developer API operations with the key

| Operation | Status | Response shape | Latency |
|---|---|---|---|
| `POST /api/v1/ats/score` | 200 | score 72.5 with JD; 80.8 without; category scores + recommendations/warnings/strengths | 1.64–2.85 s (n=5) |
| `POST /api/v1/compile` | 200 | `{job_id,status:"queued",poll_url,estimated_seconds:20}` | 5.58 s submit |
| `GET /api/v1/jobs/{id}` | 200 | `processing` → `completed`, `result.artifact`, `pdf_url` | 1.81–7.14 s per poll (first poll cold) |
| `GET /api/v1/jobs/{id}/pdf` | 200 | `application/pdf`, `%PDF-`, 49,641 B | **18.42 s cold**, 2.20 s warm |
| `POST /api/v1/optimize` | 200 queued then **failed** | `job.failed` `llm_error` | 4.35 s submit; failed ~25 s after submit |

The PDF endpoint's cold/warm gap (18.4 s vs 2.2 s, n=1 each) is flagged for the performance auditor; it is not counted as a defect here because the sample is too small to establish a p95.

## 5. Rate limits and usage metering

- `GET /developer/usage` reported `plan_id:pro`, `daily_limit:1000`; `pro_annual` also 1000; `byok` 500.
- Meter advanced from 0 to 5 on `developer-api` after 4 authorized calls with the full key plus 1 with the ATS-only key. Rejected-scope calls did not consume the meter.
- No `X-RateLimit-*`, `RateLimit-*` or `Retry-After` headers were present on any response (set of observed headers checked across 140 requests).
- The 429 path was **not exercised**: reaching it requires 1,000 authorized calls on Pro or 500 on BYOK, and the audit rules forbid a burst of that size. Treat 429 handling as unverified, not passing.
- `GET /developer/usage` took 2.48–3.26 s (n=8) versus `GET /developer/keys` 1.14–1.20 s (n=8); the handler performs 7 sequential Redis `GET`s, one per day, in `get_usage_history`. See PB-D05.

## 6. BYOK lifecycle

| Step | Result | Evidence |
|---|---|---|
| `GET /byok/api-keys` before | 200, empty | `936274e9-6843-4834-8591-8bbe6c1cc5ce` |
| `POST /byok/api-keys` rejected key, `validate_key:true` | **500 Internal server error**, no row created | `33537266-99d5-4f47-91dd-0c0a876fd9ec`; well-formed repeat `077fa524-ea34-4fb7-b6b2-f8fd048ae682` |
| `POST /byok/validate` same key | 200 `{valid:false, error_kind:"unknown"}` (no write) | `1bde83b3-9938-43be-b777-e6ae14b89d07` |
| `POST /byok/api-keys` `validate_key:false` | 200 `success:true`, `key_id:d24beec6…`, `validated:false` | `58f451ce-c2e8-43ad-a96e-35ffaf10b683` |
| `GET /byok/api-keys` after | 200, one key, `masked_key:"sk-...****"`, no ciphertext/full key | `44e4c854-00e5-416f-bdcd-1d906dff3691` |
| `POST /byok/test/openai` | 200 `{success:false, error_kind:"unknown"}` | `2476b989-3a2d-404d-a47f-710a2e8b778f` |
| `DELETE /byok/api-keys/{id}` | 200 `success:true` | `630e7c12-e297-4180-9867-9a4d0ceae682` |
| List after delete | 200, empty | `1ac23dbc…` sequence |
| Provider metadata after delete | `default.source:"platform"`, `ready:false` | 10:57:53Z |

The invalid provider key stored with `validate_key:false` is a deliberate audit fixture; it was deleted at 10:57:52Z. No valid third-party provider key was available, so a *successful* BYOK completion is untested.

## 7. BYOK rejection / platform-key fallback

| Case | Observed | Verdict |
|---|---|---|
| Stored BYOK OpenAI key, provider rejects it; call `/ai/rewrite` | **502** `AI provider could not complete the rewrite. Please retry.` (`0650fc0d-5ac7-4bc4-b695-94989466da75`) | PASS — no fallback |
| Control: same endpoint on `pro-monthly` with no BYOK key | **200**, rewritten in 7.63 s (`e9487190-…`) | PASS — platform key is healthy |
| `POST /byok/generate` with stored invalid key | 200 `success:false`, `content:null`, no cost/usage | PASS — no fallback |
| `POST /byok/generate` provider `anthropic` with no stored key | **400** `Provider request was invalid.` (`d3c97528-…`) | PASS — no cross-provider fallback |
| `/resumes/engine/providers` with key stored | `default:{provider:"openai", model:"gpt-4o-mini", source:"byok", ready:true}` | PASS — metadata reflects the stored key |

The 502 is the correct fail-closed behavior: no platform-key fallback occurred. It is not evidence that the stored key reached OpenAI — the request was routed to the platform base URL (PB-D03). The response also does not tell the user their stored key was rejected; that diagnosability gap is folded into PB-D01/PB-D03.

### BYOK OpenAI credential routing — P0

Production is configured to use a non-OpenAI, OpenAI-compatible endpoint for the platform key (Gemini per the deployed source comments), and the API process shares that configuration. Evidence:

1. `GET /resumes/engine/providers` returns `default:{provider:null, model:null, source:"platform", ready:false}` for every non-BYOK identity. That is consistent with the implicit provider resolving to `openai_compatible` (non-`api.openai.com` host) with no registered price; it would also require the platform model to be unpriced, which the Gemini-specific source comments below make the more likely explanation. Compare `backend/app/services/resume_engine/provider.py:92-122`.
2. Source at the deployed SHA documents that the OpenAI SDK reads `OPENAI_BASE_URL` from the process environment when `base_url` is omitted: `backend/app/workers/cover_letter_worker.py:228-234` says the worker "only reached Gemini because the openai SDK falls back to reading OPENAI_BASE_URL from the process environment when the constructor arg is omitted". `backend/app/workers/llm_worker.py:247-255` confirms Gemini is the live production platform provider ("confirmed live in production").
3. The BYOK provider class omits `base_url`: `AsyncOpenAI(api_key=api_key)` in `backend/app/services/llm_provider_service.py:193-195`. The same omission exists in `ai_routes` (`openai.AsyncOpenAI(api_key=resolved.key)`), `llm_worker.py:245`, `orchestrator.py:925`, `interview_prep_worker.py:233`, and `resume_engine/provider.py` (`SemanticProvider._client`), so BYOK OpenAI keys are sent to that host from those paths.
4. `backend/app/workers/converter_worker.py:170-172` explicitly forces `https://api.openai.com/v1` for BYOK "including when OPENAI_BASE_URL is also set in the process environment" — the team fixed this leak in one worker only.
5. The observed rejection taxonomy matches the misroute: native OpenAI returns 401 → SDK `AuthenticationError` → `error_kind:"rejected"` (`llm_provider_service.py:258-265`). We observed `error_kind:"unknown"` for two invalid-but-plausible `sk-` keys (`33537266…` short key; `1bde83b3…` `sk-proj-` key). A 400 from a non-OpenAI compatible endpoint lands in the generic `except` at lines 288-291.

Impact: a user's OpenAI BYOK key is transmitted as a Bearer credential to the platform's compatible provider (Gemini per the source comments), which is a credential disclosure to a different processor and makes BYOK OpenAI validation/generation unusable. This is P0 pending server-side confirmation of the configured host; the code path and production response shape are consistent and no other explanation fits both observations. See PB-D03.

**Residual risk (unverified):** `APIKeyService.get_user_provider` returns `None` if decrypting a stored key raises (`backend/app/services/api_key_service.py:309-313`). Callers treat `None` as "no BYOK key" and would then use the platform key. That would be a silent platform-key fallback after an encryption-key rotation or corrupt row. It was not reproduced because it requires corrupting a stored ciphertext; flag for the capability/security pass.

## 8. Custom model routing

- `GET /resumes/engine/providers` exposes per-provider model lists from `RESUME_ENGINE_MODEL_PRICING`; OpenAI had four `gpt-4o*` models, Anthropic/OpenRouter empty.
- With an OpenAI BYOK key present, the default resolved to `openai/gpt-4o-mini` and `ready:true`; after deletion it reverted to `platform/ready:false`. This metadata is misleading: the OpenAI BYOK path does not pin `https://api.openai.com/v1`, so the SDK inherits the platform base URL (PB-D03). A valid OpenAI key would be sent to the platform proxy, not to OpenAI.
- `POST /byok/generate` accepted `provider:"openai", model:"gpt-4o-mini"` and attempted the call (failed at provider auth, as expected for the invalid fixture). No fallback was observed, but the target host is the platform proxy (PB-D03).
- `POST /resumes/{id}/engine/optimize` is enabled: a non-existent resume returned 404 `Resume not found`, not 503 `Semantic optimization is disabled` (`99b18589…`, `f4c2f427…`).
- **Not proven:** end-to-end semantic/custom-model optimization. It needs a managed-source resume fixture, and any LLM completion currently hits PB-D01. Marked **BLOCKED**, not passing. OpenAI provider selection is additionally affected by PB-D03.

`GET /byok/models/openai` returns a different, legacy model list than the engine pricing catalog:
`gpt-4-turbo-preview, gpt-4-turbo, gpt-4, gpt-3.5-turbo, gpt-3.5-turbo-16k` (request `20e26989-0d16-40a6-86ed-fb8d95e78a2d`). See PB-D06.

## 9. Latency samples (single-region, not a load test)

| Endpoint class | n | min / median / max |
|---|---|---|
| `/health`, `/readyz` | 2 | 1.18 / 1.22 / 1.25 s |
| `/jobs/health` | 1 | 3.57 s |
| `/me` | 4 | 1.17 / 1.19 / 1.22 s |
| `/config/entitlements` | 8 | 1.84 / 1.87 / 1.91 s |
| `/subscription/current` | 4 | 1.27 / 1.29 / 1.31 s |
| Developer key create | 11 | 1.28 / 1.38 / 2.73 s |
| Developer key list | 8 | 1.15 / 1.17 / 1.20 s |
| Developer key revoke | 6 | 1.17 / 1.22 / 6.52 s (one cold outlier) |
| `/developer/usage` | 8 | 2.48 / 2.51 / 3.26 s |
| ATS score | 5 | 1.64 / 1.90 / 2.85 s |
| Compile submit | 4 | 5.28 / 5.43 / 5.58 s |
| Job poll (all types) | 28 | 1.58 / 1.84 / 7.14 s |
| Job result | 4 | 1.38 / 1.41 / 1.48 s |
| PDF download | 2 | 2.20 s warm / 18.42 s cold |
| Optimize submit | 2 | 3.80 / 4.08 / 4.35 s |
| BYOK create / delete | 1 / 1 | 1.59 s / 1.44 s |

## 10. Artifacts and cleanup

**Developer API keys** (all created by this audit; revoked unless noted):

| Cohort | Key id | Name | Final state |
|---|---|---|---|
| developer-api | `40711cd7-e98f-467b-92dd-852794a6be83` | `audit-dev-full-renamed` | revoked |
| developer-api | `dc948909-1f90-45b2-b1bd-89498707aca1` | `audit-dev-ats-only-20261127` | revoked |
| developer-api | `992a6c4e-abcd-453b-abb7-c19e1c6d5b28` | `audit-dev-filler-0` | revoked |
| developer-api | `73bb3af3-7ba8-4d58-bbbb-f0f5d3a4d48d` | `audit-dev-filler-1` | revoked |
| developer-api | `1ac23dbc-bb56-441e-a9a9-955e0461da3d` | `audit-dev-filler-2` | revoked |
| developer-api | `f2278924-cd85-40fc-9e88-285f06772476` | `audit-no-optimize-20261127` | revoked |
| developer-api | `d489d6c4-a286-4df7-8b9b-3d501d7e0d42` | `audit-empty-scopes-20261127` | revoked |
| developer-api | `afc71455-54db-4735-93cc-f6500086cc63` | `""` (whitespace name) | revoked |
| pro-monthly | `9a00e167-deed-44fd-8823-c96acfcd699a` | `audit-pro-monthly-key-20261127` | revoked |
| pro-annual | `631998d1-75a7-40a0-b8df-15233513a93b` | `audit-pro-annual-key-20261127` | revoked |
| byok-monthly | `e871ebb0-97dd-42f0-b8a7-b5ad5ac1a8b8` | `audit-byok-monthly-key-20261127` | revoked |
| developer-api | `5066ad7f-d6b3-458c-8776-82416d276ffb` | `Audit key` (matrix fixture) | **active but unusable** — see Harness finding |

**BYOK key:** `d24beec6-6829-4ad1-86f1-4c1b5857ed8a` (`audit-invalid-stored`, OpenAI, unvalidated) — deleted 10:57:52Z.

**Jobs / artifacts** (kept as evidence; no resumes were created):

| Cohort | Job id | Type | Final state |
|---|---|---|---|
| developer-api | `bf439cb9-7a29-427f-83b8-14d7643276d8` | latex_compilation | completed, 49,641 B PDF |
| developer-api | `a53dc32a-4a7f-4530-b669-548d774cde6b` | llm_optimization | failed (`llm_error`) |
| pro-monthly | `abef97e3-d9ed-4b13-a66d-3653e6e95250` | latex_compilation | completed |
| pro-monthly | `9f28dc4b-a174-4edd-8cd3-325f905d70be` | llm_optimization | failed (`llm_error`) |
| pro-annual | `495f65f0-a231-4fc9-b22a-65f689762df4` | latex_compilation | completed |
| byok-monthly | `d1197a00-0e42-4f69-848a-d3b635fab28b` | latex_compilation | completed |

No global config, plan catalog, capability grant, or feature flag was changed. `changes/production-changes.md` was not modified.

## 11. Caveats and gaps

1. **Concurrent traffic on `pro-monthly`.** It already had `compilations.used=1` at 10:46 (baseline was 0 at 10:33) and reached `used=5` by 11:01 with several jobs not created by this agent, plus an extra `ai_assists` unit. Quota deltas on that identity are contaminated by another audit process; the clean unlimited evidence is `pro-annual` and `byok-monthly` (each 0 → 1). The analytics auditor should exclude the whole audit window.
2. **All 165 entitlement flags are `true` for every cohort**, including Free. This is consistent with an all-enabled (Pass A) snapshot; either way, plan-family gating cannot be assessed from this state. The developer key `require_feature("developer_api")` gate and BYOK `require_feature("byok")` gate therefore returned allowed for all identities and are **not** evidence that a Free/Basic user is gated.
3. **429 not exercised.** The Pro daily ceiling is 1,000 and BYOK 500; no burst was run. Meter increments and reported limits were verified.
4. **No valid third-party BYOK key.** A successful BYOK completion and a successful custom-model run could not be tested. Only rejection/no-fallback behavior and metadata were exercised. PB-D03 means a valid OpenAI key would likely be sent to the wrong endpoint anyway.
5. **Optimization is the blocking failure.** Any semantic/custom-model end-to-end test that needs an LLM optimization is blocked by PB-D01 until it is fixed.
6. **PDF cold path sample is n=1.** 18.42 s cold vs 2.20 s warm needs a proper cold/warm series from the performance auditor.
7. **Matrix fixture key is not a valid `lx_sk_` key.** The provisioned developer key cannot authenticate; a real key was minted through the product endpoint for testing. This is an audit-harness issue, not a production user path.
8. **TUI, CLI, GitHub Action, and MCP were not exercised.** They were outside this sub-agent's brief; only the HTTP developer API and BYOK surfaces were tested.

## 12. Related defect records

`audit/defects/pro-byok-developer.md`: PB-D01 (P1 optimization failure), PB-D02 (P2 BYOK add 500), PB-D03 (P0 BYOK OpenAI credential routing to the platform base URL), PB-D04 (P3 key input validation), PB-D05 (P3 rate-limit observability/usage latency), PB-D06 (P3 model catalog mismatch), PB-H01 (P3 harness fixture key).
