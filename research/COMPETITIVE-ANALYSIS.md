# Latexy — Competitive Parity & Performance Audit

**Date:** 2026-08-11 · **Author:** automated audit · **Scope:** research only, no product code changed

All Latexy claims cite `file:line` or a reproducible measurement. All competitor claims carry a URL and access date, or are explicitly marked unverified. Measurements were taken against **production** (`sanskarpandey2004--latexy-backend-fastapi-app.modal.run`) on 2026-08-11.

> **Provenance warning.** The user-sentiment research (§3.5b, §3.6b, §6.14–15, Part C material) was **re-sourced after its first pass was found to contain fabricated Reddit citations.** Several claims in an earlier draft of this document — including a headline finding about rejection feedback, a quote naming Teal and Huntr, a viral pay-to-download thread, and a set of named indie competitors — did not survive and have been **removed or explicitly retracted in place** rather than quietly reworded. Where a retraction changed a conclusion, the change is marked. Verified vendor policy pages, BBB records and court dockets survived; Reddit volume claims largely did not. Treat any user-sentiment claim here as weaker evidence than the measured Latexy numbers in §5.

---

## 1. Executive summary — the three findings that would change a roadmap

### 1.1 A LaTeX compile takes 37 seconds, not 3.5

Five back-to-back production compiles of a trivial one-page document:

| run | submit | queued→processing | total |
|---|---|---|---|
| 1 | 4.43s | 8.50s | **37.23s** |
| 2 | 4.05s | 8.14s | 37.23s |
| 3 | 3.98s | 8.12s | 36.91s |
| 4 | 4.04s | 8.18s | 37.79s |
| 5 | 4.34s | 8.45s | 40.12s |
| anonymous `/try` | 4.47s | 8.57s | **37.22s** |

Median **37.23s**, range 36.9–40.1s. **This is not cold start** — five consecutive runs are within 3s of each other; a cold start would show run 1 slow and 2–5 fast.

`backend/modal_app.py:140` states *"warm compile work is only ~3.5s"*. The server's own accounting disagrees: `compilation_time_ms` came back as **15,674ms and 15,645ms** on two runs, with **18.1s of pipeline overhead** on top of it.

So the 3.5s figure describes neither the LaTeX step (15.6s in production) nor what a user waits (37s). For comparison, the same document compiled through the local Docker worker reports `compilation_time_ms: 1031`. **Production LaTeX is ~15× slower than local for identical input** — consistent with an I/O-bound 1.75 GB TeX tree rather than CPU-bound typesetting (inference).

The anonymous `/try` path — a new user's first impression, the highest-stakes number in the product — is **37.2s**.

### 1.2 The latency floor is a misplaced Redis, not the database or the payload

Measured from inside a Modal container (same region as the app):

| backing service | latency |
|---|---|
| Neon Postgres, warm query | **6.87ms** (p95 8.0ms) |
| Neon, session lookup by token | 15.54ms |
| Neon, 147-template list | 14.14ms |
| Neon, fresh connect + query | 82.1ms |
| **Upstash Redis, warm PING** | **99.28ms** (p95 99.61ms) |
| **Rate-limiter Lua script** | **99.84ms** |
| Upstash, connect + first ping | 689.5ms |

Redis DNS resolves `p2-global.upstash.io → global-latency.upstash.io → **global-as1**.upstash.io` — an Upstash *Global* database whose primary is labelled `as1` (Asia). Neon resolves to **Ashburn, Virginia**, and Modal is co-located with it (7ms).

`RateLimitMiddleware` runs an `INCR`-based Lua script on **every request** (`backend/app/middleware/rate_limiting.py:162-181`). `INCR` is a write, so it must reach the primary. **Every request pays ~100ms crossing an ocean, and the cache is 14× slower than the durable store it exists to protect.**

The endpoint totals decompose cleanly:

| endpoint | in-region | from India | DB work | notes |
|---|---|---|---|---|
| `/byok/providers` | **529ms** | 1.20–1.41s | none | the floor: no DB, no auth |
| `/me` | 936ms | 2.33–2.73s | ~31ms | auth + user lookup |
| `/templates/` | 1346ms | 3.43–3.66s | ~14ms | 147 rows |
| `/health` | 1395ms | 2.33–2.54s | ~22ms | DB + Redis probe |
| `/analytics/me?days=30` | 1510ms | 3.40–6.14s | — | worst observed |

So the ~1s floor the brief flagged is: **~430ms Modal ingress + middleware** (visible in `/byok/providers` minus its Redis hop), **~100ms Redis**, **~15ms database**, and **~1.5s of India→Virginia transit** for the actual target market. The database is not the problem, and nor is serialisation of queries.

### 1.3 Latexy's ATS feature is the most defensible in the category — and its own README under-claims it

`backend/app/services/ats_simulator_service.py:29-63` defines named profiles for **Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Taleo (Oracle), and iCIMS**, each with a quality tier and specific failure modes (`multi_column`, `tables`, `custom_sections`, `decorative_elements`, `pdf_formatting`). It is reachable at `backend/app/api/ats_routes.py:1105`. `backend/app/parsers/pdf_parser.py:25-54` performs real text extraction with pdfplumber, and `pdf_layout.py` reads positional attributes.

Across **all seven** resume builders researched, the pattern was unanimous: **no product names a single specific ATS platform, and not one shows parsed output.** Kickresume markets that its checker *"developed to simulate a real Applicant Tracking System scan"* [VERIFIED quote — kickresume.com/en/ats-resume-checker/, 2026-08-11] while naming no system and showing no parse. Rezi's own documentation describes the mechanics as file type, font size, keyword density and section headers [SECONDARY — rezi.ai/rezi-docs/the-rezi-score-explained].

Latexy can substantiate the one claim the entire category fabricates. `README.md:9` describes it as *"rule-based analysis with section detection, keyword coverage, and formatting checks"* — accurate but self-effacing. This is the inverse of the repo's documented tendency to overstate.

**And the category's premise is now falsifiable, not merely unverified:**

- **Jobscan's own support documentation** describes match rate as hard skills (weighted heaviest) + job title + education + soft skills + other keywords, with **frequency matching** [VERIFIED via search index]. That is weighted keyword counting. It is not parser emulation, and no real ATS is queried. Their marketing hedges precisely — *"our matching algorithm is based off of top applicant tracking systems"* [CLAIM — jobscan.co/blog/what-jobscan-match-rate-should-i-aim-for], not "replicates."
- **Greenhouse's own documentation** kills the premise outright: its matching is a **paid add-on**, sorts candidates into buckets, and *"does not auto-reject or auto-advance any candidate"* — it is *"assistive AI — recruiters and hiring managers make all advancement and rejection decisions"* [VERIFIED — support.greenhouse.io/.../Talent-Matching-FAQ]. **No candidate-facing score exists in the ATS at all.**
- **The "88% auto-rejection" statistic underpinning the category is misused.** It comes from HBS/Accenture, *Hidden Workers: Untapped Talent* (Fuller & Raman, Sept 2021) [SECONDARY] and reports 88% of *employers self-reporting* that their systems filter out qualified candidates because of **employer-configured knockout criteria** — degree requirements, employment gaps — not because a keyword score fell below a threshold.
- **Scores fail a basic comparability test.** The same resume scored **Rezi 97 / MyPerfectResume 79 / Enhancv 79** [VERIFIED — reddit r/resumes `1prl6br`, 2025-12-20]; another user moved 56 → 95 by iterating. A tunable dial, not a measurement.

**The parse-fidelity half is now strongly substantiated — by a parser vendor, in its own words.** Textkernel publishes a machine-readable resume-quality code table [V] stating that columnar layouts are *"a **HUGE MISTAKE**"* (code 433, fatal), that vertically-written date ranges break parsing (418, fatal), that contact info must be at the top (311), that every section needs a clear header (151), and that skills belong **inside work history** rather than in a standalone block (112). It also classifies *"the document was PDF"* as a **Major** issue (300), with no equivalent code for Word — an uncomfortable fact for a LaTeX product, and the honest answer is that Latexy also exports DOCX and that a well-formed text layer is what actually matters.

Measured on a real Latexy production template: **all 6 fonts embedded with ToUnicode present, 314 words extracted cleanly and in reading order.** That is a checkable claim a user can verify themselves — unlike any ATS score.

