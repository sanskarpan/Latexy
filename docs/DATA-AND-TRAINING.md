# Data & Model Training — Our Commitment

_Last reviewed: 2026-08-24_

**Your resume content is never used to train models — ours or anyone else's — and it never has been.** This document states that position precisely, per provider, and points at the code that backs it up so the claim is verifiable rather than aspirational. It is the commitment referenced by issue #1409.

This is the one promise that makes BYOK and self-hosting meaningful. If it were ever untrue, the architecture's main selling point would go with it — so we treat it as something to verify, not assume.

## The short version

- We do **not** run any internal training, fine-tuning, or dataset-export pipeline over your resumes. None exists in the codebase.
- We send resume/JD text to an LLM **only** to do the work you asked for (optimize, score, convert, cover letter). We attach **no** parameter that opts your content into provider-side training or extended retention.
- With **BYOK** (bring-your-own-key), requests go out on **your** provider key, so data handling is governed by **your** account with that provider — not ours.
- We ship **no** resume content to analytics or telemetry. Our metrics are counts, latencies, and token totals — never document text.

## Per-provider position

| Provider | How we use it | Training on inputs |
|---|---|---|
| **OpenAI** | Platform default and BYOK. Native OpenAI SDK. | OpenAI does not train on API inputs by default. We send no `store` flag or org data-control override. |
| **Anthropic** | BYOK. Direct `/v1/messages` call. | Anthropic does not train on API inputs by default. We send only the message payload. |
| **Google Gemini** | Platform option, via the OpenAI-compatible endpoint. | We commit to using the **paid** Gemini API tier, whose content is not used for training. (The free / AI-Studio tier can be — we do not use it for user content.) |
| **OpenRouter** | BYOK only. OpenAI-compatible SDK. | Routed on the user's own OpenRouter account; data policy is the user's account setting. We never auto-register OpenRouter with a platform key. |

Any future change that would send user content into a training/opt-in path will be made **explicit and per-user opt-in**, defaulting off — never a silent platform default.

## What the code shows (evidence)

Audited 2026-08-24 (issue #1409). Paths are under `backend/`.

- **No training/retention parameters anywhere.** Every provider call sends only the fields needed to generate a response (`model`, `messages`, `temperature`, `max_tokens`, and similar). A repo-wide search for `store=`, `data_collection`, `zdr`/`zero-retention`, and `data_policy` in provider calls returns nothing.
  - OpenAI: `app/services/llm_provider_service.py` (client + `chat.completions.create`)
  - Anthropic: `app/services/llm_provider_service.py` (direct `httpx` POST to `api.anthropic.com/v1/messages`)
  - OpenRouter: `app/services/llm_provider_service.py` (`base_url=https://openrouter.ai/api/v1`)
  - Platform optimize/score/convert workers: `app/workers/llm_worker.py`, `app/workers/orchestrator.py`, `app/workers/ats_worker.py`, `app/workers/cover_letter_worker.py`, `app/services/llm_service.py`
- **BYOK really uses your key.** Keys are stored encrypted and decrypted only at call time (`app/services/api_key_service.py`); the request path prefers the caller's own key and, when present, never falls back to the platform key or another tenant's key (`app/api/ai_routes.py`, `app/services/llm_provider_service.py`).
- **No internal training pipeline.** There is no fine-tune job, dataset export, or `.jsonl` builder. The `resumes.content_embedding` column (`app/database/models.py`) is written by `app/services/embedding_service.py` and read **only** for runtime semantic search / résumé-to-JD ranking (cosine similarity) — retrieval and scoring, not training.
- **No content in telemetry.** `app/core/observability.py` records provider/model/status labels and numeric latencies/token counts only. `app/api/telemetry_routes.py` accepts web-vitals and named business events (no document text). No third-party analytics/telemetry SDK is integrated (Sentry, PostHog, Segment, Mixpanel, Datadog, etc. are all absent). This complements the session-recording guard (issue #1410) that keeps keystroke-capture SDKs off the editor surfaces.

## Re-verifying this

Re-run the audit whenever a provider call path changes:

```bash
# Should return nothing inside provider request construction:
grep -rniE "store=|data_collection|zero.?retention|\bzdr\b|data_policy" backend/app

# Should return nothing — no fine-tune job, dataset builder, or export exists:
grep -rniE "fine[_ -]?tune|create_fine|\.jsonl|export.*dataset" backend/app
```

Two facts live outside the code and must be kept true by policy, not just by grep: the Gemini account stays on the paid API tier, and any OpenRouter usage keeps its account data policy set to "do not collect/train." Both are stated as commitments above.
