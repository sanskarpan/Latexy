# PRD: External Sources → Resume ("Import your real projects")

- **Status:** Shipped baseline; follow-up product decisions remain
- **Date:** 2026-08-02
- **Reconciled:** 2026-08-28 against current `main`
- **Owner:** TBD
- **Tier:** Premium / AI-personalization (optional, opt-in)
- **Related:** [Input-Driven Optimization PRD](2026-08-02-input-driven-optimization.md)

---

## Implementation reconciliation (2026-08-28)

All three compliant import paths described by this PRD are implemented in
source and share the editable `ProjectEvidence` review UI:

- GitHub: authenticated, owner-bound asynchronous import at
  `POST /github/import-projects` and `GET /github/import-projects/{job_id}`;
  credentials are resolved inside the worker and results expire from Redis.
- Public URL: authenticated `POST /sources/import-url`, with SSRF, redirect,
  response-size/content-type, quota, and distributed external-budget guards.
- LinkedIn/user resume: authenticated multipart
  `POST /sources/import-linkedin`; it parses only user-uploaded exports or
  resume files and never contacts LinkedIn.
- `ImportProjectsModal.tsx` lets users select and edit projects/bullets before
  insertion. Anonymous `/try` keeps local `.tex` import available but sends
  server-backed source imports through a clear login flow.

The implementation deliberately differs from the original data-model sketch:
there are no durable `external_source_connections` or `ingested_projects`
tables. Existing encrypted user integration fields are reused, and GitHub
candidates use owner-bound Redis envelopes with a short TTL. Accepted text is
ordinary user-authored resume content. Treat the remaining sections as design
rationale unless a statement is explicitly marked shipped.

## 1. Summary

Let users optionally pull their **real projects and experience** from external sources so the AI grounds resume content in verifiable work instead of generic phrasing. Sources, in priority order:

1. **GitHub** — read the user's public repos, rank their top projects, and draft resume-ready bullets from README/description/stack. **Build first.**
2. **Portfolio / arbitrary project URLs** — fetch and extract content from a personal site or project link. **Build second (reuses the existing scraper).**
3. **LinkedIn** — via the user's **own data export** upload or resume-PDF upload only. **Never scrape LinkedIn.** **Build third.**

Everything is optional, opt-in per source, gated to the premium AI tier, and **always routed through a user review/edit step** before anything is written to the resume.

## 2. Problem & motivation

Today the AI optimizer rewrites the *existing* resume text; it has no access to the user's real body of work. Users must hand-type every project. This is friction, and it caps quality — the model can only polish what's already there. Founder's framing: for users doing AI personalization, let them **bring real evidence** (GitHub, portfolio, LinkedIn export, or pasted project links) and have the AI weave it into the LaTeX resume.

**Strategic wedge:** Latexy is a *LaTeX* resume builder — its audience skews technical/developer. GitHub import is **high-value and rare** in the market (only developer-niche tools like the JSON Resume ecosystem do it). This is a genuine differentiator, not a me-too feature.

## 3. Goals / Non-goals

**Goals**
- Reduce time-to-a-real-resume by importing verifiable projects with one connect/upload.
- Improve AI output quality by grounding bullets in cited evidence (less hallucination).
- Do it legally and privately (explicit consent, encrypted tokens, delete/disconnect, no ToS violations).
- Reuse existing infrastructure (GitHub OAuth, SSRF-guarded scraper, encryption, entitlements) — minimize net-new surface.

**Non-goals**
- No automated LinkedIn scraping or third-party LinkedIn data vendors (see §7).
- No auto-writing to the resume — imports produce *suggestions* the user reviews.
- No headless-browser rendering in v1 (static fetch only for URLs).
- Not building a general "web research" agent — scoped to project/experience evidence.

## 4. Current state (from codebase audit — reuse map)