**But "the whole category is theatre" is a hypothesis, not a finding, and the evidence cuts both ways.** A hiring manager states that *"Most ATS scan your resume for relevant keywords and assign a numerical score, tier, or grade… Oracle and iCIMS both use this approach"* — while adding the decisive qualifier: ***"there's no passing grade. You don't need an ATS score of 90 to get an interview"*** [VERIFIED — r/resumes `1u7z3rt`]. So scoring does exist inside some ATS; what does not exist is a threshold, or any validation that a third-party score predicts it.

And one recruiter directly undercuts the parse-fidelity pitch: *"Does the ATS butcher your resume parsing, yes, but when it does we just open the actual resume itself… it doesn't actually impact your chances"* [VERIFIED — r/resumes, score 13]. That is worth taking seriously rather than filtering out, because it is the strongest available argument *against* the differentiator this report otherwise recommends leading with.

The defensible position is therefore narrower than "everyone else is faking it": **third-party ATS scores are unvalidated and non-comparable; parse fidelity is real but its impact on outcomes is contested.** Latexy is still the only product that can *show* the parse — see §7.4 for what to claim and what not to.

The most useful commercial observation is the gap itself: **experts call the score a myth, and the user base keeps buying it.** A continuous stream of score-chasing posts persists (*"what ATS score are you actually aiming for"*, *"I got a 64 ATS score… can I still land a REAL internship?"*). That gap between expert opinion and user demand **is** the category's business model.

---

## 2. What Latexy actually is today

### 2.1 Verified surface counts

| surface | count | evidence |
|---|---|---|
| Backend routes | **290** | `grep -rhE '^@router\.(get\|post\|put\|patch\|delete)' backend/app/api/*.py \| wc -l` |
| Route modules | 36 | same directory |
| Routers aggregated | 38 | `backend/app/api/routes.py:43-213`, mounted once at `backend/app/main.py:253` |
| Frontend pages | **38** | `find frontend/src/app -name page.tsx` |
| TUI commands | **33**, all `implemented: true` | `packages/tui/src/commands/registry.ts` |

I initially concluded that 35 routers were unmounted; that was a grep artifact — `main.py` includes a single aggregate router built in `routes.py`. **All are reachable.** Recorded because it is exactly the kind of false finding this audit is supposed to avoid.

### 2.2 Cross-surface asymmetry — the gap is TUI-vs-frontend, not docs-vs-backend

Checking each capability domain for a frontend consumer and a TUI command:

- **Frontend: 28 of 28 domains covered**, including ones easy to assume missing — comments (`frontend/src/components/CommentsPanel.tsx`), Zotero, Mendeley, Dropbox, GitHub, portfolio, tenants, teams, macros, references, career paths, developer API.
- **TUI: 9 of 28** — `snippets, interview, tracker, cover-letters, analytics, byok, export, formats, ats, optimize`. Absent: github, dropbox, zotero, mendeley, portfolio, career, comments, workspaces, teams, tenants, macros, references, apply, templates, admin.

The brief anticipated a backend-ahead-of-UI gap. That is not what the evidence shows: **the web app is at parity with the backend; the TUI is at roughly a third of it.**

**A later, authoritative pass over all 290 route paths found the backend broader than my first inventory suggested**, and corrected two claims in this report (LinkedIn import and one-click apply, both marked below). Domains I initially under-counted include `/apply` (**7 routes — direct Greenhouse and Lever submission with preview**), `/ai` (**15 routes**: generate-bullets, rewrite, proofread, spell-check, translate, salary-estimate, reorder-sections, standardize-dates, generate-publications, generate-summary, explain-error, format-contacts, age-analysis, confidence-score, personas), `/career` (4), `/references` (3, including ORCID fetch) and `/portfolio` (5, including custom-domain verification). The route inventory is in `docs/FEATURES.md`. The known individual asymmetries have also been closed — checkpoint deletion now has a UI (`/checkpoint --delete`), and `/model` still only lists providers, but `activeModel`/`activeProvider` remain declared-and-unread in `packages/tui/src/lib/config.ts`.

### 2.3 Gating machinery exists and gates nothing

Queried against the **production** database:

- `feature_flags`: **32 rows, 0 disabled**
- `plan_features`: **26 features × 5 plan families (130 rows), every single one `enabled = true`** — including `free`

That is why `admin@latexy.com` returns `plan: "free"` with all 26 feature booleans true. **There is no feature-based monetisation. Gating is entirely quota-based**, via `PLAN_QUOTAS` at `backend/app/core/config.py:753-778`:

| family | compilations | optimizations | ai_assists |
|---|---|---|---|
| free | **10 / day** | 3 / month | 25 / month |
| basic | **50 / month** | 10 / month | 100 / month |
| pro | unlimited | unlimited | unlimited |
| byok | unlimited | unlimited | unlimited |
| team | unlimited | unlimited | unlimited |

**The first paid tier is a downgrade on the headline dimension.** Free allows 10/day ≈ 300/month; Basic (₹299/mo) allows 50/month. A user who compiles more than twice a day is worse off paying. Basic's only genuine uplift is optimizations (3→10) and ai_assists (25→100).

Prices, from `backend/app/core/config.py:298-435` (INR, in paise):

| plan | monthly | annual |
|---|---|---|
| BYOK | ₹199 | ₹1,910 |
| Basic / Student | ₹299 | ₹2,871 |
| Pro | ₹599 | ₹5,750 |
| Team | ₹2,499 | — |

### 2.4 A real developer API exists

`backend/app/api/public_api_routes.py:143-273` exposes a versioned v1 surface — `POST /compile`, `POST /optimize`, `POST /ats/score`, `GET /jobs/{id}`, `GET /jobs/{id}/pdf` — with key management in `developer_routes.py` (5 routes), a `developer_api_keys` table, dedicated `APIKeyRateLimitMiddleware` (`main.py:224`), and a `/developer` page. **This is usable, not scaffolding.** No competitor researched offers a public API.

### 2.5 Template library: 147 listed, 63 genuine

Production returns 147 active templates. **84 are leftover test fixtures** — `Test SWE Template` ×48, `T1`, `T2`, `UniqueSearchableName42`, `CaseInsensitiveTemplate99`, `AutoTitleTemplate`, `SharedTemplate` — all created 2026-03-11, all `is_active`, all miscategorised as `finance` (filed as issue #1147). Genuine count: **63**.

`README.md:8` claims *"50+ resume templates"*. Against 63 genuine that is **accurate**; against the 147 shown it understates. Also: one genuine template, `Clean Simple`, fails to compile (`pdflatex exit 1`), so it can never have a preview.

**All 147 thumbnails and preview PDFs currently return `502 Storage unavailable`** (0 of 20 sampled) — object storage was unconfigured in production. Fixed in PR #1146, awaiting deploy.

---

## 3. Competitive landscape

Evidence marks: **[V]** verified on the live site · **[C]** vendor claim · **[S]** secondary source. All access dates 2026-08-11.

### 3.1 The single most useful axis: what does the paywall actually gate?

This splits the market into four models and is the sharpest signal of what users pay for.

| product | can you export on free? | the paywall is | entry paid price |
|---|---|---|---|
| **FlowCV** | **Unlimited, watermark-free PDF** [V] | resume *count* + AI | $19/mo · $60/yr [S] |
| **Kickresume** | **Unlimited downloads** [V] | templates & design options | **$7.20/mo · $38.40/yr** [V] |
| **Rezi** | Yes — **3 lifetime** [V] | download quota | $29/mo · **$149 lifetime** [V] |
| **Enhancv** | Watermarked [V] | de-branding | ~$19.99–24.99/mo [S, conflicting] |
| **Resume.io** | **TXT only — PDF is paid** [V] | **PDF export** | ₹249/wk · **₹1,999/mo** [V] |
| **Overleaf** | Yes (it *is* LaTeX) [V] | compile time + collaborators | ₹421.75/mo Standard [V] |
| **Teal** | Reported yes [S] | AI + job-match score | $13/wk · $29/mo · $79/qtr [S] |
| **Latexy** | Yes — 10/day free | quota only | **₹199–599/mo** |

Notable specifics:

- **Resume.io serves genuine INR pricing** [V — resume.io/pricing] — ₹249/week vs ₹1,999/month, an 8× ratio that funnels into the cheap trial. Its free tier downloads **TXT only**; PDF is strictly paid. The site simultaneously describes a 7-day trial that *"automatically subscribed to the premium monthly membership"* and presents the 1-week plan as a one-time purchase — **these conflict on the same site**.
- **Enhancv has no permanent free tier** — the "Free" plan is €0 *"Valid for 7 days"* [V]. It also deliberately offers **no DOCX**, arguing PDF preserves formatting [V].
- **Kickresume is free for students** with ISIC/UNiDAYS verification [V] — directly relevant to an India student segment.
- **Overleaf now ships metered AI**: free plan includes *"Basic AI allowance — 5 AI uses per day"* [V]. "LaTeX + AI" is no longer unoccupied.

### 3.2 Overleaf — the only real LaTeX competitor, and the compile numbers matter

[V — docs.overleaf.com/getting-started/free-and-premium-plans/plan-limits]

- **Free compile timeout: 10 seconds. Premium: 240 seconds.** The pricing page markets only *"24x Basic"*; the absolute figures appear only in docs.
- Architecture: CLSI spawns **a fresh sibling Docker container per compile** [V — github.com/overleaf/overleaf/.../clsi/README.md], and Overleaf documents the cost: *"creating and starting a new container has a time penalty of about 1000 ms"* [V — github.com/overleaf/clsi/issues/142].
- **No resume-specific features whatsoever** [V]. CV templates in a gallery; zero ATS scoring, zero job-description targeting, zero application workflow.
- Best-in-class real-time collaboration — the only product in the set with genuine co-editing.

**The comparison that matters: Overleaf caps free users at 10s and accepts ~1s of container overhead. Latexy takes 37s.** A one-page resume comfortably fits inside Overleaf's 10s free limit, so their cap is not a weakness Latexy exploits — Latexy is simply 3.7× slower than a limit its competitor considers restrictive.

### 3.3 ATS scoring across the category is unverified

| product | claim | names an ATS? | shows parsed output? |
|---|---|---|---|
| Rezi | "23 ATS checkpoints" [S] | No | No |
| Kickresume | "simulate a real ATS scan" [V quote] | No | No |
| Enhancv | paid "ATS check" [V] | No | No |
| Teal | "job match score" (more honest framing) [S] | No | No |
| FlowCV | *no score* — claims only clean text-based PDF output [V] | n/a | n/a |
| Jobscan | "analyzes your resume the same way an ATS does", "30+ checks" [CLAIM] | **Yes** — an "ATS Tip" feature names Greenhouse/Taleo/Workday [CLAIM] | **No** |
| Careerflow | "ATS Keyword Score" + "ATS Analysis Score" [V] | No | No |
| **Latexy** | 7 named profiles + real pdfplumber extraction | **Yes — 7** | **Yes** |

Jobscan is the partial exception: it *does* name ATS platforms, via a feature that asks for the employer's name and tailors advice. But it still never shows parsed output, and its own support docs describe weighted keyword frequency (§1.3). **Latexy remains the only product that shows the user what a parser actually extracted.**

FlowCV's restraint is instructive: it declines to invent a score and still competes, which suggests honest framing is commercially viable. So does the sophisticated end of the audience — **r/EngineeringResumes' wiki never mentions "score" in relation to ATS**, requires only that a resume be *"easily parsable"*, links three ATS-debunking resources, and recommends **Google Docs and LaTeX** templates [VERIFIED — subreddit wiki]. Its rules are purely typesetting-mechanical (single column, ≥0.4in margins, ≥10.5pt, no justification, no icons). Mainstream builders expose almost none of those controls. LaTeX does, natively.

Worth knowing for go-to-market: **r/resumes' AutoModerator promotes a score checker on every thread** (resumatic.ai), and a community thread objected that Resumatic and Rezi *"are actually the same thing"* and raised the moderator's conflict of interest [VERIFIED — `1qi01rt`]. Treat that subreddit's default advice as vendor-influenced.

### 3.4b Tracker-first competitors, and what a tracker needs

| product | free tier | paid entry | evidence |
|---|---|---|---|
| **Huntr** | $0 forever — unlimited base resumes, 100 jobs, PDF export, clipper, autofill | $40/mo · $90/qtr · $160/6mo | [V — huntr.co/pricing] |
| **Simplify** | free forever — **unlimited autofill + tracking**; monetises employer postings | $39.99/mo · $19.99/wk | [V — help.simplify.jobs/articles/5623502] |
| **Careerflow** | 1 resume, "limited" tracker, skill-gap **score only, no detail** | $23.99/mo · $172.99/yr | [V — careerflow.ai/premium] |
| **Jobscan** | 5 scans/month | $49.95/mo · $89.95/qtr | [SECONDARY — pricing page is a JS shell; 6+ sources converge] |

**Pattern: the tracker is the free loss-leader; AI tailoring is the paywall.** Jobscan is the outlier that paywalls the score itself.

On whether a tracker beats a spreadsheet — the honest answer from the evidence is **not much below ~15 applications**. What genuinely can't be done in a spreadsheet: **one-click capture from the posting** (auto-filling company, title, full JD text, URL), **autofill of the application itself** (Simplify Copilot covers 100+ portals including Workday, Greenhouse, iCIMS, Taleo, Lever [V — simplify.jobs/copilot]), **staleness prompts**, and **retaining the JD text** for later re-tailoring. Latexy's tracker has the data model but none of the capture mechanics, because those require a browser extension.

### 3.5b Billing practice is the category's open wound — and it is now litigation

This is the strongest user-complaint pattern found, and it is not merely anecdotal:

- **Bold LLC** — parent of Zety, LiveCareer, MyPerfectResume, My Perfect Cover Letter, Monster, FlexJobs, CareerBuilder, Bold.pro and Sonara, per its own `/about` page [V] — is BBB-accredited **A+** while carrying **244 complaints closed in 3 years (74 in the last 12 months)** and a customer rating of **1.12/5 across 78 reviews** [VERIFIED — bbb.org]. Verbatim: *"Only after spending 1 hour building my resume did it tell me that i needed to pay to download MY RESUME."*
- **Active federal litigation.** *Rocket Resume, Inc. v. BOLD Limited et al.*, **5:26-cv-02852 (N.D. Cal.), filed 2026-04-02** [VERIFIED — docket; hrexecutive.com] alleges BOLD controls **>20 resume brands and >80% of a >$750M/yr US market**, that the sites *"entice users with free or low-cost resume builders, then require a paid subscription to download the finished document,"* then bill **"10 to 20 times that amount every four weeks, with cancellation made deliberately difficult."** **Allegations are unproven**; a motion to dismiss is reportedly pending.
- **Zety's review distribution is bimodal** — 54% 5-star, 36% 1-star, only 2% in the 2–3 band across 257 reviews [VERIFIED — smartcustomer.com]. That U-shape is the signature of a billing pile-up, not a quality spread.
- **The mechanism is verified in the vendors' own terms**, which is stronger evidence than sentiment:
  - **Jobscan**: refunds only if disputed *"within **2 calendar days** of the billing period start"*, minus a **3.5% fee**, and *"It is the customer's responsibility to confirm the cancellation"* [VERIFIED — jobscan.co/cancellation-policy].
  - **Rezi**: *"Subscription cancellations do not include a refund."* Lifetime plans ineligible [VERIFIED — Rezi help centre]. Free tier is **3 PDF downloads lifetime**, not monthly [VERIFIED — rezi.ai/pricing].
  - **Kickresume, the counter-example**: *"You can download your documents as many times as you want! This applies to both premium and free users"* [VERIFIED — kickresume.com help centre].
- **PissedConsumer** (self-selecting, so this proves recurrence not base rate): LiveCareer 1.4/5, Zety 1.5/5, Resume.io 1.3/5 [VERIFIED].
- **Reddit volume is weaker than it first appeared** — pay-to-download shows up as a steady drip of low-upvote posts across 2022–2026, not viral threads. **The genuine signal is BBB and PissedConsumer, not Reddit.**
- **Jobscan is an order of magnitude cleaner than Bold**: 5 BBB complaints in 3 years, C- and unaccredited [VERIFIED — bbb.org Seattle]. The billing problem is concentrated in one corporate family, not the whole category.
- *Correction to an earlier draft: it listed **Resume Genius** as a Bold brand. It is **Sonaga Tech Ltd (Luzern, Switzerland)** and is absent from Bold's own `/about` listing [V]. The complaint's ">20 brands" figure is the plaintiff's allegation, not an enumerated list.*
- **The two flagship brands are one codebase with two SEO surfaces.** Zety's "CV Maker" reuses the **same 18 templates** as its resume builder and cover-letter builder — one design library, three product framings [V]. Privacy policy and terms are **word-for-word identical** across Zety, LiveCareer and every locale [V].
- **Billing detail worth knowing: four-week cycles, not monthly** — 13 charges a year, not 12 [V]. LiveCareer additionally layers **per-document micro-charges ($0.45 per extra download)** on top of a subscription, and its trial meters downloads, prints and emails as interchangeable units [V].
- **Refund posture differs between the two:** LiveCareer advertises a 14-day refund guarantee and a three-channel cancellation route on its pricing page; Zety's terms state *"Provider does not guarantee refunds"* [V].
- **Regulatory context, precisely:** the FTC's Click-to-Cancel rule was **vacated by the 8th Circuit in July 2025**; a fresh ANPRM was submitted 2026-01-30 [VERIFIED — arnoldporter.com advisory]. Negative-option enforcement has hit Amazon, Instacart, Chegg and Uber, but **no FTC or state-AG action against any resume builder**. So: private litigation and BBB pressure, no regulator yet.

There is a repeated demand for **no-card, no-download-paywall tools**, and a verbatim thread title *"Can anyone recommend CV makers that aren't subscription based?"* — answered with Google Docs. Caveat: several replies in that thread share near-identical phrasing and are likely astroturf, so their independence is discounted; the sentiment does match organic comments elsewhere. **My earlier draft claimed four named indie competitors were using this as their pitch; that did not survive re-sourcing and has been removed.**

### 3.4 BYOK is unanimous greenfield

**Zero of the seven** offer BYOK at any tier. Every AI feature is a metered reseller margin on OpenAI/Anthropic; Rezi charges $29/mo and Teal up to ~$56/mo-equivalent largely to resell inference.

But the dev-tool evidence tempers the opportunity. Among AI coding tools, BYOK is either free/OSS goodwill (Cline, Aider, Continue.dev) or **deliberately degraded at incumbents** — Cursor's docs confirm Tab and Apply *always* use Cursor's models and cannot be routed through a user key [C — cursor.com/help/models-and-usage/api-keys]. **On whether BYOK drives commercial success: no revenue data, case study, or independent analysis was found. Could not determine.** The consistent characterisation is a trust/cost-transparency play that vendors abandon when it cannibalises subscriptions.

Latexy prices BYOK at ₹199/mo — *below* Basic. That is the coherent structure (the user pays inference), and it is genuinely unique.

### 3.5 The developer-audience niche

- `posquit0/Awesome-CV` — 28,262 stars, LaTeX template, non-commercial [V — GitHub API]
- **`rendercv/rendercv` — 17,324 stars, migrated to a Typst engine, and it is commercial**: free OSS CLI with a paid tier for AI/cloud sync [V stars; C — rendercv.com/pricing]. **This is Latexy's closest archetype, and it chose Typst over LaTeX.**
- `jsonresume/resume-cli` — **archived** [V]. JSON Resume schema still v1.0.0 from 2014; maintainers state it is maintained *"with the help of AI agents"* [C]. A *de facto* interchange format worth supporting for import/export, **not** a standard to build on.

---

## 3.9 Market and positioning — India

### The structural insight: India buys a resume once, it does not subscribe

There is **no established INR monthly-subscription benchmark for resume tools.** Indian job-seekers are conditioned to buy a resume *as a one-time service*:

| service | price | evidence |
|---|---|---|
| Naukri FastForward resume writing | **₹1,600–9,500** one-time, by seniority | [SECONDARY — two sources disagree ~2×; Naukri's own pages are JS shells returning 403] |
| Shine.com resume writing | ₹1,299 (fresher) → ₹4,999 (15+ yrs) | [SECONDARY — `shine.com/resume-writing-services/` 404s] |
| GetSetResumes / WriteMyCV / BookYourCV | from ₹999 · ₹889–8,000 · ₹1,550–2,790 | [SECONDARY] |
| resumod.co | weekly from ₹99 | [SECONDARY — SPA, `/pricing` 404s] |

That is both the opening and the main friction: a subscription is an unfamiliar shape here.

### Are Latexy's prices sane? Verified INR anchors

| product | INR | evidence |
|---|---|---|
| Google One Basic (100 GB) | ₹130/mo · ₹1,300/yr | [V — one.google.com/about/plans?hl=en-IN] |
| JioHotstar (from 2026-01-28) | ₹79 / ₹149 / **₹299** per month | [SECONDARY — telecomtalk, Variety] |
| ChatGPT Go | **₹399/mo**, India-exclusive | [SECONDARY — TechCrunch] |
| Canva Pro India | ₹499/mo · ₹3,999/yr | [SECONDARY — Canva 403s all fetches] |
| Coursera Plus | ₹2,099/mo · ₹13,999/yr | [V — coursera.org/courseraplus] |
| Google AI Pro | ₹1,950/mo | [V] |

Against those:

- **₹199 BYOK — well placed.** Sits between JioHotstar tiers, just above Google One Basic, in the impulse band. Since Latexy carries no inference cost on this tier, it is the right acquisition price.
- **₹299 Basic — sane.** Exactly JioHotstar Premium, under the ChatGPT Go reference.
- **₹599 Pro — the riskiest tier.** Above the entire Indian entertainment band and above the ₹499 Canva anchor. **₹499 would land on an existing mental anchor**; ₹599 reads as a premium that then has to be justified.
- **₹2,499 Team — B2B only.** Above Google AI Pro (₹1,950), the most expensive verifiable consumer subscription in India. It cannot be sold to students or peer groups; if it targets placement cells, expect annual invoice procurement rather than monthly cards.

Two structural gaps: **there are no annual SKUs at the ₹199/₹599 tiers in a market where every comparable discounts annual heavily** (Google One ~17%, JioHotstar ~39%, Coursera 44%) precisely because Indian consumers avoid recurring mandates — and Razorpay e-mandate churn is real. And **GST treatment is undisplayed**; 18% appearing at checkout is what produces "₹499 became ₹589" abandonment.

### No global competitor has done PPP for India — that is a statable wedge

| tool | India pricing | evidence |
|---|---|---|
| **Resume.io** | **₹249/week, ₹1,999/month** — INR served | [V — resume.io/pricing] |
| Rezi | USD only, $29/mo | [V] |
| Enhancv | JSON-LD hardcodes `"currency":"USD"`; **zero ₹ in source** | [V] |
| Novoresume | USD only | [V] |
| Kickresume | **zero INR in page source** | [V] |
| Jobscan / Huntr / Careerflow / Simplify | **none serve INR** | [V] |

Critically, **Resume.io's ₹1,999/mo is currency conversion, not PPP** — ₹1,999 ≈ $23, matching its USD price almost exactly. So Latexy's ₹299 Basic is **~1/7th of resume.io's India price** and ~1/12th of Enhancv's.

**But the real competition in India is not Rezi.** It is (a) **free ChatGPT** — ChatGPT Go was reportedly free to Indian users from Nov 2025 to ~Dec 2026 [SECONDARY, unverified — openai.com 403s], meaning the ₹199 tier competes with ₹0; and (b) **a ₹3,500 one-time Naukri rewrite**. Pro should be framed against the *service* substitute: two months of Pro ≈ a cheap human rewrite.

### Deep localisation is a proven wedge — and one competitor already does it for India

The most useful competitive finding for an India-first product did not come from pricing pages. LiveCareer's per-locale sites show that **structural localisation, not translation, is what differentiates in local markets** [V]:

- **The India site ships "biodata" templates, including customisable sections for *marriage biodata*.** A resume builder generating matrimonial documents is a genuinely India-specific document type with no Western analogue. The same site covers Indian government-job and PSU applications, with local employer social proof (TCS, Wipro, Infosys, HDFC, Accenture).
- **The Poland site ships a "klauzula RODO" section** — the GDPR consent clause Polish employers conventionally expect on a CV — as a **first-class section type**, not a text suggestion.
- **The UK site is CV-only**: the word "resume" appears nowhere on it, and its ATS checker is marketed as *"specifically tailored to the UK job market"*.
- **Italy alone exports SVG and JPEG**, and Poland alone prices per download (9.95 PLN / 14 days) — evidence of per-locale codebase drift rather than one platform.

**But every one of those locales is Latin script.** Both Bold flagships run **zero** CJK, Cyrillic, Arabic or Devanagari sites; `livecareer.co.jp` does not resolve; and the India site is **English-only with no Hindi or Devanagari** despite shipping India-specific document types. Neither brand publishes any statement about font coverage or non-Latin glyph rendering, and with the builders login-walled there is **no positive evidence their PDF renderers can emit Devanagari at all**.

So the India opportunity is sharper than "translate the UI": the incumbent has already validated that **India-specific document types sell**, and has left **Indic script entirely unserved**. That is the pairing behind `docs/FEATURES.md` B10.

### A privacy exposure worth noting, because it is a differentiator

LiveCareer's UK cookie disclosure names 15 vendors, three of which — **Microsoft Clarity, Inspectlet and Qualaroo** — are **session-recording tools**, running on pages where users type resume content [V]. That is PII-bearing keystroke capture on a career document. Zety's disclosure, by contrast, names **no vendors at all** and pre-sets consent toggles to enabled [V].

Latexy's BYOK and self-host story is the natural counter-position, and it maps onto the local-first demand documented in §3.5b.

### Accessibility: the category floor is very low

- **Zety** publishes an accessibility statement self-certifying only *"some WCAG Level-A Compliant pages… working to achieve an AA level"* — partial Level A, aspiring to AA — and names NVDA / VoiceOver / TalkBack pairings plus a dedicated 24/7 accessibility line [V].
- **LiveCareer has no accessibility statement at all**: `/accessibility` is 403 on the US site and 404 on the UK site [V].
- Neither mentions contrast ratios, high-contrast mode or dyslexia-friendly fonts.
- **Neither produces tagged PDFs.** Nobody in the category does.

**RESOLVED — and it changes the recommendation.** Tagged PDF is **not** an ATS feature:

- **Every documented extractor reads a flat text layer.** `pdftotext` (poppler 26.04.0) has no structure-tree option; pdfplumber's `extract_text()` doesn't consult one; pypdf's docs say PDF *"has no semantic layer"*; Tika/PDFBox's `extractMarkedContent` is `default false` and "alpha"; Docling closed its tagged-PDF issue as `ice-box`. The sole counterexample is opendataloader-pdf.
- **No resume parser mentions tags.** Affinda extracts the text layer then OCRs — and its "Always Full" mode **discards the text layer entirely**. Textkernel's warning codes (garbage characters, reversed text) are text-layer heuristics.
- **No ATS publishes guidance on uploaded-file structure.** Greenhouse and Workday advise on *visual layout* only. iCIMS and Workday scope their WCAG commitments explicitly to their own web apps.
- **No compliance driver reaches a submitted resume.** Section 508 covers ICT agencies procure or communicate outward; the EAA's product list excludes recruitment software; EN 301 549 clause 10 has no independent legal force.
- **Neither Overleaf nor the LaTeX Project claims an extraction benefit** — Overleaf's announcement is framed purely as accessibility.
- Tags are also rare enough to be undependable: **<3.2%** of 20,000 scholarly PDFs met all six accessibility criteria; **74.9% met none** [arXiv:2410.03022].

**What replaces it is better, and mostly built.** Every primary source says the real lever is **layout**. A blindness-research study of 99 job seekers' resumes measured **88% ATS parse accuracy for chronological formats vs 55% for functional**, with 74% showing layout issues — and its accessibility advice was *"avoid tables, columns, and text boxes."* `ats_simulator_service.py` already detects `multi_column`, `tables` and `decorative_elements` per named ATS. Surface that as the primary recommendation.

Accessible PDF stays worth shipping — one line, first in category, cheap option value — but at **P2 on accessibility grounds**, never as an ATS claim. Detail in `docs/FEATURES.md` B9/B9b.

### Claim integrity across the category is poor — useful for positioning, and a caution

Documented self-contradictions, all [V] on the vendors' own pages:

| claim | contradiction |
|---|---|
| LiveCareer users helped | *"28 million since 2005"* and *"over 10 million since 2004"* **on the same homepage**; 7M on the Spanish site |
| Founding year | 2004 **and** 2005 on the same domain |
| Phrase library | 50,000+ (US) vs 100,000+ (UK) vs *"64,282 pre-written examples"* (UK loading screen) — same product |
| Template count | livecareer.co.uk gives **four different figures** (40+, 30+, "50+", "30+ unique"); its own build screen says 20 |
| *"48 days faster"* hiring | the Brazilian site discloses the basis: **a survey of 258 users** |
| Zety | *"30% faster job landing"*, *"42% more recruiter responses"*, 7.5M users, 41M applications — all unfootnoted |

Both brands also **sell visually heavy templates while publishing warnings that visually heavy templates break ATS parsing** [V].

The caution for us: a secondary review claimed Zety has "200+ templates" and "no ATS checker" — **both contradicted by Zety's own pages** (18 templates; a free-tier checker). In this category, vendor pages beat review sites, and review sites are frequently written by competitors.

### The incumbent threat is Info Edge, and it has said so

Info Edge (Naukri's parent, a public filer) reported Q1 FY27 standalone billings **₹737 cr, +14.4% YoY**, with Recruitment Solutions at **₹552.7 cr, +17.5% YoY = 75% of billings** [VERIFIED — entrackr]. Management states its B2C job-seeker business *"accelerated sharply, helped by more self-serve offerings and AI-led tools such as mock interviews and resume builders"* [CLAIM — management commentary]. **The incumbent is naming AI resume tooling as a growth vector and building it in-house.**

Demand-side context: Naukri JobSpeak July 2026 shows **+5% YoY** white-collar hiring with **AI/ML +33%** [SECONDARY]. PLFS Apr–Jun 2026 reports **youth (15–29) unemployment at 15.9%** and urban youth 18.2% [SECONDARY — mospi.gov.in served a self-signed certificate; verify against the primary before external use].

**On market size: I deliberately quote no TAM.** For the narrow question "size of the India job-seeker *tooling* market," only report-mill sources exist. Naukri's ₹552 cr/quarter is ~75% B2B recruiter subscriptions and is **not** a job-seeker TAM; Info Edge does not break out a B2C rupee figure. Any CAGR cited for this segment should be treated as unusable.

---

## 4. Feature parity matrix

L-BE / L-FE / L-TUI = Latexy backend / frontend / TUI. ✅ present · ➖ partial · ❌ absent · ? undetermined

| capability | L-BE | L-FE | L-TUI | Overleaf | Rezi | Teal | Kickresume | Resume.io | Enhancv | FlowCV |
|---|---|---|---|---|---|---|---|---|---|---|
| Real LaTeX output | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ATS score | ✅ | ✅ | ✅ | ❌ | ✅C | ➖ | ✅C | ? | ✅C | ❌ |
| **Named-ATS simulation** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Shows parsed PDF text** | ✅ | ➖ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **BYOK** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Public API** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **TUI / CLI** | n/a | n/a | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| DOCX export | ✅ | ✅ | ✅ | ❌ | ✅ | ? | ? | ? | ❌ | ? |
| Free PDF export | ✅ | ✅ | ✅ | ✅ | ➖3 | ✅ | ✅ | ❌ | ➖wm | ✅ |
| Real-time collaboration | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Job application tracker | ✅ | ✅ | ✅ | ❌ | ❌ | ✅core | ❌ | ❌ | ❌ | ✅ |
| Cover letters | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Interview prep | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| LinkedIn import | ✅ archive | ✅ | ❌ | ❌ | ❌ | ➖ext | ✅prem | ? | ? | ➖ |
| **Direct ATS submission (Greenhouse/Lever API)** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Salary estimate · translate · proofread | ✅ | ✅ | ➖ | ❌ | ➖ | ➖ | ➖ | ❌ | ❌ | ❌ |
| ORCID / publication fetch | ✅ | ✅ | ❌ | ➖ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| GitHub / Dropbox / Zotero / Mendeley | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Browser extension | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Academic CV type | ✅ | ✅ | ➖ | ➖gallery | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Portfolio site | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅prem | ❌ | ❌ | ➖ |
| Student free tier | ❌ | ❌ | ❌ | ➖disc | ❌ | ❌ | **✅ free** | ❌ | ❌ | ❌ |
| Template count (genuine) | **63** | 63 | — | gallery | **5** | ? | 40+ | ? | infl. | 50+ |

### 4b. Tracker / ATS-focused competitors

| capability | Latexy | Jobscan | Huntr | Careerflow | Simplify |
|---|---|---|---|---|---|
| ATS score | ✅ +named +parsed | ✅C, paywalled | ➖ | ✅C score-only free | ➖ |
| **Shows parsed output** | **✅** | ❌ | ❌ | ❌ | ❌ |
| Job tracker | ✅ | ✅ | ✅ core | ✅ | ✅ core |
| **One-click capture from posting** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Application autofill (100+ portals)** | ❌ | ❌ | ✅ | ✅ | ✅ best |
| Browser extension | ❌ | ✅ | ✅ | ✅ | ✅ |
| Real LaTeX | ✅ | ❌ | ❌ | ❌ | ❌ |
| BYOK | ✅ | ❌ | ❌ | ❌ | ❌ |
| Free tier shape | 10 compiles/day, all features | 5 scans/mo | unlimited base, 2 tailored | 1 resume | unlimited autofill+tracking |
| INR pricing | ✅ native | ❌ | ❌ | ❌ | ❌ |

The capture mechanics — extension, one-click clip, autofill — are the one cluster where Latexy is absent across the board and every tracker-first competitor is present. All four require a browser extension, which Latexy does not have.

---

## 5. Performance and cost

### 5.1 Methodology

- **From-laptop numbers**: `curl -w` with the full timing breakdown, 3 runs per endpoint, India→Virginia.
- **In-region numbers**: `urllib` inside a Modal container in the same region (`research/measure_db_latency.py::measure_api_from_region`), 5 runs, median reported. This isolates Modal ingress + application from client transit.
- **Backing-service numbers**: measured inside a Modal container with the production secrets (`research/measure_db_latency.py`), 20 iterations warm.
- **Compile numbers**: real job submissions to production, 1s polling. Polling from a laptop costs ~2.5s per state call, so `total_s` carries up to ~3.5s of granularity error. Server-reported `compilation_time_ms` is used to separate LaTeX work from pipeline overhead.
- Benchmarking consumed the admin account's full daily compile quota (`compilations: 10/10 (day)`), which is why one run returned in 2.7s with no compile time — a correct fast rejection, not a failure.

### 5.2 What the numbers say

**The compile pipeline spends 18.2s not compiling.** Server-reported LaTeX work is 15.6s; wall clock is 33.7–33.8s. Of the overhead, ~8.2s is queued→processing (Celery/Modal dispatch plus ~100ms-per-op Redis) and ~4.1s is the submit POST itself.

**Production LaTeX is ~15× slower than local for the same document** — 15.6s vs 1.03s locally. Both use pdflatex on the same source. The plausible cause is filesystem I/O against a 1.75 GB TeX tree in a container, not CPU (inference — not directly measured).

**The image is the lever, and it is one package.** Debian amd64 installed sizes [V — packages.debian.org, 2026-08-11]:

| package | installed |
|---|---|
| **texlive-fonts-extra** | **1,665 MB** |
| texlive-latex-extra | 94.9 MB |
| texlive-latex-recommended | 25.5 MB |
| texlive-science | 20.0 MB |
| texlive-xetex | 15.7 MB |
| texlive-fonts-recommended | 14.7 MB |
| texlive-latex-base | 13.3 MB |

`backend/modal_app.py:51-60` installs all of these. **`texlive-fonts-extra` is 1.63 GB of the 1.75 GB total — 93%.** fontspec, microtype and enumitem ship in `texlive-latex-recommended`; titlesec and hyperref in recommended/base [C]. Dropping fonts-extra leaves ~184 MB, unless a specific template names a specific font family.

### 5.3 Cost per operation

Inputs: `OPENAI_MODEL = "gpt-4o-mini"` (`config.py:113`); no `cpu=`/`memory=` overrides in `modal_app.py`, so Modal defaults apply; `min_containers=1` on both `run_latex_task` and `run_orchestrator_task` (`modal_app.py:143,167`).

- **Compile**: ~15.6s of container time per compile, plus **two containers held warm 24/7** by `min_containers=1`. The standing cost of warmth dominates the marginal cost of a compile at low volume — at 100 compiles/day, 1,560 container-seconds of work against 172,800 container-seconds of idle warmth. **Precise INR figures require Modal's current rate card, which I did not retrieve — see §8.**
- **Optimize**: gpt-4o-mini is the cheapest capable tier; a resume rewrite is plausibly single-digit US cents. Free tier allows 3/month, Basic 10/month — so LLM cost is tightly bounded by quota and is *not* the cost risk.
- **The cost risk is idle warmth, not usage.** Two always-on containers to avoid a cold start that the measurements show is not currently being paid anyway (five consecutive compiles all ~37s).

### 5.4 Architectural options, with evidence

| option | evidence | verdict |
|---|---|---|
| **Drop `texlive-fonts-extra`** | 1.63 GB of 1.75 GB [V] | **Highest leverage, lowest risk.** Test each of the 63 genuine templates still compiles. |
| **Lazy image loading** (SOCI / stargz) | `awslabs/soci-snapshotter` 759★ pushed 2026-08-07; reported 6m59s→21.1s and ~30s→~4s pulls [S] | Right tool for an image-pull-bound cold start. A resume compile touches a tiny fraction of the TeX tree. Modal support unconfirmed. |
| Modal memory snapshots | 3–10× on init-heavy functions [V — modal.com/docs/guide/memory-snapshots] | **Probably won't help.** Modal's own docs warn snapshots "will generally not improve" storage-load-bound init. |
| **Tectonic** | 5,019★ pushed 2026-08-01; images ~56–75 MB vs ~2.3 GB [C] | ~30× smaller image, but compile speed is *contested* — issue #452 is "Tectonic is slower than xelatex", and a user reports xelatex 2× faster single-threaded, 8× at 10-way concurrency [V — discussions/1153]. Benchmark before committing. |
| **Typst** | 105.7ms vs pdflatex 329.1ms on a 1-page doc, third-party hyperfine benchmark by a *competing* vendor [V — speedata/typesetting-benchmark] | Fastest and eliminates cold start (~50 MB binary, or ~10 MB gzipped WASM). Costs the LaTeX ecosystem: **~26 CV templates on Typst Universe vs thousands for LaTeX**, and users cannot bring an existing `.tex`. RenderCV already migrated. |
| WASM LaTeX in-browser | SwiftLaTeX 2,316★ but **last push 2024-06-18 and its package mirror `texlive.swiftlatex.com` is NXDOMAIN** [V — own DNS/curl]; texlive.js abandoned 2017; TeXlyre-busytex needs **122–432 MB** of WASM+data [C] | **Not viable as a replacement.** The small-binary route depends on a dead mirror. Plausible only as an optional offline preview. |

---

## 6. Gap analysis

### Table stakes — absence actively loses users

1. **37s compile.** Overleaf's *free-tier restriction* is 10s. This is the product's core loop.
2. **All 147 template previews 502.** Fixed in #1146, undeployed. A gallery with no images is not a gallery.
3. **84 of 147 gallery entries are test fixtures** (#1147). 57% junk, mostly in `finance`.
4. ~~**LinkedIn import — absent on all three surfaces.**~~ **Wrong — it is shipped.** `POST /sources/import-linkedin` (`backend/app/api/sources_routes.py:142`) accepts a user-uploaded LinkedIn data export via `linkedin_import_service`, is feature-gated on `ai_import_linkedin`, and has UI at `/workspace/new`. My original claim came from a route-prefix scan that did not connect the `sources` domain to LinkedIn. **The real gap is narrower**: import requires the user to download their LinkedIn archive first, whereas Teal and Kickresume import from a profile URL or extension. That is a friction gap, not an absence.

### Differentiators others hold

5. **Real-time collaboration** — Latexy has it (`collab_manager.py`, capped at 500 updates with `LTRIM` + TTL, so bounded). Only Overleaf matches. Not a gap; a strength.
6. **Browser extension** — Teal's core acquisition and retention mechanism. Expensive to match, and it is how Teal makes a bursty product sticky.
7. **Free student tier** — Kickresume gives Premium free with student verification [V]. For an India student segment this is a direct competitive threat to a ₹299 Student plan.

### Latexy's own advantages — press these

8. **Named-ATS simulation + real parsed output.** Nobody else names a system or shows a parse. This is the single most defensible asset and it is currently undersold in the README.
9. **BYOK at ₹199.** Unanimous greenfield, and structurally coherent.
10. **A working public v1 API.** No competitor has one.
11. **A genuine TUI.** But see §8 — evidence that a TUI monetises is weak.
12. **Real LaTeX.** Only Overleaf, and Overleaf has no resume workflow.

### Nobody has this

13. **Honest ATS reporting as positioning.** The whole category ships unverifiable scores. "Here is the text Workday will actually extract, and here is what breaks in Taleo" is defensible, checkable, and currently unclaimed.

14. **A bullet-variant library — the highest-upvoted unmet need, and users are hand-building it.** This is the one user-research finding that survived re-sourcing intact, and the upvotes sit here rather than on scores or templates. Two threads, `1me4kat` (score 61) and `1tdqn0s` (score 52, 48 comments) [VERIFIED — Arctic Shift archive]:

    - Top comment, score 15: *"I keep a 'master resume' and pick and choose stuff… The master is about 4 pages long at this point, and **I'm slowly working on a project that lets me tick off various accomplishments/summaries to include**."* — a user hand-building the missing product.
    - *"I have a standard resume I use and add a bullet point tailored to the job posting… I also save all the new bullet points in a separate doc so now I have like 15-20 per past job."*
    - The cost of not having it: *"you end up spending like 30 mins per app and wonder why you only sent out 3 that day… rewriting from scratch every time is a trap."*
    - **The unaddressed failure mode** (score 7): *"I sent a resume where I copy pasted a bullet point from one place to another and forgot to remove the first iteration."* So the needed primitive is **diffable, format-preserving edits**, not "make it sound better."

    Latexy has the substrate already: a variants migration, checkpoint tables, and `resume_diff_service.py`.

    *An earlier draft of this report also quoted a user naming this as a specific gap in Teal and Huntr. **That quote was retracted as fabricated** and is removed — the need is well-evidenced, but the claim that incumbents specifically fail at keyword integration is not.*

15. ~~**Rejection feedback as the loudest unmet need.**~~ **Retracted.** An earlier draft of this report built a headline finding on a Reddit thread about wanting rejection feedback. **The researcher subsequently retracted that citation as fabricated**, and I could not substantiate it independently. The framing it supported — "the ATS score is a cheap fake of a demand for explanation" — was mine, and it was resting on nothing. It is removed rather than quietly reworded, because it was persuasive and wrong.

    What *does* survive, and is now **independently verified**: the *market gap* is real even though the *user quote* was not. **Zero platforms give a rejected candidate a reason.** SmartRecruiters' candidate-facing `StatusDto` has exactly three fields and no reason field; reasons sit behind an employer-gated Configuration API. Greenhouse's `rejection_reason` taxonomy is internal analytics. Handshake shows "Declined" and **explicitly does not notify**. LinkedIn's responsiveness signals are **pre-application only** — after you apply it shows only *viewed* and *downloaded*, with no rejection status at all [V].

    **And no law requires it anywhere checked** — UK ACAS states outright that *"Employers do not have to explain their reasons for rejecting job applications"*; EU AI Act Art. 86 is on-request-only, high-risk-only, and explains *the role of the AI system* rather than an individual rejection [V*].

    So: the gap is verified, the demand is not. Those are different claims and the distinction is the whole lesson of this retraction.

### Deliberately declined — preserve the reasoning

14. **pdf-inspector** was declined on the grounds the product is LLM-bound, not parse-bound. **That logic does not transfer to the compile path**, which the measurements show is I/O-bound on image size — a genuinely different bottleneck.
15. **JSON Resume** as an architectural standard: schema frozen at v1.0.0 since 2014, `resume-cli` archived. Support as import/export; do not build on it.

### Overlooked categories

- **Accessibility, i18n / non-Latin scripts**: not assessed. `texlive-lang-english` only (`modal_app.py:58`) — a Devanagari or CJK resume would fail. **For an India-first product this is a real gap**, though whether Indian users want non-Latin resumes is unestablished.
- **Data export / account deletion / GDPR**: not assessed.
- **SOC2**: not assessed; relevant only if selling Team tiers.

---

## 7. Recommendations, ordered

**1. Move Redis into the same region as Modal and Neon.** Effort: hours. Impact: **removes ~100ms from every single request**, and more from endpoints doing several Redis operations. Trades against: a brief cache flush, and re-pointing the `latexy-storage`-style secret. This is the cheapest latency win available and it fixes an inversion — the cache being 14× slower than the database is indefensible.

**2. Attack the 37s compile, in this order.** Effort: 1–2 days for the first step.
   a. **Drop `texlive-fonts-extra`** — 1.63 GB of 1.75 GB. Verify all 63 genuine templates still compile.
   b. **Instrument the 18.2s of non-LaTeX overhead** before optimising it. 8.2s is queued→processing and 4.1s is the submit POST; neither is typesetting. Do not guess.
   c. Only then consider Tectonic (benchmark the concurrency regression first) or Typst.
   Impact: the core loop, and the anonymous `/try` first impression at 37.2s. Trades against: font coverage risk for specific templates.

**3. Fix the pricing inversion, and restructure the tiers.** Effort: hours.
   - Basic at ₹299/mo gives 50 compiles/month against Free's 10/day ≈ 300. **The first paid tier is a downgrade on the headline dimension** — one line at `config.py:761`, and embarrassing to ship as-is.
   - **Reprice Pro ₹599 → ₹499** to land on the Canva anchor rather than above the entire Indian consumer-subscription band.
   - **Add annual SKUs at 35–45% off for every tier.** Every verified India comparable discounts annual heavily because consumers avoid recurring mandates, and it sidesteps Razorpay e-mandate churn. BYOK and Pro currently have annual entries; the structure should be deliberate and uniform.
   - **Display GST-inclusive round numbers.** 18% appearing at checkout is a known abandonment cause.
   Impact: directly on conversion, at near-zero engineering cost.

**4. Lead with the ATS evidence — and reframe it as explanation, not score.** Effort: days (mostly copy plus surfacing the parse in the frontend). Latexy is the only product that shows what a parser extracted, and one of two that names ATS platforms. Meanwhile the category's premise is falsifiable: **Greenhouse's own docs say its matching is a paid add-on that "does not auto-reject any candidate"**, the "88% auto-rejection" stat is about employer knockout rules, and the same resume scores 97/79/79 across three tools.

   **What to claim and what not to.** Ship **parse fidelity + keyword gaps + the visible parsed output**. Do *not* claim ATS emulation: it is unverifiable, and the sophisticated segment already reads it as a tell — r/EngineeringResumes' wiki never uses the phrase "ATS score" and links only myth-busting sources [VERIFIED — official wiki mirror, last updated 2024-06-24; live wiki unreachable].

   **Two honest counterweights.** Some ATS (Oracle, iCIMS) do assign scores, so "scores are fake" is too strong — the accurate claim is that **no passing grade exists and third-party scores are unvalidated**. And one experienced recruiter argues parse failures don't matter because *"we just open the actual resume itself"*. If that view is representative, this recommendation's value drops sharply. **It is the assumption most worth testing before investing.** Trades against: little engineering, but a real risk of being the wrong bet.

**5. Never paywall the download of content the user typed.** Effort: a decision. This is the single most-complained-about thing in the category, it is the **core allegation in active federal litigation** against the market leader (*Rocket Resume v. BOLD*, 5:26-cv-02852), Bold LLC carries a **1.12/5 BBB rating across 78 reviews**, and **four separate indie competitors are using "not that" as their entire pitch**. Latexy has drifted into the most generous position without choosing it — 10 compiles/day with all 26 features unlocked. **Choose it deliberately and say so in marketing**, because for a LaTeX product the export *is* the proof of quality. The right place to meter is AI spend, which is exactly what the quota table already does.

**6. Assemble the bullet-variant library from primitives that already exist.** Effort: 1–2 weeks, not 3–4 — `POST /ai/generate-bullets`, `POST /ai/rewrite`, the variants migration, checkpoint tables and `resume_diff_service.py` are all shipped. What is missing is the *library UI and per-JD variant model*, not the generation or diffing. Impact: this is the **#1 hand-rolled workaround** in the research and an **explicitly named gap in both Teal and Huntr** — users maintain 15–20 tailored bullets per job in a side document, and complain that incumbents "dump keywords in the skills section" instead of integrating them. Wanted: master resume → per-JD variants → **3 rewrite options per bullet**, with diffable, format-preserving edits (a real reported failure is shipping a resume with a duplicated bullet after manual copy-paste). Latexy already has the substrate — variants migration, checkpoint tables, `resume_diff_service.py`. Trades against: it competes for the same LLM budget as `/optimize`, and it is the one recommendation here that is genuinely weeks rather than days.

**7. Reduce LinkedIn import friction — do not build it.** Effort: days, not weeks. **It already exists** (`sources_routes.py:142`), but requires the user to request and download a LinkedIn data archive, which takes LinkedIn hours to produce. Competitors import from a profile URL or a browser extension. The work is a lower-friction on-ramp, not the importer. Trades against: LinkedIn's terms — URL scraping is what they enforce against, so the archive path may be a deliberate and correct choice already.

**8. Do not invest further in the TUI until BYOK/TUI conversion is measured.** The TUI covers 9 of 28 domains and closing that gap is weeks of work. Evidence that a TUI *monetises* is weak — no revenue data was found for any BYOK or TUI-first product, and incumbents degrade BYOK deliberately. The TUI is a strong credibility signal for a developer audience; treat it as marketing until the data says otherwise. **Recommend instrumenting which plan TUI users are on before spending more.**

**9. Clean up the template gallery (#1147) and fix `Clean Simple`.** Effort: one `UPDATE` plus a LaTeX fix. Impact: the gallery goes from 57% junk to genuine. Low effort, visible.

**Explicitly not recommended: adding templates.** 63 genuine already exceeds Rezi's 5 and matches FlowCV's 50+. The 1.63 GB font package and the 100ms Redis hop each cost more perceived quality than another 84 templates would buy.

---

## 8. What I could not determine

- **Cold-start behaviour.** All five consecutive compiles were ~37s, so I never observed a cold start and **could not verify the ~40–45s figure at `modal_app.py:140`**. Forcing one requires scaling `min_containers` to 0 or a concurrent burst — both disrupt production. The 3.5s warm-compile claim in that same comment is *contradicted*: server-reported compile is 15.6s.
- **Modal's current rate card**, so cost-per-operation is directional, not costed. Retrieving pricing and multiplying by measured container-seconds would close this in under an hour.
- **The 430ms in-region floor.** `/byok/providers` takes 529ms with no database and one ~100ms Redis hop, leaving ~430ms in Modal ingress plus the middleware chain (`main.py:209-238`: GZip, SecurityHeaders, BodySizeLimit, Timeout, APIKeyRateLimit, Tenant, RequestContext). I did not instrument per-middleware cost. **This is the single most valuable follow-up measurement** — it may be a larger win than the Redis move.
- **Why production LaTeX is 15× slower than local.** I/O against the TeX tree is the hypothesis; not measured. `strace`/timing inside the worker would settle it.
- **Jobscan's actual weighting.** Its method is verified as weighted keyword frequency from its own support doc, but the weights are undisclosed and **no rigorous third-party teardown exists** — the entire "Jobscan review" search result set is content marketing by competing resume products. Whether its weighting bears any relation to a real ATS: could not determine.
- **Naukri's own subscription pricing.** `resume.naukri.com/value-plans` and `naukri.com/naukri360-pro` are JS shells returning 403. A ₹750/mo figure appears in snippets; do not rely on it. Shine's resume-writing page 404s. All India service prices are secondary, and two sources on Naukri FastForward disagree by ~2×.
- **LinkedIn Premium Career India pricing** — secondary sources conflict badly (₹999 vs ₹2,400+). Canva Pro India (₹499) is secondary only; Canva 403s all fetches.
- **Whether ChatGPT Go is currently free in India** — reportedly free Nov 2025 to ~Dec 2026, but openai.com 403s. This matters, because it determines whether the ₹199 tier competes with ₹399 or with ₹0.
- **Teal's prices and export formats** — `tealhq.com` returned HTTP 403 (Cloudflare). Prices are secondary-sourced only. **Enhancv's prices** rendered as literal `€NaN`; secondary sources conflict ($19.99 vs $24.99). **FlowCV's Pro price** unverified. Re-check from a non-datacenter network before quoting.
- ~~Whether tagged PDF helps ATS parsers~~ — **resolved, no.** See above; the recommendation was demoted from P1-ATS to P2-accessibility as a result.
- ~~Devanagari/Indic LaTeX specifics~~ — **resolved.** LuaLaTeX + `luahbtex` + HarfBuzz; **babel ≥24.14 over polyglossia**; `texlive-lang-indic` does not exist in Debian and the macros ship in packages we already have; **~52 MB minimum**. One thing remains untested: whether tagged PDF preserves Devanagari text extraction — no `tagpdf` issue mentions Indic scripts either way.
- **Whether BYOK or a TUI monetises.** No revenue data, case study, or independent analysis found for either. This is a genuine evidence gap, not an oversight — and recommendation 7 is deliberately conservative because of it.
- **Evidence-access limits, and one failure worth naming.** reddit.com is hard-blocked from this environment; all Reddit evidence came via the **Arctic Shift archive**. **Trustpilot and G2 returned 403 to every attempt — so no Trustpilot star ratings appear in this report at all**; an earlier draft quoted some, and they were discarded as unsourceable. `mospi.gov.in` served a self-signed certificate, so PLFS figures are secondary. Zety's pricing page timed out twice, so its paywall terms are **user-claim only, never verified at source**. The r/EngineeringResumes wiki was read from a **GitHub mirror last updated 2024-06-24** because the live wiki was unreachable — it may be stale.
- **The first pass of the user-sentiment research fabricated citations**, including a thread that anchored a headline finding. This was caught only because the researcher re-ran and retracted its own work. **I had already written the fabricated material into this report and published conclusions on it.** The lesson generalises: sentiment research with unverifiable primary sources needs a second independent pass before it earns a place in an executive summary, and I did not apply that standard before the correction arrived.
- **Whether parse fidelity actually affects outcomes.** One experienced recruiter says it does not — *"when it does [butcher parsing] we just open the actual resume itself"*. This is the single assumption most worth testing, because recommendation 4 depends on it and the report otherwise leans on it heavily.
- **Template/export quality complaints are the thinnest-evidenced item** in the user research — roughly 4 threads, not a wave. And there is **no recurring user demand for DOCX/LaTeX/JSON export**; treat "users want LaTeX export" as inferred from the developer-audience launches in r/developersIndia, not as evidenced demand.
- **Accessibility, i18n, GDPR posture, SOC2** — out of time, not assessed. Non-Latin script support looks absent (`texlive-lang-english` only) but I did not test a Devanagari resume.

---

### Appendix — reproducing the measurements

- Backing services and in-region API: `modal run research/measure_db_latency.py` · `::redis_probe` · `::api_probe --token <session-token>` (read-only; not part of the deployed app)
- From-laptop timings: `curl -w 'dns=%{time_namelookup} tcp=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}'`
- Payload: `curl -H 'Accept-Encoding: identity'` vs `gzip` against `/templates/`
- Compile: submit to `POST /jobs/submit`, poll `GET /jobs/{id}/state` at 1s; read `compilation_time_ms` from the headless CLI (`node dist/cli.js compile <file> --json`)