| Capability | Status | Location |
|---|---|---|
| GitHub OAuth (connect/callback/status/disconnect), Fernet-encrypted token on `User` | **SHIPPED** — purpose-scoped authorization: public import requests no OAuth scope; private `.tex` sync explicitly requests `repo`. Granted capabilities are recorded, and disconnect revokes the GitHub app grant before local deletion. | `backend/app/api/github_routes.py`, `github_sync_service.py`, `User.github_access_token/username` (`models.py:48-49`) |
| Authenticated GitHub httpx client + token decryption | **EXISTS** (reuse) | `github_sync_service.py` |
| SSRF-guarded URL fetcher + readability HTML→clean-text + JSON-LD + platform handlers + 24h cache | **EXISTS** (production-grade, used by the job-description scraper) | `backend/app/services/job_scraper_service.py` (`_SSRFGuardTransport`, `_assert_public_url`, `_html_to_clean_text`, `_extract_generic_html`) |
| "Pull external structured data → format → insert into resume" flow | **EXISTS** as ORCID publications → LaTeX block | `ai_routes.py:1782` `POST /generate-publications`, frontend `PublicationsPanel` |
| Resume parsers (PDF/DOCX → text) | **EXISTS** | `backend/app/parsers/`, `MultiFormatUpload` |
| Fernet token encryption | **EXISTS** (reuse) | `encryption_service.py` |
| Entitlement gating (`require_feature` + admin matrix) + quota (`enforce_quota`) | **EXISTS** (reuse) | `feature_registry.py`, `middleware/entitlements.py`, `PLAN_QUOTAS` in `config.py` |
| **GitHub repo listing / README reading / project extraction** | **SHIPPED** — GraphQL discovery and defensive parsing both enforce public visibility; candidates are reviewed before insertion | `github_projects_service.py`, `github_import_worker.py`, `ImportProjectsModal.tsx` |
| **LinkedIn/user-resume file import** | **SHIPPED** — parses user-owned LinkedIn export ZIPs and resume files only; no OAuth or scrape path | `sources_routes.py`, `linkedin_import_service.py`, `ImportProjectsModal.tsx` |
| **Generic public URL project ingest** | **SHIPPED** — static SSRF-guarded fetch, bounded response, LLM extraction with platform fallback, editable review | `sources_routes.py`, `url_projects_service.py`, `ImportProjectsModal.tsx` |

**Takeaway:** GitHub import is ~50% plumbing you already own (OAuth + encrypted token + authed client). URL ingest reuses the SSRF scraper. Only the *consumers* are net-new.

## 5. Proposed solution — phased

### Phase 1 — GitHub import (SHIPPED)

**Why first:** official API (zero ToS risk), effectively free rate limits, highest recruiter signal, and half-built.

**Flow:** Connect GitHub (or reuse existing connection) → `POST /github/import-projects` → Celery `github_import_worker` → fetch + rank + summarize → return **candidate `ProjectEvidence` records** → user reviews/edits/selects → selected items feed the optimizer (or insert as an Experience/Projects section) → user approves before write.

**Fetch (hybrid GraphQL + REST):**
- One **GraphQL** call: `user.pinnedItems(first:6)` (user-curated = highest signal) + `user.repositories(first:100, ownerAffiliations:OWNER, orderBy:{field:STARGAZERS})` → stars, forks, primaryLanguage, topics, description, isFork, pushedAt, README existence. ~1 point of the 5,000/hr budget.
- **REST** per selected repo: `GET /repos/{o}/{r}/readme`, `GET .../languages`, optionally `contents/{package.json|requirements.txt|go.mod|Cargo.toml}` for stack inference.
- **Auth:** use the **connecting user's own OAuth token** so each user gets their own 5,000/hr bucket. Read **public repos only**. Serialize per-user fetches (avoid GitHub secondary rate limits).

**Ranking heuristic** (take top 4–6, always include pinned, exclude forks by default):
```
score = 3.0*log10(stars+1) + 1.5*log10(forks+1)
      + 2.0*e^(-months_since_push/12) + 1.0*has_readable_README
      + 0.5*has_topics + 0.5*has_description + BIG_BOOST_if_pinned
penalize/exclude: isFork, isArchived, README<100 chars
```

**LLM summarization:** truncate/summarize each README (first ~1,500 tokens or an "extract what/why/tech" pass) before it hits the prompt. Under **BYOK this runs on the user's own key → ~zero marginal cost to Latexy.**

### Phase 2 — Portfolio / project URL ingest (SHIPPED)

Generalize `job_scraper_service` into a shared `ContentIngestService` and add `POST /ingest/url`. **Static fetch only** (Trafilatura or the existing scorer); **skip JS-heavy pages** with a clear "couldn't read this page" message rather than spinning up headless Chrome. Honor **robots.txt**; enforce the existing **SSRF guard**, redirect/size/content-type/timeout caps on every fetch. LLM structures cleaned text into `ProjectEvidence`. Lower signal-to-noise than GitHub → build after it.

### Phase 3 — LinkedIn via user-owned data (SHIPPED, COMPLIANT ONLY)

Three user-initiated, ToS-safe paths (no automated access, ever):
1. **Upload LinkedIn data archive** (Settings → Data Privacy → *Get a copy of your data* → parse `Positions.csv`, `Skills.csv`, `Education.csv`, `Profile.csv`). Note: the large archive takes 24–72h for the user to generate → async "come back later" UX.
2. **Upload existing resume PDF/DOCX** — reuse `backend/app/parsers/`. Fastest, highest-conversion; covers most users.
3. **Paste public profile text** — user-initiated copy = compliant.

## 6. Shipped data flow & API

The proposed new tables were not required. GitHub reuses the encrypted
integration state on `User`; the worker stores an owner-bound result envelope
in Redis for roughly one hour. URL and uploaded-file imports return candidates
directly. No raw external-source archive is persisted by these routes.

**Normalized shape** (decouples ingestion from optimization):
```
ProjectEvidence { source, title, description, tech[],
                  metrics{stars,forks,...}, dates, url, raw_excerpt, confidence }
```

**Endpoints (all feature-gated; AI paths are metered):**
- `POST /github/import-projects` → job id; `GET /github/import-projects/{id}` → owner-bound candidate evidence
- `POST /sources/import-url` → evidence for one public URL
- `POST /sources/import-linkedin` → evidence from a user-owned ZIP/PDF/DOCX upload
- Selected, editable evidence is converted to LaTeX and inserted only after the user confirms it.

**Caching:** GitHub import results are ephemeral Redis data keyed by job id and
bound to the initiating user. Durable normalized-evidence storage remains a
future optimization, not shipped behavior.

## 7. Legal & privacy (must-dos) ⚠️

**LinkedIn is a legal minefield — decisions locked here:**
- LinkedIn's official API (OpenID Connect) returns **only name/email/photo** — no positions/experience. Rich data is Partner-only, effectively unavailable to a small SaaS.
- **Scraping LinkedIn violates its User Agreement.** `hiQ v. LinkedIn` ended with hiQ enjoined + $500K to LinkedIn (no-CFAA-crime ≠ permitted — it's breach-of-contract). **Proxycurl was sued and shut down (July 2025)** under a permanent injunction. Third-party LinkedIn data vendors (Bright Data, PDL) carry the same exposure LinkedIn is actively litigating.
- **Competitors that "paste your LinkedIn URL to import" are scraping and violating ToS. Do not copy this.**
- **Verdict: never scrape LinkedIn or buy LinkedIn data. Only user-owned data uploads.**

**Cross-cutting:**
- **Explicit opt-in per source.** GitHub consent copy: *"Latexy will read your **public** GitHub repositories (names, descriptions, READMEs, languages, stars) to suggest resume content. We do not read private repositories. You can disconnect anytime."*
- **Narrowest scope:** public import requests **no OAuth scope**, which GitHub defines as read-only access to public information. Do not request `public_repo`: despite its name, it includes write access. Private resume sync separately and explicitly requests `repo`, because GitHub OAuth does not offer read-only private source-code access.
- **Encrypted tokens** (Fernet, already in place); **disconnect** revokes the complete GitHub app authorization, removes the encrypted local token/capability metadata, and disables per-resume sync. Import candidates are ephemeral Redis job results rather than durable `ingested_projects`; already accepted resume text remains user content.
- **Never auto-write to the resume** — human review required.
- **URLs:** SSRF guard mandatory, robots.txt honored, provenance logged.

## 8. Entitlement & metering

- Add `FeatureDef` keys to `feature_registry.py`: `ai_import_github`, `ai_import_url`, `ai_import_linkedin_archive` (category `integrations` or a new `ai_personalization`), bound to the premium AI tier via the admin matrix.
- Gate routes with `Depends(require_feature("ai_import_github"))` etc.
- Meter with `enforce_quota(...)` — reuse `ai_assists` (or add an `imports` dimension to `QUOTA_DIMENSIONS` + `PLAN_QUOTAS`). Per-user rate-limit URL ingestion.

## 9. Success metrics

- % of AI-tier users who connect ≥1 source; % of imports that result in ≥1 accepted project bullet.
- Reduction in time-to-first-optimized-resume for importers vs non-importers.
- AI output quality (accepted-suggestion rate — ties to PRD 2's review loop) for grounded vs ungrounded runs.
- Zero ToS/abuse incidents (SSRF, rate-limit) — guardrail metric.

## 10. Effort & sequencing (rough)

| Phase | Scope | Effort | Risk |
|---|---|---|---|
| 1 GitHub | new endpoints + worker + ranking + README summarize + review UI (reuses OAuth/token/client) | ~1–1.5 wk | Low (official API) |
| 2 URL ingest | generalize scraper → `ContentIngestService` + endpoint + review UI | ~0.5–1 wk | Low-med (abuse controls) |
| 3 LinkedIn (user data) | archive parser + resume-upload path + review UI | ~0.5–1 wk | Low (compliant) |

## 11. Open decisions for founder

1. **Positioning:** lead marketing with **GitHub import** as the developer differentiator? (Recommended.)
2. **Scope tightening — RESOLVED:** public import uses an unscoped OAuth token; private sync requests `repo` only when selected. A future GitHub App migration could make private-repository permissions finer-grained and short-lived.
3. **Insert model:** should imported projects feed the *optimizer prompt* as evidence, or generate a standalone **Projects/Experience section** the user drops in (ORCID-style)? (Recommend: both — evidence for optimize, and a "generate section" quick action.)
4. **Tier & quota:** which plans get imports, and what monthly cap (reuse `ai_assists` vs a new `imports` dimension)?
5. **LinkedIn UX:** ship the async data-archive path in v1, or start with just resume-PDF upload (fastest) and add archive later?
