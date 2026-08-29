# Latexy — Feature Catalog

> **Purpose.** The complete inventory: what Latexy already ships, what every competitor ships, and what nobody ships. Priority-ordered, but **exhaustive** — features are listed even where the recommendation is *don't build this*, because knowing a competitor has it is the point.
>
> **Supersedes** the previous version of this file, archived intact at **`docs/FEATURES-2026-07-legacy.md`** — its per-feature "What to build" prose remains useful for unshipped items even though its status claims are void. That version (92 entries, no status tracking) had gone materially stale — its first entry read *"Latexy currently ships with exactly 2 resume templates"* against **63 genuine templates** in production today, and it listed Zotero, Dropbox, GitHub, the job tracker and cover letters as work to do when all five are shipped. Every entry below carries a verified status.
>
> **Companion document:** `research/COMPETITIVE-ANALYSIS.md` — pricing, positioning, performance measurements and the strategic argument. This file is the feature inventory; that one is the reasoning.

**Last full catalog verification:** 2026-08-12 · against `main` @ `d76f8765`

**P0 delivery reconciliation:** 2026-08-28

> This is a point-in-time research catalog, not the live issue board. Linked GitHub issues are
> authoritative for delivery state after the dates above. The P0 items below were reconciled on
> 2026-08-28; later sections retain their original research snapshot unless explicitly noted.

> **Revision note (2026-08-12) — this file was audited against the legacy catalog and corrected.** A line-by-line reconciliation of all **92** legacy entries (Part F) found that this catalog, while accurate about competitors, **under-counted Latexy's own shipped features**: **19 of 92** legacy entries are shipped in the codebase yet were absent from or misdescribed in Part C — including the resume heatmap, the LaTeX package-manager UI, the TikZ editor, industry-specific ATS calibration, keyword density, and **Canva/Figma export**. That is the same class of staleness this file criticises the legacy version for, inverted. All 19 are now corrected and Part F records the full mapping so the claim is checkable.
>
> **Companion, not competitor:** `docs/qa/ux-improvements.md` (on `main`, 126 findings) is a **UX-defect** backlog — broken affordances, missing confirmations, accessibility failures in shipped surfaces. This file is a **feature** inventory. They deliberately do not overlap: if a surface exists but behaves badly it belongs there; if it does not exist it belongs here. Three genuine cross-references are noted inline.

> **Sourcing note.** Competitor detail comes from parallel research streams, each marked [V]/[C]/[S] inline. The Zety and LiveCareer inventory was contributed by a peer session and is retained with its own caveats — both brands hard-block direct fetching, so it was obtained via a text-extraction proxy, and LiveCareer's US site WAF-403s every interior path (detail is reconstructed from `livecareer.co.uk`). It also **corrected an error in `research/COMPETITIVE-ANALYSIS.md`**: Resume Genius is **not** a Bold brand (it is Sonaga Tech Ltd, Switzerland).

---

## Legend

| Mark | Meaning |
|---|---|
| **P0** | Ship immediately — blocks conversion, retention, or credibility |
| **P1** | High value — next 3–9 months |
| **P2** | Medium value — 9–18 months |
| **P3** | Future / speculative — 18+ months |
| **P4** | **Listed for completeness; recommendation is do not build.** Reason given. |
| **S / M / L / XL** | < 1 week / 1–3 weeks / 1–2 months / 3+ months |
| ✅ | **Shipped** — verified by route, component or dependency |
| ➖ | **Partial** — exists but incomplete, or backend-only with no UI |
| ❌ | **Absent** |
| **[V]** | Verified on the vendor's own site/docs/repo |
| **[C]** | Vendor claim, not independently confirmed |
| **[S]** | Secondary source |

**Status is evidence-based.** Every ✅ traces to a route path in `backend/app/api/*.py`, a file in `frontend/src`, or a package dependency. Where I could not verify, it says so — this file has no aspirational ticks.

---

## Table of contents

- [Part A — What Latexy already ships](#part-a--what-latexy-already-ships)
- [Part B — Priority backlog](#part-b--priority-backlog)
- [Part C — Exhaustive master feature list](#part-c--exhaustive-master-feature-list)
- [Part D — Deliberately not recommended](#part-d--deliberately-not-recommended)
- [Part E — Open research](#part-e--open-research)
- [Part F — Legacy catalog reconciliation](#part-f--legacy-catalog-reconciliation) — all 92 legacy entries mapped

---

# Part A — What Latexy already ships

**Ground truth:** 290 backend routes across 48 path domains (`backend/app/api/*.py`, aggregated in `routes.py:43-213`, mounted at `main.py:253`), 38 frontend pages, 33 TUI commands.

This section exists because the previous catalog, this report's own first draft, and the README all **understated** what is built. Two corrections were made to `COMPETITIVE-ANALYSIS.md` on the strength of it.

## A1. Capabilities that are stronger than any competitor's

| capability | evidence | why it matters |
|---|---|---|
| **Direct ATS submission** | `POST /apply/greenhouse`, `/apply/lever`, `/apply/detect`, `+/preview`, `GET /apply/submissions` (`application_routes.py`) | Of every competitor surveyed only Simplify does *autofill* — typing into a form. Latexy submits via API. **Nobody else does this.** |
| **Named-ATS simulation** | `ats_simulator_service.py:29-63` — Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Taleo, iCIMS, each with failure modes; `ats_routes.py:1105` | No competitor names a single ATS *and* shows a parse. |
| **Real parsed-output view** | `pdf_parser.py:25-54` (pdfplumber), `pdf_layout.py` | **Zero** competitors show what a parser extracted. |
| **BYOK** | `/byok` (12 routes), ₹199 tier | Zero of 7 builders offer BYOK at any tier. |
| **Public developer API** | `/api` v1 (5 routes: compile, optimize, ats/score, jobs/:id, jobs/:id/pdf), `/developer` (5), `developer_api_keys` table, `APIKeyRateLimitMiddleware` | No competitor has a public API. |
| **Terminal UI** | 33 commands, `packages/tui` | No competitor has one. |
| **Real LaTeX** | whole product | Only Overleaf, which has no resume workflow. |
| **Real-time collaboration** | `yjs ^13.6.31`, `collab_manager.py`, `CollaboratorPanel.tsx`, `/resumes/:id/comments` + `/resolve` | Only Overleaf matches. No resume builder does. |

## A2. Shipped, by domain

**Resume core (49 routes)** — CRUD, `/fork`, `/variants`, `/merge`, `/diff-with-parent`, `/checkpoints` (+`/content`, delete), `/restore-optimization/:id`, `/optimization-history`, `/score-history`, `/error-history`, `/pin`+`/unpin`, `/archive`+`/unarchive`, `/tags`, `/search`, `/settings`, `/stats`, `/analytics`, `/share`, `/export/bulk`, `/quick-tailor`, `/academic-cv-convert`, `/academic-cv-report`, `/generate-portfolio`, `/generate-references`, `/builder` + `/builder/templates` + `/builder/seed-upload`, `/collaborators`, `/comments`

**AI (15 routes)** — `generate-bullets`, `rewrite`, `generate-summary`, `generate-publications`, `proofread`, `spell-check`, `explain-error`, `translate`, `salary-estimate`, `reorder-sections`, `standardize-dates`, `format-contacts`, `age-analysis`, `confidence-score`, `personas`

**ATS (13)** · **Templates (11)** · **Export (5) + Formats (6)** · **Cover letters (7)** · **Interview prep (3)** · **Optimize (3)** · **Tracker (7)** · **Apply (7)** · **Analytics (11)** · **BYOK (12)** · **Jobs (11)** · **Workspaces (15) + Teams (4) + Tenants (9)** · **GitHub (11) · Dropbox (9) · Zotero (7) · Mendeley (5)** · **Portfolio (5)** incl. custom-domain verify · **Career (4)** · **References (3)** incl. `fetch-orcid` · **Snippets · Macros · Admin (7) · Settings · Telemetry · Sources (2)** incl. `import-linkedin`

**Frontend (38 pages)** — incl. `/try` anonymous, `/workspace/builder/*` WYSIWYG, `/workspace/[id]/batch-tailor`, `/career`, `/cover-letter`, `/optimize`, `/merge`, `/history`, `/workspaces/[id]/recruiter`, `/u/[username]` portfolio, `/r/[token]` share, `/developer`, `/byok`, `/tracker`, `/templates`, `/admin/tenant`

**Editor** — LaTeX linter (`LinterPanel.tsx`), LanguageTool spell/grammar (`ai_routes.py:693`), SyncTeX (13 refs in `routes.py`), multi-compiler (pdflatex/xelatex/lualatex), share tokens, QR insertion (`QrCodeInserter.tsx`), contact formatter

## A2b. Shipped but previously undocumented — found by the legacy reconciliation

These were built, are in the codebase today, and were **missing from this catalog's earlier revision**. Each traces to a route or component. This is the corrective half of the audit in Part F.

| feature | evidence | legacy ref |
|---|---|---|
| **Canva / Figma export** | `GET /export/{id}/canva`, `/export/{id}/figma` (`export_routes.py:115,148`) → `CanvaResumeExport`, `FigmaResumeExport` | 5.20 |
| **Resume heatmap** (recruiter attention prediction) | `frontend/src/lib/heatmap-generator.ts` — rule-based, from published eye-tracking research; surfaced in `PDFPreview.tsx` | 3.12 |
| **LaTeX package-manager UI** | `PackageManagerPanel.tsx` — `getInstalledPackages`, `addPackageToPreamble`, `removePackageFromPreamble` | 4.1 |
| **TikZ / diagram editor** | `TikZEditor.tsx`, wired into `LaTeXEditor.tsx` | 4.9 |
| **Print-preview mode** | `lib/print-preview.ts` + `printPreview` state in `PDFPreview.tsx`, with colour-dependency analysis | 5.19 |
| **Industry-specific ATS calibration** | `services/industry_ats_profiles.py` — `INDUSTRY_PROFILES`, `detect_industry`; `industry_override` on the scoring request | 2.12 |
| **Keyword-density map** | `POST /ats/keyword-density` (`ats_routes.py:1194`), anonymous-capable; UI on `/optimize` | 3.15 |
| **BibTeX smart import from DOI / arXiv** | `reference_service.fetch_doi`, `fetch_arxiv` (`reference_routes.py:90-93`) | 1.9 |
| **Font & colour visual editor** | `DesignPanel.tsx` | 3.3 |
| **Template customizer** | `TemplateCustomizerPanel.tsx` | 4.11 |
| **Keyboard-shortcuts reference panel** | `KeyboardShortcutsPanel.tsx` | 4.6 |
| **Reference-page generator** | `POST /resumes/{id}/generate-references` + `GenerateReferencesModal.tsx` | 5.8 |
| **Resume freshness tracking** | `freshness_status` computed property (`resume_routes.py:126`), typed `'fresh' \| 'stale' \| 'very_stale'` | 2.14 |
| **Compile queue priority by plan** | `get_task_priority()` in `celery_app`, used by `converter_worker.py:195` | 5.10 |
| **Score history / error history** | `GET /resumes/{id}/score-history`, `/error-history` | 3.13, 5.18 |
| **Project-level tags** | `/resumes/{id}/tags` | 1.14 |
| **Before/after optimization comparison** | `VersionHistoryPanel.tsx` + `/diff-with-parent` | 3.11 |
| **Email notifications** | Resend/SMTP delivery for completion, terminal failure, debounced share views, and weekly digests; per-trigger `GET`/`PUT /settings/notifications` preferences | 2.8 — ✅ |
| **Browser push notifications** | `usePushNotifications` hook with a real `Notification.requestPermission()` path; wired into `settings/page.tsx:247`, the editor and `/optimize` | 4.13 — ✅ |

**Email notification status (corrected 2026-08-30):** the former B29 stub is no longer present. Transactional delivery uses Resend or SMTP, Modal defines production task entry points for every trigger, terminal failures are Redis-deduplicated, share views reuse the analytics debounce, and the weekly digest has a production Modal schedule. Delivery remains operator-gated by `EMAIL_ENABLED` and provider credentials.

**Corrected 2026-08-12 after re-verifying against `main`:** an earlier revision of this file recorded **browser push (4.13)** as partial — a toggle that never requested permission. That was true at `308b7513`; it is **no longer true.** `settings/page.tsx:247` now calls `Notification.requestPermission()`, handles the `denied` state, and refuses to persist the preference ON when permission is not granted. Issue **#1213** described code that had since been fixed; it was verified and closed on 2026-08-13, along with 20 others found by the same sweep.

## A3. Built but inert — decide or delete

| thing | evidence | assessment |
|---|---|---|
| **`plan_features` gates nothing** | 26 features × 5 families = 130 rows, **all `enabled = true`** in production, including `free` | Feature gating is fully built and switched off. Monetisation is quota-only. **This is a pricing decision waiting to be made, not a feature to build.** |
| `feature_flags` | 32 rows, **0 disabled** in production | Machinery works; nothing uses it to differentiate. |
| `activeModel` / `activeProvider` | declared in `packages/tui/src/lib/config.ts`, never read or written | `/model` lists providers but persists no choice. Dead config. |
| Template `is_premium` | **no such column** in `resume_templates` | Premium templates are not modelled at all. |

---

# Part B — Priority backlog

> **Every item below is tracked as an individual GitHub issue** (linked in each heading or row). Filed 2026-08-12: **#1281–#1411 (131 issues)**, plus **#1147** for B4 which already existed.
>
> **No grouped items remain.** The 15 issues that originally bundled multiple features — B18, B19, B28, B33, B37, B45, B46, B48, B49, B50, B51, B53, B54, B56, B57 — were split into **63 individual issues** and converted into epics that link their children. Every feature in this catalog is now one issue.
>
> **Part D is deliberately not fully filed.** 24 of its 29 rows are decisions *not* to build and correctly have no issue; the **5 rows that hide real engineering or verification work** are filed as **D1–D5 (#1407–#1411)**. The two bundles — **B18** (#1302, 7 items) and **B19** (#1303, 15 items) — carry GitHub task-list checklists rather than 22 separate micro-issues, since each sub-item is under a week; say the word and they can be split out.
>
> **The accounting closes.** Part C lists **117 absent features**. Every one now resolves to a backlog item above (**86 items**, counting bundle sub-items) or to an **explicit refusal with a reason** in Part D (**29 rows**). An earlier revision of this file tracked only 29 items against those 117 absences, which left several legacy **P0** features — real-time ATS scoring, page-count warning, email delivery — with no owner at all.
>
> **Not double-filed:** issues **#1157–#1280** are the UX-defect audit from `docs/qa/ux-improvements.md` and deliberately do not overlap this backlog. Three genuine intersections are cross-referenced in the relevant items (#1245, #1247, #1213).


## P0 — ships now

### B1. Compile latency: 37s → target < 10s · **L** · status ✅ · [#1281](https://github.com/sanskarpan/Latexy/issues/1281)
The original audit measured a **37.23s** median. After the Modal image reduction and timing instrumentation, production verification on 2026-08-24 measured a **5.47s median** through the async job path; the issue is closed. Cold-start reduction remains separate follow-up work rather than part of this warm-path target.

Original ordered sub-tasks (retained for decision provenance; items 1–2 are complete and 3–4 were
deferred after the target was met):

1. **Drop `texlive-fonts-extra`** — **1,665 MB of the 1,750 MB** install (95%); fontspec/microtype/enumitem live in `texlive-latex-recommended` [V — packages.debian.org]. **S**
2. Instrument the 18.2s of non-LaTeX overhead before optimising it (8.2s queued→processing, 4.1s submit POST). **S**
3. Evaluate lazy image loading (SOCI / stargz — reported 6m59s→21.1s pulls [S]) over Modal memory snapshots, which Modal's own docs say *won't* help storage-bound init [V]. **M**
4. Only then consider Tectonic or Typst. **Typst now carries an India-specific caveat**: open bugs #8062 (*"Hyphenation skips words containing Virama and combining marks, breaking Indic script support"*) and #6339 (*"Poor paragraphs… with Indic scripts"*) [V] — a Typst pivot would forfeit B10. Tectonic (images ~56–75 MB vs ~2.3 GB [C], but compile speed is *contested* — a user reports xelatex 2× faster single-threaded, 8× at 10-way concurrency [V — tectonic#1153]) or Typst (105.7ms vs pdflatex 329.1ms, third-party hyperfine [V]). **L**

### B2. Colocate Redis · **S** · status ✅ · [#1282](https://github.com/sanskarpan/Latexy/issues/1282)
Redis was migrated from the Asia endpoint to Upstash AWS `us-east-1`, colocated with Modal and Neon. Production verification on 2026-08-24 measured a **3.9ms median** `INCR` round trip, down from 99.3ms; the issue is closed.

### B3. Fix the pricing inversion · **S** · status ✅ · [#1283](https://github.com/sanskarpan/Latexy/issues/1283)
Basic now enforces and advertises **400 compiles/month**, above Free's worst-case monthly equivalent. The fix and regression coverage shipped through PR #1549; the issue is closed.

### B4. Template gallery cleanup · **S** · status ✅ · [#1147](https://github.com/sanskarpan/Latexy/issues/1147)
The 84 test fixtures are no longer active, and `Clean Simple` compiles successfully with working PNG/PDF assets after the direct `cm-super` dependency fix. The source-owned catalog now contains 56 templates (51 résumé/academic templates plus five Beamer presentations); #1687 added automatic production synchronization and asset backfill so the source inventory cannot silently drift from the live gallery again.

### B5. Deploy the storage fix · **S** · status ✅ · [#1284](https://github.com/sanskarpan/Latexy/issues/1284)
The R2 wiring from PR #1146 is deployed. Production verification on 2026-08-24 confirmed thumbnail and preview-PDF redirects resolve to real R2 assets with HTTP 200; the issue is closed.

### B6. Annual SKUs + GST-inclusive display · **S** · status ✅ · [#1285](https://github.com/sanskarpan/Latexy/issues/1285)
Basic, Pro, and BYOK annual SKUs now carry a 20% discount, checkout validates configured Razorpay annual plan IDs, and the billing UI identifies prices as GST-inclusive. The work shipped through PR #1549; the issue is closed.

## P1 — next

### B7. Bullet-variant library with diff view · **M** · status ➖ · [#1286](https://github.com/sanskarpan/Latexy/issues/1286)
**The highest-upvoted unmet need in the user research**, and users hand-build it: *"I keep a 'master resume' and pick and choose… I'm slowly working on a project that lets me tick off various accomplishments"* [V]. The named failure mode is shipping a duplicated bullet after manual copy-paste [V]. Wants **3 rewrite options per bullet** and format-preserving, reviewable edits.

**Most of this exists**: `POST /ai/generate-bullets`, `POST /ai/rewrite`, `/resumes/:id/variants`, `/checkpoints`, `resume_diff_service.py`, `/diff-with-parent`. Missing: the library UI and the per-JD variant model. **Also note: no surveyed product exposes resume-version diffing as a user-facing feature** — Latexy already has the engine.

### B8. Lower-friction LinkedIn on-ramp · **S** · status ➖ · [#1287](https://github.com/sanskarpan/Latexy/issues/1287)
`POST /sources/import-linkedin` **exists** (`sources_routes.py:142`, feature-gated on `ai_import_linkedin`, UI at `/workspace/new`) but requires the user to request and download a LinkedIn archive, which LinkedIn takes hours to produce. Teal and Kickresume import from a URL or extension. **The work is the on-ramp, not the importer.** **The archive path is not a shortcut — it is the only compliant route that exists.** LinkedIn's *entire* self-serve API surface is three permissions: `profile` (name, headline, photo), `email` via Sign in with LinkedIn (OIDC), and `w_member_social`. Its own docs state *"Open Permissions are the only permissions available to all developers without special approval"* — **no jobs, no search, no connections, no full-profile read, at any tier**, and Compliance APIs are formally closed and *"may not be requested"* [V]. Anything marketed as a "LinkedIn Job Search API" is third-party scraping.

So B8 is strictly a UX problem: make the archive request → upload flow as painless as possible (clear instructions, resumable upload, partial import while the archive is pending). **Do not attempt profile-URL import** — Teal and Kickresume achieve it via browser extension, i.e. the user's own authenticated session, which is a different mechanism and a different risk profile.

### B9. Tagged / accessible PDF (PDF/UA-2) · **M** · status ❌ · **nobody has this** · [#1288](https://github.com/sanskarpan/Latexy/issues/1288)
LaTeX ships this now: one line before `\documentclass` —
```latex
\DocumentMetadata{tagging=on, tagging-setup={math/setup=mathml-SE},
                  pdfstandard=ua-2, lang=en-US}
```
`tagpdf` **v1.0d**, part of the kernel effort; **LuaLaTeX preferred, pdfLaTeX limited, XeLaTeX unsupported**; requires TeX Live 2025+ [V]. Auto-tags headings, lists, tables, figures with alt text, math via MathML. **Overleaf shipped it 2026-01-29** [V]; **Typst has it on by default since 0.14** [V].

**No resume product anywhere ships accessible resume PDFs** [V by absence across the whole survey]. Validators are free and open: **veraPDF** (UA-1 + UA-2), ngPDF, `showtags`. The LaTeX project maintains a **CI-tested tagging-compatibility matrix for 1,000+ packages** with 474 open issues naming exactly what breaks [V] — the practical prerequisite.

**RESOLVED — the ATS case is dead. Ship it as accessibility or not at all.**

*Every* documented extraction pipeline reads a flat text layer, geometrically or in content-stream order:

| extractor | uses structure tags? | evidence |
|---|---|---|
| `pdftotext` (poppler 26.04.0) | **No — no such option exists** (`-layout`, `-raw`, `-bbox` are all geometric) | measured locally |
| pdfplumber 0.11.x `extract_text()` | **No** — `structure_tree` is a separate opt-in API; `utils/text.py` has zero structure references | measured locally + [V] docs |
| pypdf | **No.** Its docs: PDF *"was not created for parsing the content… there is no information what the header, footer, page numbers, tables, and paragraphs are"* | [V] |
| Tika / PDFBox | **Opt-in, `default false`, "alpha" since 1.24** (`extractMarkedContent`) | [V] source |
| Docling (IBM) | **No** — tagged-PDF issue closed and labelled `ice-box` | [V] |
| opendataloader-pdf | **Yes** — the single counterexample; tag-aware is its primary path | [V] |

**pdfplumber's own maintainers state the reason** [V]: these standards are *"optional and variably implemented… frequently not enabled by default, **it is not possible to rely on them**."* Quantified: a 2024 study of 20,000 scholarly PDFs found **<3.2%** met all six accessibility criteria and **74.9% met none** [V — arXiv:2410.03022]. Tags are too rare in the wild for any extractor to depend on — a self-reinforcing loop.

**Commercial resume parsers: no vendor mentions tags anywhere.** Affinda extracts the text layer then OCRs, and its "Always Full" OCR mode **discards the text layer entirely** — tagging is provably irrelevant in that path [V]. Textkernel's document-conversion warnings (*garbage characters, unusual word lengths, truncation, reversed text*) are exactly the heuristics you build when consuming a raw text layer, not a structure tree [V].

**ATS vendors publish nothing about uploaded-file structure.** Greenhouse and Workday give *visual layout* advice only — Workday verbatim: *"use resumes that don't have images or image-based styles"* [V]. iCIMS and Workday publish WCAG/508 commitments but **explicitly scope them to their own web apps**, not the uploaded file [V].

**No compliance driver exists.** Section 508's scope is ICT agencies *procure or communicate outward*, not what the public submits [V]. The EAA's product list excludes recruitment software [V]. EN 301 549 clause 10 covers non-web documents but **has no independent legal force** [V]. No employer, university or tender requiring accessible applicant resumes was found.

**Neither Overleaf nor the LaTeX Project claims an extraction benefit** — Overleaf's 2026-01-29 announcement is framed strictly as accessibility and compliance [V].

**The strongest counter-evidence is the most telling.** The NRTC at Mississippi State studied 99 blind and low-vision job seekers' resumes (2025). ATS read **84%** of content correctly — **88%** for chronological/combination formats vs **55%** for functional; 74% had layout issues. Its accessibility recommendation verbatim: *"Avoid tables, columns, and text boxes—simple formatting usually works best for ATS **and screen readers**."* **A blindness research centre writing resume guidance for blind job seekers does not mention tagged PDF once** [V].

**Revised recommendation:** ship it as a **P2 accessibility/differentiation** item, not P1, and never as an ATS claim. It is one `\DocumentMetadata` line, it makes Latexy first in the category, and it is a cheap option on a future where tag-aware pipelines (opendataloader-pdf, Tika's marked-content mode) reach ATS vendors. Do not sell an option as a present-day benefit.

### B9b. Layout-based ATS safety — the lever that actually works · **S** · status ✅➖ · **now the strongest evidence in this file** · [#1289](https://github.com/sanskarpan/Latexy/issues/1289)

**Textkernel publishes a machine-readable table of what breaks resume parsing** [V — `developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/`]. It is a major parser vendor specifying, in its own words, exactly what to avoid. Selected codes by severity:

| code | severity | what it says |
|---|---|---|
| **433** | Fatal | columnar data is *"a **HUGE MISTAKE** for candidates… rather than a simple top-to-bottom, all-across-the-page format"* (their capitals) |
| **418** | Fatal | *"Dates ranges were found written vertically on multiple lines"* |
| 412–414 | Fatal | no sections found / no WORK HISTORY / no EDUCATION section |
| 441 | Fatal | neither email nor phone found |
| 417 | Fatal | CV-style documents parse **only the first work-history section** |
| **300** | **Major** | **"Indicates that the document was PDF."** |
| 311 | Major | contact info not at the top |
| 325 | Major | a section with no header |
| 224/225 | Data | job without a start / end date |
| **112** | Suggested | a *separate* skills section — they want skills **in the context of work history** |
| 151 | Suggested | *"Every section should have a clear, unambiguous, commonly-used header on a separate line directly above the content."* |

Plus text-layer failure signatures from their conversion codes: `ovIsImage`, `ovProbableGarbageInText` (≥5% symbol characters), `ovMayContainSomeReversedText`, `ovTooFewLineBreaks`, `ovAvgWordLengthLessThan4`, `ovTruncated` [V]. Affinda's threshold is precise and testable: **OCR fires when fewer than 25 words are found in the text layer** [V].

**Latexy already detects the layout half of this** — `ats_simulator_service.py` flags `multi_column`, `tables`, `decorative_elements`, `custom_sections` per named ATS. Codes 418 (vertical dates), 311 (contact position), 325/151 (headers) and 112 (skills placement) are **not yet checked and are cheap to add**.

**One caution that shapes presentation, from Textkernel itself** [V]: do not surface these crudely to candidates — *"unless you have a very sophisticated workflow and step-by-step improvement process… you will frustrate candidates and do more harm than good."* Ship them as ranked, actionable fixes, not a wall of error codes.

**Uncomfortable finding, stated plainly: Textkernel classifies "the document was PDF" as a Major issue (code 300), with no equivalent code for Word** [V]. For a LaTeX product whose output *is* PDF, that deserves an honest response rather than omission — the answer is that Latexy also exports DOCX (`/formats`, 6 routes), and that a well-formed PDF text layer is what actually matters, which leads to the next point.

### B9c. Verify and advertise the extraction contract · **S** · status ✅ · **measured** · [#1290](https://github.com/sanskarpan/Latexy/issues/1290)
The concrete thing separating a good PDF from a bad one is whether fonts are embedded **with a ToUnicode CMap**. Without it a viewer can draw a selection box while extraction returns garbage — the reported Figma failure mode.

**Measured on a real production template** (`Phd Applicant`, 119 KB), 2026-08-11:

```
pdffonts  → 6 fonts, all  emb=yes  sub=yes  uni=yes      ← ToUnicode present on every font
pdftotext → 314 words extracted (Affinda OCRs below 25)
            avg word length 6.5 (flag fires <4)
            extraction is correct and in reading order:
            "Ravi Mehta" / "Bangalore, India" / "ravi.mehta@gmail.com" / "+91 98765 43210"
```

**Latexy's output satisfies the contract.** That is a checkable, demonstrable claim — and unlike an ATS score, a user can verify it themselves. This is the honest version of "ATS-friendly."

**The competitive angle, and a claim to NOT make yet.** "Canva resumes fail ATS" is folklore — **no primary or secondary report was found attributing Canva failures to unextractable text** [V, searched]. What is documented is narrower and more useful:

- **Canva's default export appears to keep a real text layer.** The documented hazard is a separate **"Flatten PDF" checkbox**, offered on both PDF Standard and PDF Print, which Canva's own help says *"converts the file into a static image"* and *"merges all design elements into a single image"* [V]. A flattened resume has no text layer and would hit Textkernel's `ovIsImage` / Affinda's sub-25-word OCR path. Whether it is ever default-on: could not determine.
- **Figma is where the real evidence is, and its docs contradict its users.** Figma states *"exports text as glyphs… You can still select and copy text"* [V, updated 2026-08-02], but five years of forum reports say text is outlined, including one explicitly about our use case: *"people using Figma to build resumes… might not be readable by ATS software… Select text and copy. Paste in notepad: crazy non-text data was copied"* [S]. The likely mechanism — **glyph-ID-addressed subset fonts with no usable ToUnicode CMap** — is a hypothesis, not verified.
- **Adobe Express has an explicit "Add accessibility tags" checkbox** on download [V] — the only design tool found offering it.

**Do not publish a comparative claim until we run the matrix ourselves**: export one identical resume from Canva (Standard, Standard+Flatten, Print), Figma and Express (±tags), then run `pdffonts` and `pdftotext` on each. That converts the whole question from folklore to a table we can show. It needs accounts we do not have.

*One thing to investigate, not yet a defect:* my crude symbol-ratio calculation gave **6.7%**, above the 5% threshold Textkernel documents for `ovProbableGarbageInText`. My counting method almost certainly differs from theirs (I counted all non-alphanumerics, including the `@`, `+` and `.` that any resume legitimately contains). But the template's `\quad|\quad` separators do surface as **leading `|` characters on contact lines**, which is worth checking against contact-block parsing given code 311. Verify before treating as either safe or broken.

### B10. Devanagari / Indic script resumes · **M** · status ❌ · **nobody has this** · [#1291](https://github.com/sanskarpan/Latexy/issues/1291)
`modal_app.py:58` installs `texlive-lang-english` only, so a Hindi/Marathi/Tamil resume cannot compile today. **No resume product supports Indic scripts as a documented feature, and no Devanagari CV template exists in LaTeX or Typst** [V].

**A nine-product sweep of the mid-tier long tail sharpens this rather than overturning it** [V]. Only **two of nine** support non-Latin script at all: Reactive Resume (56 UI locales, 22 non-Latin, real RTL plumbing) and **Resume.io**, which is the one genuine competitor here — it supports Japanese kana/kanji, Greek, Russian/Bulgarian/Serbian Cyrillic and **Hindi (Devanagari)**, across 27 locale-native brand domains. Every other product is Latin-only: Kickresume 6 locales all Latin and **explicitly scoped to "any left-to-right language" — RTL out of scope**; Novoresume 5, all Latin; Enhancv 13, all Latin, and notably **no Bulgarian despite being a Bulgarian company**; Teal English-only, stating *"We do not have the capability to change language features just yet."*

Two qualifications, so this is not overstated: Resume.io's own doc is **internally inconsistent** — Hindi appears in the intro but not the in-builder language list — and it has **no India locale** despite shipping Hindi as a document language. So the honest claim is not "nobody has Devanagari" but **"one competitor lists it, inconsistently, with no India presence, and nobody has Indic-script *templates*."* That is still a real gap, and it is narrower and more defensible than the original wording.

**The engineering answer is now concrete, and it is much cheaper than assumed.**

*Engine.* XeLaTeX or LuaLaTeX; **pdfLaTeX cannot do Unicode Devanagari** [V]. The legacy `devanagari`/`devnag` route still exists but requires ASCII transliteration input (`k.sa`) and emits legacy 8-bit encodings, so users could not paste Hindi and the PDF text layer would be unextractable — disqualifying.

*Shaping — the detail most often got wrong, and it differs by engine.*
- **XeLaTeX: HarfBuzz has been the shaper since v0.9999.0 (2013)** [V — XeTeX NEWS]. Devanagari shapes correctly with no flag.
- **LuaLaTeX: HarfBuzz is NOT the default.** luaotfload's own manual states ***"the default fontloader of luaotfload doesn't support many Indic scripts correctly. For these scripts it is recommended to use the harf mode along with the binary luahbtex"*** [V]. Requires `luahbtex` plus `mode=harf;script=dev2`. *What exactly breaks is not enumerated by the docs — the verified claim is only that default node mode is unsafe for Devanagari.*

*Package — this refutes the usual assumption.* **babel is the better choice, not polyglossia.** babel ships `locale/hi/` with hyphenrules, Indian calendar and danda handling, plus `bn, gu, kn, ml, mr, pa, ta, te` [V]. Its official Hindi guide gives the MWE `\usepackage[hindi, provide=*]{babel}` + `\babelfont{rm}{Mukta}`, and crucially: ***"In versions <24.14 and lualatex you should activate explicitly the Harfbuzz renderer"*** — **babel ≥24.14 enables HarfBuzz for you** [V]. Gaps: babel lacks Sanskrit and Odia; polyglossia lacks Gujarati. Choose polyglossia only if Sanskrit or Odia matter.

*Size — the number that changes the decision.* **`texlive-lang-indic` does not exist in Debian**; Indic is folded into `texlive-lang-other` (75.4 MB). But **the macro files are already in packages we ship** — `babel-hi.ini` is in `texlive-latex-base`, `gloss-hindi.ldf` in `texlive-latex-recommended` [V]. Only *hyphenation* lives in the 75 MB package, and hyphenation is close to irrelevant for a one-page resume.

| component | installed |
|---|---|
| `texlive-luatex` (LuaLaTeX) | **52.0 MB** |
| `fonts-lohit-deva` | **0.19 MB** |
| `fonts-noto-core` (OFL, wider coverage) | 42.6 MB |
| *`texlive-lang-other` (hyphenation only — skippable)* | *75.4 MB* |
| *`fonts-noto-extra` — **avoid*** | *334 MB* |

**Minimum viable Devanagari ≈ 52 MB**, or ~95 MB with Noto instead of Lohit. XeLaTeX looks cheaper at 16 MB until you count its `texlive-latex-extra` dependency (97 MB → 113 MB real cost). *[Arithmetic on verified per-package figures; not yet validated by an image build.]*

**Engine forcing function.** `tagpdf` v1.0d states the **xelatex route is "basically untested" and not recommended**, and that Lua mode *"is the future and the only one that will be usable for larger documents"* [V]. So **tagging + Devanagari ⇒ LuaLaTeX + luahbtex**. If B9 ships, this constraint is nearly free; if it doesn't, tagging alone does not justify an engine migration.

**Untested interaction — do this before shipping.** A search of `latex3/tagpdf` issues for devanagari / harfbuzz / indic returned **zero results** [V]. Whether HarfBuzz-shaped Devanagari produces correct ToUnicode/ActualText under tagging is **undetermined**, and tagpdf devotes a whole section to "real space glyphs" — precisely where shaped-script extraction tends to break. **Compile a Devanagari resume with and without `tagging=on` and diff `pdftotext` output.**

**Relevant to B1:** this weakens the Typst option for an India-first product. Typst has **open** Indic bugs — #8062 *"Hyphenation skips words containing Virama and combining marks, breaking Indic script support"* and #6339 *"Poor paragraphs (suboptimal line-breaking) with Indic scripts"* [V].

### B10b. Locale-specific document types and sections · **M** · status ❌ · **near-greenfield** · [#1292](https://github.com/sanskarpan/Latexy/issues/1292)
Structural localisation, not translation, is what differentiates in local markets:
- **Biodata / marriage biodata** (India) — LiveCareer ships it [V]; a genuinely India-specific document type with no Western analogue
- **`klauzula RODO`** (Poland) — the GDPR consent clause Polish employers expect, shipped as a **first-class section type** [V]
- **Government-job / PSU application formats** (India) [V]
- **Rirekisho** (Japan), **Lebenslauf** with photo/signature norms (Germany) — **nobody does these** [V by absence]

For an INR-priced product, biodata and PSU formats are the highest-relevance items in this entire catalog after compile latency — and they need no LLM spend, only templates and section models.

**LinkedIn leaves the same gap, and it is the strongest single piece of evidence for this line of work.** LinkedIn ships interface localisation into **Hindi, Marathi, Telugu, Punjabi and Bengali — but that does not extend to its AI features**: cover-letter drafting is **English-only**, and AI job search has no documented Hindi support [V]. It also ships **India-only Open to Work fields** (notice period, availability to join, expected salary — visible to recruiters *regardless* of the member's visibility setting, launched 2025-10-08) and **DigiLocker as the India-only identity-verification route** [V].

Read together: the largest player in the market has localised its *interface* for India and its *data model* for Indian hiring conventions, while leaving **AI generation English-only**. An India-first product whose AI works in Indic languages is competing where the incumbent has explicitly not gone.

### B10c. Model the resume on the convergent ATS field set · **M** · status ➖ · **highest-leverage data decision** · [#1293](https://github.com/sanskarpan/Latexy/issues/1293)
Eight parser and ATS schemas were compared field-by-field (Textkernel, RChilli, Affinda, HireAbility; Greenhouse, SmartRecruiters, Lever, Ashby). **The intersection is only six groups wide:**

```
identity   : given name, family name
contact    : ONE email, ONE phone, city / region / country
links      : LinkedIn + personal site (typed, not free text)
work[]     : employer · job title · start date · end date · is_current · description
education[]: institution · degree · field/major · start date · end date
skills[]   : flat list of named skills
```

Four consequences that should drive design:

1. **`employer · title · start · end` is the irreducible core.** Every one of the eight either stores exactly these four or stores nothing (Ashby stores only a file handle). **Anything a resume expresses that does not survive into those four fields is decoration.**
2. **Dates are the real contract.** Parsers model *partial* dates explicitly — Textkernel returns `{Date, IsCurrentDate, FoundYear, FoundMonth, FoundDay}`; SmartRecruiters' `When` type accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; Lever stores `{year, month}` only. Greenhouse alone forces a full ISO timestamp and therefore **fabricates day precision it never had**. Practical rule to encode in templates and linting: emit `MMM YYYY – MMM YYYY` or `MMM YYYY – Present`; **never a vertical date column** (Textkernel fatal code 418), never a date-only column (433).
3. **Skills are the widest divergence, and this is counter-intuitive.** All four parsers extract skills with rich metadata (evidence, months of experience, last-used), but **Greenhouse, SmartRecruiters and Ashby have no skills field at all** — skills reach an ATS *only* through job-description text. This independently corroborates Textkernel's suggested code 112: **put skills inside work-history bullets, not only in a standalone block.** That is a content recommendation, not a formatting one, and no competitor gives it.
4. **The taxonomy layer is where free text dies.** Greenhouse *writes* require `school_id`, `degree_id`, `discipline_id` against its own controlled lists; Affinda maps to Lightcast/ESCO/O\*NET/ISCO/SOC; Textkernel normalises school, degree, employer, title, skills and GPA. **Non-canonical spellings silently fail to normalise** — pairs naturally with B15 (ESCO).

The convergence is not accidental: HireAbility's schema uses straight **HR-Open Standards** naming, and Textkernel/RChilli are near-isomorphic to it. Adopting this shape internally makes export, parse-preview and the ATS simulator all speak the same language.

### B11. Surface parsed output prominently · **S** · status ➖ · [#1294](https://github.com/sanskarpan/Latexy/issues/1294)
The engine exists; the differentiation is presentational. Show "here is the text Workday will extract" beside the score. **Do not claim ATS emulation** — see Part D.

### B11b. Prep for AI interview screening · **M** · status ➖ · **new funnel stage** · [#1295](https://github.com/sanskarpan/Latexy/issues/1295)
**LinkedIn now runs candidate-facing AI interviews**: hirers invite applicants to an **audio or video screening with an AI interviewer**, questions and "ideal answers" generated from the JD and edited by the hirer; candidates can take a **practice interview** first; participation is voluntary — *"If you decide not to participate, you will not be automatically disqualified"* [V]. In Hiring Pro, hirers invite up to 40 applicants and **candidates must request transcripts, summaries or recordings** — ratings are never pushed to them [V].

Latexy has `/interview-prep` (3 routes) generating questions. The gap is preparing users for *this specific format*: JD-derived question generation is exactly what LinkedIn's own tooling does, so the same input produces comparable output. Note the controllership split — for real screenings the **hirer** is controller and LinkedIn is processor; practice-interview data stays with LinkedIn and is opt-out-able from AI training [V].

### B12. Browser extension · **L** · status ❌ · [#1296](https://github.com/sanskarpan/Latexy/issues/1296)
The one cluster where every tracker-first competitor is present and Latexy is absent: one-click capture from a posting (company, title, full JD text, URL), autofill, save-to-tracker. Simplify covers 100+ portals [V]. Latexy's `/apply/greenhouse|lever` is *better* where it works but covers 2 platforms; an extension is how coverage scales.

### B13. Reusable GitHub Action for CV rendering · **S** · status ❌ · **nobody has this** · [#1297](https://github.com/sanskarpan/Latexy/issues/1297)
**No project in the entire developer-facing survey publishes a consumer Action** to render a CV on push — RenderCV and JSON Resume both use Actions internally only [V]. Latexy has a public API (`/api/v1/compile`) and BYOK; an Action is a thin wrapper and a strong developer-audience acquisition channel.

## P2 — later

### B14. JSON Resume import/export · **S** · status ❌ · [#1298](https://github.com/sanskarpan/Latexy/issues/1298)
Schema is Draft 7, frozen at **v1.0.0 since 2014**, `resume-cli` **archived** June 2026, maintained *"with the help of AI agents"* [V]. **Support it as interchange; do not build on it.** Reactive Resume (40,282★) imports it while keeping a richer internal model — the right pattern. Note `@jsonresume/ats-validator` exists as a package.

### B15. Skill taxonomy via ESCO · **M** · status ❌ · [#1299](https://github.com/sanskarpan/Latexy/issues/1299)
**ESCO v1.2.1**: 3,039 occupations, 13,939 skills, **28 languages**, free download **and public API**, managed by DG EMPL [V]. Turns "keyword gap" into "skill gap against a real taxonomy" — and its multilingual dimension pairs with B10.

### B16. Symbol palette · **S** · status ❌ · [#1300](https://github.com/sanskarpan/Latexy/issues/1300)
Overleaf gates it behind premium [V]; TeXmaker ships 370 symbols free [V]; TeXstudio has a dockable one [V].

### B17. Reference manager sync · **M** · status ➖ · [#1301](https://github.com/sanskarpan/Latexy/issues/1301)
Zotero (7 routes) and Mendeley (5) exist. Overleaf's model is worth copying precisely: **link account → import library or collection as a read-only `.bib` → manual Refresh**, one-directional [V]. Papers/ReadCube is a third option Overleaf supports. Missing: EndNote (Overleaf also punts to manual export).

### B18. AI features competitors have that Latexy lacks · [#1302](https://github.com/sanskarpan/Latexy/issues/1302)
Each row is independently shippable and independently valuable; they are grouped only because they share the LLM plumbing.

| id | feature | holder | status | size |
|---|---|---|---|---|
| **B18.1** [#1344](https://github.com/sanskarpan/Latexy/issues/1344) | Natural language → LaTeX | Overleaf TeXGPT [V] | ❌ | **M** |
| **B18.2** [#1345](https://github.com/sanskarpan/Latexy/issues/1345) | Image/text → LaTeX **table** | Overleaf Table Generator [V] | ❌ | **M** |
| **B18.3** [#1346](https://github.com/sanskarpan/Latexy/issues/1346) | Image/text → LaTeX **math** | Overleaf Equation Generator [V] | ❌ | **M** |
| **B18.4** [#1347](https://github.com/sanskarpan/Latexy/issues/1347) | Citation checking vs a scholarly DB | Overleaf + Dimensions [V] | ❌ | **M** |
| **B18.5** [#1348](https://github.com/sanskarpan/Latexy/issues/1348) | Named rewrite modes (paraphrase / concise / scientific / split / join) | Overleaf [V] | ➖ `/ai/rewrite` is generic | **S** |
| **B18.6** [#1349](https://github.com/sanskarpan/Latexy/issues/1349) | Synonyms | Overleaf [V] | ❌ | **S** |
| **B18.7** [#1350](https://github.com/sanskarpan/Latexy/issues/1350) | AI interview **simulation** (not just question generation) | JSON Resume registry [V] | ➖ `/interview-prep` generates only | **M** |

**B18.2/B18.3 are the highest-value pair** — users pasting a table out of a PDF is a real, frequent LaTeX pain point, and it is squarely in our wheelhouse.

### B19. Editor capabilities from the LaTeX category · [#1303](https://github.com/sanskarpan/Latexy/issues/1303)
Individually small, collectively the difference between "a textarea" and "an editor". Ordered by value per unit of work.

| id | capability | holder | status | size |
|---|---|---|---|---|
| **B19.1** [#1351](https://github.com/sanskarpan/Latexy/issues/1351) | Autocomplete for commands / refs / citations | TeXstudio `.cwl`, texlab [V] | ❌ | **M** |
| **B19.2** [#1352](https://github.com/sanskarpan/Latexy/issues/1352) | Compile-on-save / continuous background compile | Papeeria, LaTeX Workshop [V] | ➖ cover-letter page only | **S** |
| **B19.3** [#1353](https://github.com/sanskarpan/Latexy/issues/1353) | Outline / structure navigator | LyX, tinymist [V] | ❌ | **S** |
| **B19.4** [#1354](https://github.com/sanskarpan/Latexy/issues/1354) | Code folding | TeXstudio [V] | ❌ | **S** |
| **B19.5** [#1355](https://github.com/sanskarpan/Latexy/issues/1355) | Word count | LaTeX Workshop [V] | ❌ | **S** |
| **B19.6** [#1356](https://github.com/sanskarpan/Latexy/issues/1356) | Stop-on-first-error toggle | Overleaf [V] | ❌ | **S** |
| **B19.7** [#1357](https://github.com/sanskarpan/Latexy/issues/1357) | Draft mode | Overleaf [S] | ❌ | **S** |
| **B19.8** [#1358](https://github.com/sanskarpan/Latexy/issues/1358) | Custom dictionaries for spell check | Overleaf [C] | ❌ | **S** |
| **B19.9** [#1359](https://github.com/sanskarpan/Latexy/issues/1359) | Multi-cursor editing | TeXstudio, VS Code [V] | ❌ | **S** |
| **B19.10** [#1360](https://github.com/sanskarpan/Latexy/issues/1360) | **vim / emacs keybinding modes** | Overleaf, Typst.app [V] | ❌ — *directly relevant to the TUI audience* | **M** |
| **B19.11** [#1361](https://github.com/sanskarpan/Latexy/issues/1361) | Hover previews of math / graphics / citations | LaTeX Workshop [V] | ❌ | **M** |
| **B19.12** [#1362](https://github.com/sanskarpan/Latexy/issues/1362) | Thesaurus | TeXstudio, LyX [V] | ❌ | **S** |
| **B19.13** [#1363](https://github.com/sanskarpan/Latexy/issues/1363) | Presentation mode | Typst.app, TeXstudio [V] | ❌ · P3 | **M** |
| **B19.14** [#1364](https://github.com/sanskarpan/Latexy/issues/1364) | **Regex-aware find & replace** (within document) | TeXstudio, VS Code [V] | ❌ — *legacy 4.4, recovered by the Part F audit* | **S** |
| **B19.15** [#1365](https://github.com/sanskarpan/Latexy/issues/1365) | **In-app package documentation lookup** (`texdoc`-style) | TeXstudio [V] | ❌ — *legacy 4.5, recovered by the Part F audit* | **S** |

**Note:** Monaco already provides the substrate for B19.4, B19.5, B19.9 and **B19.14** — these are configuration and wiring, not implementation. B19.2's engine exists and is proven on one page; extending it is plumbing. **B19.15 pairs directly with the already-shipped `PackageManagerPanel.tsx`** — a user who can add a package currently cannot read what it does.

### B20. Track changes with accept/reject · **L** · status ❌ · [#1304](https://github.com/sanskarpan/Latexy/issues/1304)
Overleaf gates it behind premium [V]. Three models exist: accept/reject per range (Overleaf), auto-accept (Authorea [S]), sticky-note markers (LyX [V]). Latexy has comments + collaborators + yjs, so the substrate is there. Note `latexdiff` + **`latexrevise`** already do accept/reject at the source level [V] — a cheaper path than building it in the editor.

### B21. Rendered-document diffing · **M** · status ➖ · [#1305](https://github.com/sanskarpan/Latexy/issues/1305)
`latexdiff` **v1.4.0 (2026-01-02)**, GPL-3.0, in TeX Live, with `latexdiff-vc` wrappers for git/svn/hg and a **WASM browser UI** [V]. `diff-pdf` (4.3k★) is **CI-friendly via exit codes** and emits a highlighted diff PDF [V]; `diffoscope` handles PDFs in a general recursive differ [V]. **No surveyed product exposes this to users.** Latexy has `/diff-with-parent` and `resume_diff_service.py` already — this is packaging, not invention.

### B22. Self-hosting · **L** · status ❌ · [#1306](https://github.com/sanskarpan/Latexy/issues/1306)
Reactive Resume ships `docker compose up -d` + Postgres + optional SeaweedFS, MIT [V]. Overleaf has free Community Edition vs paid Server Pro (SSO, sandboxed compiles, track changes) [V]. Typst.app sells an On-Premises tier with LDAP [V]. **Pairs naturally with BYOK** — the same privacy-motivated user.

### B23. First-party MCP server · **S** · status ❌ · **two competitors shipped this; we are closest to it** · [#1307](https://github.com/sanskarpan/Latexy/issues/1307)
**Rezi ships a Pro-gated MCP server** at `api.rezi.ai/mcp` — streamable HTTP, tools `list_resumes`/`read_resume`/`write_resume`, credentials held in memory and never persisted, with documented setup for **Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI and Lovable**, open-sourced at `github.com/rezi-io/rezi-mcp`. **Reactive Resume ships one too** — hosted at `rxresu.me/mcp`, **34 tools**, OAuth, published to the MCP registry with prompts and `resume://` resources [V]. Nobody else in the surveyed field has any LLM-client-reachable interface.

**This is the cheapest item on the list for us**, because the hard part is already built: `packages/tui` exists, and it already speaks to the API with a token store, resume resolution and job streaming (`src/tools/shared.ts`). An MCP server is a second transport over the same tool layer, not a new product. Effectively a public read/write resume API reachable from any LLM client — and it is the natural home for an audience that already lives in a terminal.

### B24. Academic CV — the largest verified gap in the category, and the one we are built for · **M** · status ➖ · **strongest strategic fit in this document** · [#1308](https://github.com/sanskarpan/Latexy/issues/1308)

> **Placement note:** this sits under *P2 — later* only because B-numbers were assigned in the order research arrived. On merit I would argue it belongs in **P1**, and it is the one item in this file where I think the ordering is wrong. Flagging rather than silently re-filing it, since backlog priority is the reader's call.
**Across all nine mid-tier builders surveyed: zero ORCID integrations and zero publication importers** [V]. Enhancv is the only product that mentions ORCID *at all*, and only as prose advice with no structured field. Rezi files Publications under an "Academic" menu group; Standard Resume and Novoresume have Publications sections; **none of them has a DOI lookup, a BibTeX path, a citation-style choice, or an ORCID field.** Teal and Kickresume have no academic surface whatsoever — and on Kickresume "CV" means the personal website, not a curriculum vitae.

Multi-page handling, which an academic CV requires by definition, is where the category actively fights the use case: Rezi's score **penalises >2 pages**, Standard Resume's whole pitch is one-page auto-fit, and **Novoresume caps pages by pricing tier** — 1 page on Basic, 10 on Premium — while its own guidance says an academic CV of *"eight pages or more"* is fine, a contradiction inside a single product. Only Enhancv explicitly supports multi-page CVs for academics, and Reactive Resume's unbounded **free-form page format** sidesteps the problem.

**Why this matters more for Latexy than for anyone else:** the academic CV is LaTeX's native use case and its incumbent audience. We already have multi-page compilation, real typography, and BibTeX in the toolchain by construction. The competitive moat is not that this is hard — it is that a WYSIWYG builder with a one-page auto-fit engine **cannot** ship it without abandoning its core design. Concretely: an ORCID field, DOI/BibTeX import into a Publications section, and a citation-style selector. Pairs with B10c (publications are outside the convergent ATS field set, so this is a *human-reader* feature, not an ATS one — and should be positioned as such).

### B25. Anonymous / blind-review mode · **S** · status ❌ · **nobody has this** · [#1309](https://github.com/sanskarpan/Latexy/issues/1309)
Redact PII at *render* time for a share link: name, email, phone, address, LinkedIn and GitHub URLs blanked, original document untouched, with a banner on the shared view. **No surveyed product offers it** — and the substrate is already here: `/resumes/{id}/share` issues tokens, `/r/[token]` renders them, and compilation is server-side so a redacted variant costs one extra compile.

Two real audiences: peer review on Reddit/Discord (where people currently hand-blur screenshots) and university career centres reviewing student CVs. Carried over from the legacy catalog (2.13), which this file had dropped.

## P1–P3 — completeness sweep (closes Part C)

> **Why this section exists.** Part B originally held 29 items while **Part C listed 117 absent features** — so most of the catalog's own gaps were untracked, and several legacy **P0** items (real-time ATS score, page-count warning) had no owner at all. This sweep resolves every remaining absence into exactly one of three states: **an item below**, **an existing item**, or **an explicit refusal** in Part D. Nothing in Part C is now unaccounted for.

| id | item | summary |
|---|---|---|
| **B28** [#1310](https://github.com/sanskarpan/Latexy/issues/1310) | Real-time debounced ATS score + multi-dimensional score card | Legacy 2.3 (**P0**) and 2.7. Scoring exists but is request-scoped, not live.  **2 children below** |
| ↳ **B28a** [#1366](https://github.com/sanskarpan/Latexy/issues/1366) | Real-time debounced ATS score in the editor | |
| ↳ **B28b** [#1367](https://github.com/sanskarpan/Latexy/issues/1367) | Multi-dimensional score card with deep links | |
| **B29** [#1311](https://github.com/sanskarpan/Latexy/issues/1311) | Email notification delivery | ✅ Shipped: completion, terminal failure, debounced share-view, and weekly-digest delivery through Resend/SMTP with Modal parity and per-trigger preferences. |
| **B30** [#1312](https://github.com/sanskarpan/Latexy/issues/1312) | Real-time page-count / overflow warning | Legacy 3.2 (**P0**). `page_count` is already parsed server-side but never surfaced as a warning. |
| **B31** [#1313](https://github.com/sanskarpan/Latexy/issues/1313) | AI writing assistant / chat over the document | Legacy 3.6 + C2 'AI chat over the document' + 'LLM tool-calling into editor state'. |
| **B32** [#1314](https://github.com/sanskarpan/Latexy/issues/1314) | Two-way Git sync (currently import-only) | Legacy 1.12 + C7 'Git bridge'. `/github` has 11 routes but only imports. |
| **B33** [#1315](https://github.com/sanskarpan/Latexy/issues/1315) | Compile timeout tiers by plan + compile caching | Legacy 1.6 + C8 'Compile caching / incremental' (**nobody verified has this**).  **2 children below** |
| ↳ **B33a** [#1368](https://github.com/sanskarpan/Latexy/issues/1368) | Compile timeout tiers by plan | |
| ↳ **B33b** [#1369](https://github.com/sanskarpan/Latexy/issues/1369) | Compile caching / incremental compile | |
| **B34** [#1316](https://github.com/sanskarpan/Latexy/issues/1316) | Resume benchmarking — percentile vs other applicants | Legacy 3.22 + C3 'Benchmark vs other applicants' (LinkedIn Premium gates it). |
| **B35** [#1317](https://github.com/sanskarpan/Latexy/issues/1317) | Smart import from competitor resume builders | Legacy 5.12. `/sources/import-url` and LinkedIn exist; no builder-specific importers. |
| **B36** [#1318](https://github.com/sanskarpan/Latexy/issues/1318) | Mobile / PWA | Legacy 1.20 + C10. **Seven of nine** competitors have no first-party mobile app either. |
| **B37** [#1319](https://github.com/sanskarpan/Latexy/issues/1319) | White-label / careers-centre edition + SSO/LDAP | Legacy 5.4 + C10 x2. Enhancv's education tier is the model; Rezi adds revenue share.  **2 children below** |
| ↳ **B37a** [#1370](https://github.com/sanskarpan/Latexy/issues/1370) | White-label / careers-centre edition | |
| ↳ **B37b** [#1371](https://github.com/sanskarpan/Latexy/issues/1371) | SSO / LDAP | |
| **B38** [#1320](https://github.com/sanskarpan/Latexy/issues/1320) | Strict typed validation with location-pinpointed errors | C1. RenderCV/Pydantic pinpoints the exact field and line; we surface LaTeX errors only. |
| **B39** [#1321](https://github.com/sanskarpan/Latexy/issues/1321) | Section visibility per variant | C1 — **nobody has this.** Our `/variants` fork content instead of toggling visibility. |
| **B40** [#1322](https://github.com/sanskarpan/Latexy/issues/1322) | Auto-scale font / spacing to force one page | C1. `always-fit-resume` does it; Standard Resume's single spacing slider is the UX to copy. |
| **B41** [#1323](https://github.com/sanskarpan/Latexy/issues/1323) | Pre-written phrase library indexed by title + seniority | C1. Kickresume claims 20k phrases / 3.2k jobs; LiveCareer 50k+; Enhancv indexes on 3 axes. |
| **B42** [#1324](https://github.com/sanskarpan/Latexy/issues/1324) | Cover-letter signature (type / draw / upload) | C1. Zety ships it; German and Japanese conventions expect a signature. |
| **B43** [#1325](https://github.com/sanskarpan/Latexy/issues/1325) | Dark-mode PDF viewer | C1/legacy 5.17. Texifier has it. `PDFPreview.tsx` already imports a Moon icon. |
| **B44** [#1326](https://github.com/sanskarpan/Latexy/issues/1326) | Auto-optimize action from the score report | C3. Zety ships upload → score → **apply changes** → download as one loop. |
| **B45** [#1327](https://github.com/sanskarpan/Latexy/issues/1327) | Locale-tuned ATS checker + published score threshold | C3 x2. LiveCareer runs a UK-tuned checker; Zety publishes '80 or higher'.  **2 children below** |
| ↳ **B45a** [#1372](https://github.com/sanskarpan/Latexy/issues/1372) | Locale-tuned ATS checker | |
| ↳ **B45b** [#1373](https://github.com/sanskarpan/Latexy/issues/1373) | Published score threshold with stated calibration | |
| **B46** [#1328](https://github.com/sanskarpan/Latexy/issues/1328) | Tracker depth: job alerts, saved jobs, reminders, calendar sync, contacts CRM | C4 x5. Huntr and Teal are much deeper here; LinkedIn's own caps are documented.  **5 children below** |
| ↳ **B46a** [#1374](https://github.com/sanskarpan/Latexy/issues/1374) | Job alerts | |
| ↳ **B46b** [#1375](https://github.com/sanskarpan/Latexy/issues/1375) | Saved jobs | |
| ↳ **B46c** [#1376](https://github.com/sanskarpan/Latexy/issues/1376) | Reminders / staleness prompts | |
| ↳ **B46d** [#1377](https://github.com/sanskarpan/Latexy/issues/1377) | Calendar sync / interview scheduling | |
| ↳ **B46e** [#1378](https://github.com/sanskarpan/Latexy/issues/1378) | Contacts CRM | |
| **B47** [#1329](https://github.com/sanskarpan/Latexy/issues/1329) | Email parsing for application status | C4. Genuinely hard and privacy-heavy; scope it narrowly or not at all. |
| **B48** [#1330](https://github.com/sanskarpan/Latexy/issues/1330) | Outreach message generation + recruiter lookup | C4 x2. Careerflow does both; Teal has stage-aware email templates.  **2 children below** |
| ↳ **B48a** [#1379](https://github.com/sanskarpan/Latexy/issues/1379) | Outreach / referral message generation | |
| ↳ **B48b** [#1380](https://github.com/sanskarpan/Latexy/issues/1380) | Recruiter / hiring-manager lookup | |
| **B49** [#1331](https://github.com/sanskarpan/Latexy/issues/1331) | Application-outcome signals — the verified category gap | C4 x4. **Zero platforms give a rejected candidate a reason** — verified across four ATSs.  **4 children below** |
| ↳ **B49a** [#1381](https://github.com/sanskarpan/Latexy/issues/1381) | Rejection / outcome feedback | |
| ↳ **B49b** [#1382](https://github.com/sanskarpan/Latexy/issues/1382) | Ghosting / employer responsiveness signals | |
| ↳ **B49c** [#1383](https://github.com/sanskarpan/Latexy/issues/1383) | Application-viewed / resume-downloaded signals | |
| ↳ **B49d** [#1384](https://github.com/sanskarpan/Latexy/issues/1384) | Candidate-side signal visible to the hirer | |
| **B50** [#1332](https://github.com/sanskarpan/Latexy/issues/1332) | Export surface: Google Drive, SVG/JPEG, ePub/ODF, email delivery | C5 x4. Each is small; none is load-bearing.  **4 children below** |
| ↳ **B50a** [#1385](https://github.com/sanskarpan/Latexy/issues/1385) | Google Drive export | |
| ↳ **B50b** [#1386](https://github.com/sanskarpan/Latexy/issues/1386) | SVG / JPEG export | |
| ↳ **B50c** [#1387](https://github.com/sanskarpan/Latexy/issues/1387) | ePub / ODF / DocBook export | |
| ↳ **B50d** [#1388](https://github.com/sanskarpan/Latexy/issues/1388) | Email delivery of the document | |
| **B51** [#1333](https://github.com/sanskarpan/Latexy/issues/1333) | Collaboration depth: @mentions, suggesting mode, chat, peer review | C6 x4. We have yjs + comments + collaborators; these are the layer above.  **4 children below** |
| ↳ **B51a** [#1389](https://github.com/sanskarpan/Latexy/issues/1389) | @mentions in comments | |
| ↳ **B51b** [#1390](https://github.com/sanskarpan/Latexy/issues/1390) | Suggesting mode | |
| ↳ **B51c** [#1391](https://github.com/sanskarpan/Latexy/issues/1391) | Collaborator chat | |
| ↳ **B51d** [#1392](https://github.com/sanskarpan/Latexy/issues/1392) | Peer / mentor review with in-document comments | |
| **B52** [#1334](https://github.com/sanskarpan/Latexy/issues/1334) | Per-paragraph / per-element versioning | C7. Curvenote has the finest-grained versioning found anywhere. |
| **B53** [#1335](https://github.com/sanskarpan/Latexy/issues/1335) | Editor infrastructure: duplicate-label detection, LSP, scripting | C8 x3. LSP is the strategic one — texlab/tinymist would subsume much of B19.  **3 children below** |
| ↳ **B53a** [#1393](https://github.com/sanskarpan/Latexy/issues/1393) | Duplicate-label detection | |
| ↳ **B53b** [#1394](https://github.com/sanskarpan/Latexy/issues/1394) | Evaluate adopting an LSP (texlab / tinymist) | |
| ↳ **B53c** [#1395](https://github.com/sanskarpan/Latexy/issues/1395) | Scripting engine for user macros | |
| **B54** [#1336](https://github.com/sanskarpan/Latexy/issues/1336) | Script coverage beyond Devanagari: CJK, RTL, multilingual-in-one-document, europecv | C9 x4. The same engine work as B10; only fonts and packages differ.  **4 children below** |
| ↳ **B54a** [#1396](https://github.com/sanskarpan/Latexy/issues/1396) | CJK support | |
| ↳ **B54b** [#1397](https://github.com/sanskarpan/Latexy/issues/1397) | RTL / Arabic / Hebrew support | |
| ↳ **B54c** [#1398](https://github.com/sanskarpan/Latexy/issues/1398) | Multilingual document in one file | |
| ↳ **B54d** [#1399](https://github.com/sanskarpan/Latexy/issues/1399) | EU-language CV standard (europecv) | |
| **B55** [#1337](https://github.com/sanskarpan/Latexy/issues/1337) | UI localisation | C9. Reactive Resume has 56 locales via Crowdin; every commercial builder is Latin-only. |
| **B56** [#1338](https://github.com/sanskarpan/Latexy/issues/1338) | Accessibility commitments: statement, screen-reader support, contrast, fonts | C9 x2 + C10 x3. **No product among the nine has an accessibility statement.** Cheap to be first.  **5 children below** |
| ↳ **B56a** [#1400](https://github.com/sanskarpan/Latexy/issues/1400) | Publish an accessibility statement | |
| ↳ **B56b** [#1401](https://github.com/sanskarpan/Latexy/issues/1401) | Named screen-reader support (NVDA / VoiceOver / TalkBack) | |
| ↳ **B56c** [#1402](https://github.com/sanskarpan/Latexy/issues/1402) | Dedicated accessibility support channel | |
| ↳ **B56d** [#1403](https://github.com/sanskarpan/Latexy/issues/1403) | Screen-reader-friendly output | |
| ↳ **B56e** [#1404](https://github.com/sanskarpan/Latexy/issues/1404) | Dyslexia-friendly fonts and high-contrast mode | |
| **B57** [#1339](https://github.com/sanskarpan/Latexy/issues/1339) | Pricing SKUs: lifetime and weekly | C10 x2. Rezi $149 / Novoresume $139.99 lifetime; Resume.io ₹249 / Teal $13 weekly.  **2 children below** |
| ↳ **B57a** [#1405](https://github.com/sanskarpan/Latexy/issues/1405) | Lifetime plan | |
| ↳ **B57b** [#1406](https://github.com/sanskarpan/Latexy/issues/1406) | Weekly plan | |
| **B58** [#1340](https://github.com/sanskarpan/Latexy/issues/1340) | Passkey / 2FA | C10. Reactive Resume has passkeys/WebAuthn + TOTP; nobody else does. |
| **B59** [#1341](https://github.com/sanskarpan/Latexy/issues/1341) | Referral / affiliate programme | C10. Standard Resume runs $10 both ways, uncapped. |
| **B60** [#1342](https://github.com/sanskarpan/Latexy/issues/1342) | Offline mode (PWA read + share) | C10. **Only one of nine** competitors supports offline editing (Resume.io). |
| **B61** [#1343](https://github.com/sanskarpan/Latexy/issues/1343) | Free identity verification | C4. LinkedIn's is free and **DigiLocker is the India-only route** — directly relevant. |

Each carries its own GitHub issue with the full evidence; the one-line summaries above are pointers, not the content. **Six further Part C absences were resolved as explicit refusals instead of items** — they are in Part D with reasons.

**Sequencing constraints worth honouring** (each is stated in the relevant issue):
- **B53 before B19.1** — an LSP would deliver autocomplete, outline and hover previews together instead of three hand-built features.
- **B54 after B10** — they share the engine decision; doing them together wastes the work if B10 slips.
- **B33 inside B1** — compile caching is a latency lever, not a follow-up.
- **B30 + B40 together** — warn about overflow, then offer the fix.
- **B44 must not repeat #1247** — applying score fixes has to be reviewable and revertable.
- **B29 blocks the email half of B50.**

## P3 — speculative

*Deduplicated: culture-specific document formats now live in **B10b** (they are a P1/P2 India-market item, not speculative); ORCID login and publication import moved to **B24**.*

- **PWA / mobile** — ❌. Only Texifier (iOS) among LaTeX tools [V]; Kickresume gates mobile apps behind premium [V]. **L**
- **Client-side PDF generation** — Reactive Resume moved to `@react-pdf/renderer`, dropping server Chromium [V]. Not applicable to LaTeX without WASM. **XL**
- **In-browser WASM compile** — `resumeforfree` (85★) does Typst-via-WASM with no server [V]. But **SwiftLaTeX's package mirror is NXDOMAIN** [V] and TeXlyre-busytex needs **122–432 MB** of WASM+data [C]. Viable only as an optional offline preview. **XL**
- **Interactive/executable content** — Curvenote does Plotly/Bokeh/Jupyter inline [V]. Wrong product. **XL**
- **Per-paragraph/equation/figure independent versioning** — Curvenote [V]; finest-grained versioning found anywhere. **L**
- **Journal submission integration** and **DOI minting** — academic adjacency beyond B24's scope. **L**
- **Auto font/line-spacing scaling to force one page** — `always-fit-resume` (192★) [C]. Genuinely useful, small. **M**
- **Passkey / 2FA** — Reactive Resume has it [V]. **M**
- **Multi-language UI** via Crowdin — Reactive Resume [V]. **M**

---

# Part C — Exhaustive master feature list

Everything observed anywhere, deduplicated, with an example holder and Latexy's status. **Includes features we should not build** — flagged in Part D but listed here for completeness, per the brief.

## C1. Resume authoring
| feature | example holder | Latexy |
|---|---|---|
| WYSIWYG / rich-text builder | Reactive Resume, Overleaf Visual Editor [V] | ✅ `/workspace/builder` |
| Raw LaTeX source editing | Overleaf [V] | ✅ |
| Markdown-based authoring | resume.lol, resume-ai [C] | ❌ |
| Declarative single-file source (YAML/JSON/TOML) | RenderCV, imprecv, brilliant-CV [V] | ❌ |
| Published JSON Schema for the data | JSON Resume, RenderCV, imprecv [V] | ❌ |
| Strict typed validation, location-pinpointed errors | RenderCV/Pydantic [V] | ❌ |
| Drag-and-drop section reordering | Reactive Resume [V] | ➖ `/ai/reorder-sections` is AI-driven |
| Arbitrary custom sections with typed entry kinds | RenderCV [V] | ➖ |
| Section visibility per variant | **nobody** | ❌ |
| Photo support (L/R/multiple/non-circular) | AltaCV, moderncv [V] | ➖ template-dependent |
| Icon sets (FontAwesome 5/6/7, simpleicons) | AltaCV, Awesome-CV [V] | ➖ |
| Named colour roles / colour themes | AltaCV (8 roles), moderncv (8) [V] | ✅ `DesignPanel.tsx` |
| Two-column with automatic page breaking | AltaCV via `paracol` [V] | ➖ |
| A4 / US-Letter switching | Reactive Resume, Enhancv [V] | ➖ |
| Auto-scale font to force one page | always-fit-resume [C] | ❌ |
| Character / section-item limits | Enhancv (12 items free) [V] | ➖ quota-based |
| Multi-page CV handling | Overleaf, europecv [V] | ✅ academic-cv |
| **Locked grid (prevents layout breakage)** | LiveCareer — deliberate ATS-safety tradeoff [S] | ❌ |
| Store multiple versions of one document | LiveCareer [V] | ✅ `/variants`, `/checkpoints` |
| Pre-written phrase library by title + seniority | LiveCareer (50k US / 100k UK, contradictory) [C], Zety (40+/title) [S] | ❌ |
| Three alternative phrasings per paragraph | LiveCareer [C] | ❌ — cf. B7 |
| Signature on cover letter (type/draw/import) | Zety [S] | ❌ |
| **Biodata / marriage biodata** | LiveCareer India [V] | ❌ |
| **Market-specific consent-clause section (RODO)** | LiveCareer Poland [V] | ❌ |
| Matching cover-letter variant | typst modern-cv, brilliant-CV [V] | ✅ `/cover-letters` |
| Template customizer (per-resume design overrides) | Kickresume, Enhancv [V] | ✅ `TemplateCustomizerPanel.tsx` |
| **Print-preview / colour-dependency check** | **nobody** | ✅ `lib/print-preview.ts` |
| Resume freshness / staleness tracking | Teal (via tracker) [V] | ✅ `freshness_status` |
| Project-level tags & organisation | Overleaf [V] | ✅ `/resumes/{id}/tags` |
| **Anonymous / blind-review mode** (redact PII at render) | **nobody** | ❌ · **S** — see B25 |
| Dark mode (app) | Reactive Resume [V] | ? unverified |
| Dark-mode PDF viewer | Texifier [V] | ❌ |

## C2. AI
| feature | example holder | Latexy |
|---|---|---|
| Bullet generation | Rezi, Teal [C] | ✅ `/ai/generate-bullets` |
| Bullet rewrite | most [C] | ✅ `/ai/rewrite` |
| **3 rewrite options per bullet** | **nobody** | ❌ |
| Summary / profile generation | most [C] | ✅ `/ai/generate-summary` |
| Publication list generation | — | ✅ `/ai/generate-publications` |
| Proofread / grammar | Overleaf-Writefull [V] | ✅ `/ai/proofread` + LanguageTool |
| Spell check | Overleaf (Aspell), TeXstudio (Hunspell) [V] | ✅ `/ai/spell-check` |
| Synonyms | Overleaf [V] | ❌ |
| Rewrite modes: paraphrase/concise/scientific/split/join | Overleaf [V] | ➖ |
| JD-targeted tailoring | Rezi, Teal, Jobscan [C] | ✅ `/optimize`, `/quick-tailor` |
| Batch tailoring to many JDs | — | ✅ `/batch-tailor` |
| Cover letter generation | all [C] | ✅ |
| Interview question generation | Rezi, Kickresume [C] | ✅ `/interview-prep` |
| Interview **simulation** | JSON Resume registry [V] | ❌ |
| Mock interview (voice/video) | Careerflow, Final Round AI [C] | ❌ |
| Salary estimate / benchmarking | Careerflow, Huntr [C] | ✅ `/ai/salary-estimate` |
| Career path mapping | Kickresume Career Map [V] | ✅ `/career/analyze` |
| Translation | — | ✅ `/ai/translate` |
| Date standardisation | — | ✅ `/ai/standardize-dates` |
| Contact formatting | — | ✅ `/ai/format-contacts` |
| Confidence / age analysis | — | ✅ `/ai/confidence-score`, `/ai/age-analysis` |
| Writing personas | — | ✅ `/ai/personas` |
| LaTeX error explanation | Overleaf Error Assist [V] | ✅ `/ai/explain-error` |
| Natural language → LaTeX | Overleaf TeXGPT [V] | ❌ |
| Image/text → LaTeX math | Overleaf Equation Generator [V] | ❌ |
| Image/text → LaTeX table | Overleaf Table Generator [V] | ❌ |
| Citation checking vs scholarly DB | Overleaf + Dimensions [V] | ❌ |
| AI chat over the document | Overleaf, TeXstudio [V] | ❌ |
| Multi-provider LLM choice | Reactive Resume, TeXstudio [V] | ✅ BYOK 4 providers |
| Local/self-hosted model support | TeXstudio (llamafile) [V] | ➖ via BYOK base URL |
| LLM tool-calling into editor state | TeXstudio [V] | ❌ |
| Agent skill packaging (`npx skills add`) | RenderCV [V] | ❌ |
| **MCP server (first-party)** | **Rezi** — Pro-gated `api.rezi.ai/mcp`, streamable HTTP, tools `list_resumes`/`read_resume`/`write_resume`, documented setup for **Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI, Lovable**, open-sourced at `github.com/rezi-io/rezi-mcp`; **Reactive Resume** — hosted `rxresu.me/mcp`, **34 tools**, OAuth, published to the MCP registry with prompts and `resume://` resources [V] | ❌ — **but see B23** |
| MCP server (third-party wrapper) | workopia-mcp, resumake-mcp [V] | ❌ |
| "Humanise" / AI-detection evasion | various [C] | ❌ — see Part D |

## C3. ATS & scoring
| feature | example holder | Latexy |
|---|---|---|
| Numeric ATS score | Rezi, Kickresume, Enhancv, Jobscan [C] | ✅ |
| Real-time / debounced scoring | Enhancv, Rezi [C] | ➖ |
| Keyword gap vs JD | all [C] | ✅ |
| Format/design checks | Rezi (23 metrics), Kickresume (20+) [C] | ✅ |
| **Per-ATS profiles naming vendors** | Jobscan ("ATS Tip") [C] | ✅ **7 named** |
| **Visible parsed output** | **nobody** | ✅ pdfplumber |
| Benchmark vs other applicants | LinkedIn Premium [C] | ❌ |
| **Industry-specific ATS calibration** | Jobscan [C] | ✅ `industry_ats_profiles.py`, `industry_override` |
| **Keyword-density map** | — | ✅ `POST /ats/keyword-density` |
| **Recruiter-attention heatmap** | **nobody** | ✅ `heatmap-generator.ts` — rule-based, eye-tracking research |
| Score history over time | — | ✅ `/resumes/{id}/score-history` |
| Dedicated ATS-validator library | `@jsonresume/ats-validator` [V] | ➖ |
| Accessible icon alt-text via `accsupp` | AltaCV [V] | ❌ |
| Parse-rate leaderboard | a widely-circulated Reddit claim [C, disputed] | ❌ — see Part D |
| Published score threshold | Zety ("80 or higher"), LiveCareer ("80–100% good") [V] | ❌ |
| **Auto-optimize action from the score report** | Zety (upload → score → apply changes → download) [V] | ❌ · **M** |
| JD skills-matching | LiveCareer [C]; Zety does **not** advertise it [V] | ✅ `/optimize` |
| Locale-tuned ATS checker | LiveCareer UK [V] | ❌ |
| Free-tier ATS checker | Zety, LiveCareer (partial) [V] | ✅ |

## C4. Job search & application
| feature | example holder | Latexy |
|---|---|---|
| Job tracker / kanban | Huntr, Teal, Simplify [V]; **LinkedIn: 5 stages, transitions asymmetric and irreversible past "applied", jobs auto-removed after 1 year** [V] | ✅ `/tracker` |
| Stored resume slots | **LinkedIn: exactly 4** (Word/PDF, <2MB recommended), and application-resumes vs profile-media resumes are **non-interchangeable** [V] | ✅ unlimited |
| Job alerts | **LinkedIn: hard cap 20**, daily or weekly only [V] | ❌ |
| Saved jobs | **LinkedIn: 2,000, no bulk unsave** [V] | ❌ |
| AI interview screening (candidate side) | LinkedIn [V] | ➖ see B11b |
| Free identity verification | **LinkedIn** — CLEAR (US/CA/MX), Persona NFC passport, **DigiLocker India-only**; restores a lowered Easy Apply cap [V] | ❌ |
| One-click capture from posting | Huntr clipper, Jobscan [V] | ❌ needs extension |
| Autofill across portals | Simplify (100+) [V] | ❌ |
| **Direct API submission to ATS** | **nobody** | ✅ Greenhouse + Lever |
| Application submission history | Huntr [V] | ✅ `/apply/submissions` |
| Bulk apply | auto-appliers [C] | ❌ — see Part D |
| Reminders / staleness prompts | Huntr [V] | ❌ |
| Email parsing for status | some [C] | ❌ |
| Calendar sync / interview scheduling | Huntr [V] | ❌ |
| Contacts CRM | Huntr, Careerflow [V] | ❌ |
| Referral / outreach message generation | Careerflow [C] | ❌ |
| Recruiter / hiring-manager lookup | Careerflow [V] | ❌ |
| Job board / aggregation | Simplify, Huntr [V] | ❌ — see Part D |
| JD scraping from URL | — | ✅ `/scrape-job-description` |
| Funnel analytics | Huntr [V] | ✅ `/analytics` |
| **Rejection / outcome feedback** | **Zero verified instances anywhere.** SmartRecruiters' candidate-facing `StatusDto` has exactly three fields — `applicationId`, `status`, `substatus` — and **no reason field**; reasons live in an employer-gated Configuration API. Greenhouse's `rejection_reason` taxonomy is internal analytics. Handshake shows "Declined" and explicitly **does not notify**. **No law requires it** — UK ACAS states outright that *"Employers do not have to explain their reasons for rejecting job applications"*; EU AI Act Art. 86 is on-request-only and explains *the role of the AI system*, not your rejection [V] | ❌ |
| **Ghosting / responsiveness signals** | **LinkedIn, free — but PRE-APPLICATION ONLY** [V]: *"Actively reviewing candidates"*, *"Review time is typically 1 week"*, *"Responses managed off LinkedIn"* are shown on the **job post before you apply**. After applying you get only *application viewed* and *resume downloaded* — **no responsiveness data and no rejection status at all** | ❌ · **M** |
| Application-viewed / resume-downloaded signals | LinkedIn, free (view includes screening answers) [V] | ❌ |
| Candidate-side signal visible to the hirer | LinkedIn **Top Choice** — 3/month, poster sees the flag, Easy Apply only [V] | ❌ |
| Edit or withdraw a submitted application | **LinkedIn cannot** — remedy is InMail, which is Premium-gated [V] | ✅ n/a (own submissions) |

## C5. Import / export / interop
| feature | example holder | Latexy |
|---|---|---|
| LinkedIn import | Teal (ext), Kickresume (premium) [V] | ✅ archive-based |
| PDF import / parse | Kickresume, FlowCV [V] | ✅ `/formats/parse` |
| DOCX import | FlowCV [V] | ✅ |
| GitHub import (projects) | — | ✅ `/github/import-projects` |
| URL import | — | ✅ `/sources/import-url` |
| Zotero / Mendeley import | Overleaf, Curvenote [V] | ✅ |
| ORCID publication fetch | — | ✅ `/references/fetch-orcid` |
| PDF export | all | ✅ |
| DOCX export | Rezi [V]; Kickresume degrades to plain text [V]; Enhancv **refuses** [V] | ✅ |
| TXT export | Resume.io (free tier only) [V] | ✅ |
| LaTeX source export | Overleaf [V] | ✅ |
| JSON export | Reactive Resume [V] | ✅ |
| HTML / MD / YAML / XML export | HackMyResume [V] | ✅ `/formats` (6 routes) |
| Bulk export | — | ✅ `/resumes/export/bulk` |
| ePub / ODF / DocBook | LyX [V] | ❌ |
| Share link (read-only) | Resume.io [V] | ✅ `/r/[token]` |
| Public profile page | JSON Resume registry [V] | ✅ `/u/[username]` |
| Custom domain | — | ✅ `/portfolio/verify-domain` |
| Personal website generation | Kickresume (premium, 7 templates) [V] | ✅ `/generate-portfolio` |
| QR code | — | ✅ `QrCodeInserter.tsx` |
| Share-link view analytics | — | ✅ `resume_views` table |
| Google Drive export | Rezi [V] | ❌ |
| **Canva / Figma export (structured content hand-off)** | **nobody** | ✅ `GET /export/{id}/canva`, `/figma` |
| **BibTeX smart import from DOI / arXiv** | Overleaf (Dimensions) [V] | ✅ `fetch_doi`, `fetch_arxiv` |
| Reference-page generation | — | ✅ `/generate-references` |
| **SVG / JPEG export** | LiveCareer Italy only [V] | ❌ · **S** |
| Email delivery of the document | LiveCareer [C] | ❌ |
| Resume → public networking profile URL | LiveCareer (**free tier**), Zety via Bold.pro [V] | ✅ `/u/[username]` |
| Syndication to job boards (Monster/CareerBuilder) | Bold.pro [V] | ❌ — see Part D |
| Cross-document data sync (resume ↔ cover letter) | Zety, LiveCareer [V] | ➖ |
| Dropbox sync | Papeeria [V] | ✅ `/dropbox` (9 routes) |
| Full data export (GDPR) | Reactive Resume [V] | ? unverified |
| Account deletion | **no vendor documents one** | ? unverified |

## C6. Collaboration
| feature | example holder | Latexy |
|---|---|---|
| Real-time co-editing | Overleaf, Typst.app [V] | ✅ yjs |
| Comments + resolve | Overleaf [V] | ✅ `/comments/:id/resolve` |
| Margin discussions | Papeeria [V] | ➖ |
| @mentions | Overleaf [C] | ❌ |
| Track changes accept/reject | Overleaf (premium) [V] | ❌ |
| Suggesting mode | Curvenote [V] | ❌ |
| Per-collaborator permissions | Overleaf, Papeeria [V] | ✅ `/collaborators` |
| Collaborator chat | Overleaf [V] | ❌ |
| Expert / human resume review | Rezi (1/mo on Pro) [V] | ❌ |
| Peer / mentor review | — | ❌ |
| Team workspaces | Typst.app Teams [V] | ✅ `/workspaces`, `/team`, `/tenants` |
| Recruiter view | — | ✅ `/workspaces/[id]/recruiter` |
| Multi-tenancy | — | ✅ 9 routes |

## C7. Versioning
| feature | example holder | Latexy |
|---|---|---|
| Version history + restore | Overleaf [V] | ✅ `/checkpoints` |
| Named checkpoints | — | ✅ |
| Version diff | Overleaf compare [V] | ✅ `/diff-with-parent` |
| Variants / forks | — | ✅ `/fork`, `/variants` |
| Merge | — | ✅ `/merge` |
| Document branches | LyX [V] | ➖ variants |
| Per-paragraph/equation/figure versioning | Curvenote [V] | ❌ |
| Git bridge / GitHub sync | Overleaf, Typst.app [V] | ➖ GitHub import only |
| Source-level diff with markup | latexdiff v1.4.0 [V] | ➖ |
| Accept/reject on a diff | latexrevise [V] | ❌ |
| Rendered-PDF visual diff | diff-pdf (CI exit codes) [V] | ❌ |
| **Resume-version diffing as a user feature** | **nobody** | ➖ engine exists |

## C8. Compile & editor infrastructure
| feature | example holder | Latexy |
|---|---|---|
| Engine choice pdf/xe/lua | Overleaf [V] | ✅ |
| Per-resume compiler settings | — | ✅ `/resumes/:id/settings` |
| Compile timeout tiers | Overleaf 10s free / 240s paid [V] | ➖ |
| Continuous auto-compile | Papeeria [V] | ➖ |
| Stop on first error | Overleaf [V] | ❌ |
| Draft mode | Overleaf [S] | ❌ |
| Compile caching / incremental | **nobody verified** | ❌ |
| Log parsing → readable errors | all [V] | ✅ `/logs`, `/ai/explain-error` |
| Linting (ChkTeX/LaCheck) | LaTeX Workshop [V] | ✅ `LinterPanel` |
| Duplicate-label detection | LaTeX Workshop [V] | ❌ |
| SyncTeX forward + inverse | TeXstudio, LaTeX Workshop [V] | ✅ |
| Autocomplete (cmds/refs/cites) | TeXstudio `.cwl`, texlab [V] | ❌ |
| Snippets / user macros | TeXstudio, TeXmaker [V] | ✅ `/macros` |
| Symbol palette | TeXmaker (370), Overleaf (premium) [V] | ❌ · see B16 |
| **LaTeX package-manager UI** | TeXstudio (package view) [V] | ✅ `PackageManagerPanel.tsx` |
| **TikZ / diagram visual editor** | TikZiT, Mathcha [V] | ✅ `TikZEditor.tsx` |
| Keyboard-shortcuts reference panel | TeXstudio, Overleaf [V] | ✅ `KeyboardShortcutsPanel.tsx` |
| Compile queue priority by plan | Overleaf (paid faster) [V] | ✅ `get_task_priority()` |
| Compile error history | — | ✅ `/resumes/{id}/error-history` |
| **Regex-aware find & replace** | TeXstudio, VS Code [V] | ❌ · **S** — see B19.14 |
| **In-app package documentation lookup** | TeXstudio (texdoc) [V] | ❌ · **S** — see B19.15 |
| Outline navigator | LyX, tinymist [V] | ❌ |
| Code folding | TeXstudio [V] | ❌ |
| Project-wide search | TeXmaker [V] | ✅ `/resumes/search` |
| Word count | LaTeX Workshop [V] | ❌ |
| Multi-cursor | TeXstudio, VS Code [V] | ❌ |
| vim/emacs keybindings | Overleaf, Typst.app [V] | ❌ |
| Thesaurus | TeXstudio, LyX [V] | ❌ |
| Custom dictionaries | Overleaf [C] | ❌ |
| Scripting engine | TeXstudio JS macros [V] | ❌ |
| LSP | texlab, tinymist [V] | ❌ |
| Docker/remote compilation | LaTeX Workshop [V] | ✅ (is the architecture) |
| Presentation mode | Typst.app, TeXstudio [V] | ❌ |

## C9. Accessibility & i18n
| feature | example holder | Latexy |
|---|---|---|
| **Tagged PDF / PDF-UA** | Overleaf (2026-01), Typst 0.14+ [V] | ❌ **nobody in resumes** |
| Automatic MathML math tagging | LuaLaTeX + luamml [V] | ❌ |
| Alt text / artifact markup | LaTeX, Typst [V] | ❌ |
| Table header/data-cell roles | LaTeX, Typst [V] | ❌ |
| Per-region language declaration | `\DocumentMetadata{lang=}` [V] | ❌ |
| Accessible icon alt-text | AltaCV `accsupp` [V] | ❌ |
| CJK support | ctex, xeCJK, luatexja; brilliant-CV [V] | ❌ |
| RTL / Arabic / Hebrew | bidi; brilliant-CV [V] | ❌ |
| **Devanagari / Indic** | **nobody** | ❌ |
| Multilingual doc in one file | brilliant-CV per-profile [V] | ❌ |
| EU-language CV standard | europecv (all EU + Catalan) [V] | ❌ |
| UI localisation | Reactive Resume (Crowdin) [V] | ❌ |
| Multilingual skill taxonomy | ESCO (28 langs, API) [V] | ❌ |
| Screen-reader friendly output | — | ❌ |
| Dyslexia-friendly fonts / high contrast | — | ❌ |
| Culture-specific formats (rirekisho, Lebenslauf) | **nobody** | ❌ |

## C10. Platform, growth, monetisation
| feature | example holder | Latexy |
|---|---|---|
| Public API | **nobody** | ✅ v1, 5 routes |
| API keys + rate limiting | — | ✅ |
| CLI / TUI | **nobody** | ✅ 33 commands |
| Reusable GitHub Action | **nobody** | ❌ |
| Self-hosting | Reactive Resume (MIT), Overleaf CE [V] | ❌ |
| SSO / LDAP | Overleaf Server Pro, Typst On-Prem [V] | ❌ |
| Sandboxed compiles | Overleaf Server Pro [V] | ➖ Modal isolation |
| Admin panel | Overleaf Server Pro [V] | ✅ `/admin` |
| Feature flags | — | ✅ 32, all on |
| Plan-based feature gating | all competitors | ➖ built, **disabled** |
| Quota metering | Rezi (3 lifetime DLs) [V] | ✅ |
| Student free tier | **Kickresume: Premium free w/ verification** [V] | ➖ ₹299 Student |
| Lifetime plan | Rezi $149, Novoresume $139.99 [V] | ❌ |
| Weekly plan | Resume.io ₹249, Teal $13 [V] | ❌ |
| Annual discount | all [V] | ➖ partial |
| BYOK tier | **nobody** | ✅ ₹199 |
| Browser extension | Simplify, Huntr, Jobscan, Careerflow [V] | ❌ |
| Mobile app / PWA | Kickresume (premium) [V] | ❌ |
| Offline mode | desktop editors [V] | ❌ |
| Passkey / 2FA | Reactive Resume [V] | ❌ |
| Email notifications | most [C] | ✅ completion, failure, share-view, and weekly-digest delivery |
| Browser push notifications | — | ✅ `usePushNotifications` + permission flow |
| White-label / careers-centre edition | — | ❌ |
| Referral / affiliate programme | several [S] | ❌ |
| Template marketplace | Typst Universe, npm themes [V] | ➖ `/snippets` upvote |
| Per-document micro-charges on top of a subscription | LiveCareer ($0.45/extra download) [V] | ❌ — see Part D |
| Four-week billing cycle (13/yr) | Zety, LiveCareer [V] | ❌ — see Part D |
| Published accessibility statement | Zety (partial WCAG A) [V]; LiveCareer **none** [V] | ❌ · **S** |
| Named screen-reader support (NVDA/VoiceOver/TalkBack) | Zety [V] | ❌ |
| Dedicated accessibility support line | Zety (24/7) [V] | ❌ |
| Multi-region phone support | both Bold brands, 6+ countries [V] | ❌ |
| Self-serve CCPA "do not sell" form, no login | Zety [V]; LiveCareer's route **unverifiable** [V] | ? |
| Self-serve account deletion | both — but **login-walled and retains an archival copy** [V] | ? unverified |
| Human resume-writing service | LiveCareer [C]; Rezi (1 expert review/mo on Pro) [V]; Zety explicitly **none** [V] | ❌ — see Part D |

---

## C11. Category-wide verified negatives — nine mid-tier builders, checked individually

Absences confirmed one product at a time across VisualCV, Standard Resume, Novoresume, Reactive Resume, Rezi, Teal, Kickresume, Enhancv and Resume.io [V]. A verified negative is worth more than a feature idea: it is a gap with evidence that nobody has closed it.

| absence | scope | Latexy read |
|---|---|---|
| **No accessibility statement** | **all nine** | Cheap to be first. Pairs with tagged-PDF work in B9c — accessible *output* plus an accessible *product* is a coherent story, and PDF/UA is a procurement requirement for public-sector and university buyers |
| **No academic CV support** — zero ORCID, zero publication importers | **all nine** | **See B24.** Our single best-fitting gap |
| **No documented public API** | eight of nine (only Reactive Resume) | Pairs with B23 |
| **Non-Latin script** | only two of nine | See B10 |
| **Offline editing** | only one of nine (Resume.io) | Not a priority; noted for completeness |
| **Print margin control** | only Teal, per-side 0.25–2 with Letter/A4 | Most builders expose *no* margin control at all. A LaTeX product has this for free |

**Three premises in the research brief failed verification and are recorded as corrections** [V]: Kickresume has **no** university edition (only an ISIC/UNiDAYS student discount — no admin dashboard, no seat management, corroborated three ways); Enhancv's photo background removal has **no first-party evidence** (the sole official photo article documents upload and hide only); Novoresume's one-page content-fit slider is **unconfirmed** — page count there is a *paywall*, not a design control.

**Ideas worth stealing, none of which require our engine to change:**
- **Teal's Resume Syncing** — one master career history, N derived resumes, propagate-or-diff on every edit. Solves "update your job title in twelve resumes," which nobody else touches. We already have the data model for it.
- **Teal's Auto-Select** — AI that *de-activates* existing content judged irrelevant to a target job. The inverse of every competitor's generate-more reflex, and better aligned with a one-page constraint.
- **Reactive Resume's Semantic CSS** — a sandboxed styling DSL whose selectors address *resume semantics* (`section[type="experience"]`, `field[name="position"]`) rather than template DOM, with real pagination primitives (`break-inside`, `orphans`, `widows`). **This is a re-invention of what LaTeX already is** — read it as validation that the abstraction is right, not as something to copy.
- **Novoresume's `[X]` placeholders** — generated achievement bullets ship with literal `[X]` slots the user must fill: a systematised refusal to fabricate metrics. Directly relevant to our own LLM output.
- **VisualCV's Career Journal** — dated achievement capture by *replying to a prompt email*. A continuous-capture loop that is not a resume feature at all.

# Part D — Deliberately not recommended

Listed because a competitor has them, per the brief. **Reasons stated so the decision can be revisited if the reasoning changes.**

| feature | who has it | why not |
|---|---|---|
| **"Scores like a real ATS" marketing** | Kickresume [V quote], Jobscan [C] | Unverifiable, and **falsifiable**: Greenhouse's docs say its matching *"does not auto-reject or auto-advance any candidate"* [V]; the same resume scores 97/79/79 across three tools [V]. The sophisticated segment already reads it as a tell — r/EngineeringResumes' wiki never uses the phrase [V]. Ship the parse instead. |
| **Paywalling PDF export** | Resume.io (TXT only free) [V] | Most-complained-about thing in the category; **core allegation in active federal litigation** (*Rocket Resume v. BOLD*, 5:26-cv-02852) [V]; Bold LLC sits at **1.12/5 across 78 BBB reviews** with 244 complaints [V]. For a LaTeX product the export *is* the proof of quality. |
| **Watermarking free output** | Enhancv [V] | Same reasoning, milder. Hides the differentiator. |
| **Download quotas** | Rezi (3 lifetime) [V] | Same. Meter AI spend, which the quota table already does. |
| **Auto-renewing "7-day free" trials** | Enhancv [V], Resume.io (self-contradictory terms) [V] | Jobscan refunds only within **2 calendar days** minus a **3.5% fee** [V]; Rezi refunds nothing [V]. This is the reputational hole the category is in. |
| **Inflated template counts** | Enhancv "hundreds" while selling "thousands of design options" separately [V] | 63 genuine beats 5 (Rezi) and matches FlowCV's 50+. Counting colour variants is a tell. |
| **Bulk / automatic job application** | auto-appliers [C]; Bold runs one as a separate brand, **Sonara** [C] | Now backed by first-party enforcement detail, not just principle. **LinkedIn rate-limits Easy Apply three ways** [V]: an undisclosed daily cap resetting end-of-day UTC; a **velocity trigger** that pauses Easy Apply if you submit too fast, explicitly framed as anti-bot; and a **reduced daily cap when activity "seems inauthentic,"** restorable only by verifying your account. **Automation tools are a named trigger for invitation limits**, and those limits are **identical for Basic and Premium — you cannot pay them away** [V]. Building bulk-apply means building something whose failure mode is getting your users' accounts throttled. Latexy's `/apply` is deliberate per-application submission — keep it that way. |
| **Job board / aggregation** | Simplify, Huntr [V] | Two-sided marketplace, entirely different business. Simplify monetises employer postings [V]. **And it now carries regulatory exposure**: New York **S8877** passed both chambers 2026-06-02 and awaits signature; it binds *"third-party job-posting entities"* — platforms, not just employers — requiring bold-capitals vacancy disclosures, two-week takedown of filled roles, and **$2,500 per ad per platform, $5,000 if uncorrected in 30 days, doubling every 30 days thereafter** [V]. Hosting other people's postings would import that liability. |
| **"Humanise" / AI-detection evasion** | various [C] | Adversarial, brittle, reputationally risky. |
| **Parse-rate leaderboards** | a widely-circulated Reddit post [C] | Methodology undisclosed, author was promoting a competing standard, top recruiter reply rebuts it [V]. Don't cite, don't imitate. |
| **JSON Resume as the internal model** | — | Schema frozen at v1.0.0 since **2014**, CLI archived, no notion of variants, layout intent, provenance or per-variant visibility [V]. Support as *interchange* (B14); don't build on it. |
| **WASM LaTeX as the primary compile path** | resumeforfree (Typst) [V] | **SwiftLaTeX's package mirror is NXDOMAIN** [V]; texlive.js abandoned 2017 [V]; TeXlyre-busytex needs 122–432 MB [C]. Optional offline preview at most. |
| **Four-week billing cycles** | Zety, LiveCareer [V] | 13 charges a year presented as "monthly". Auto-renewal is the dominant complaint theme in every review source for both brands [V]. |
| **Per-document micro-charges on a subscription** | LiveCareer ($0.45/extra download; trial meters downloads, prints and emails as interchangeable units) [V] | Charging again for a document the user already paid to build is the same trust failure as paywalling export, metered. |
| **Job-board syndication of user documents** | Bold.pro → Monster, CareerBuilder [V] | Zety's privacy policy discloses resume data may go to *"employers, recruiters or job posting third-party websites, third parties in the career building industry"* — **a stated category with no partner ever named** [V]. Latexy's counter-position is BYOK and self-host. |
| **Training models on user resumes by default** | **LinkedIn** — *"Share resume data with hirers"* is **ON by default**, parsed resume data goes to recruiters, recruiter search can surface you from resumes saved in the **past 2 years**, and **your resume trains LinkedIn's content-generating AI unless you opt out** [V] | This is precisely the position BYOK and self-hosting argue against. If Latexy ever trains on user content, it forfeits the one thing its architecture makes credible. Default-off, explicit, per-user. |
| **Session-recording on document-editing pages** | LiveCareer runs Microsoft Clarity, Inspectlet and Qualaroo [V] | PII-bearing keystroke capture on a career document. Do not add session recording to the editor, whatever the product-analytics case. |
| **Bundling users into a public directory profile** | Bold.pro, a paid-tier line item on both brands [V] | Buying a resume builder silently enrolls the user in a directory-listed public profile. |
| **Selling visually heavy templates while warning they break ATS** | both Bold brands [V] | Self-undermining. Either the template is ATS-safe or it is sold as a design piece — not both. |
| **Unfootnoted outcome statistics** | Zety ("30% faster", "42% more responses"); LiveCareer ("48 days faster", basis = **a survey of 258 users**) [V] | Latexy can substantiate parse claims. Don't dilute that with numbers it cannot defend. |
| **Human resume-writing services** | LiveCareer [C], Rezi (1 review/mo) [V] | Services business, not software: headcount-bound, unscalable, and Zety explicitly declines it [V]. |
| **Markdown-based authoring** | resume.lol, resume-ai [C] | LaTeX **is** the product and the differentiator; a second authoring syntax splits the template model, the linter and the AI prompts for no gain. Users who want Markdown are better served by JSON Resume interchange (B14). |
| **Locked grid (prevents layout breakage)** | LiveCareer [S] | A deliberate ATS-safety tradeoff that forfeits exactly what we sell. Our answer to layout breakage is a compiler and a linter, not a cage. Note LiveCareer simultaneously sells visually heavy templates while warning they break ATS — the incoherence Part D already flags. |
| **Mock interview (voice/video)** | Careerflow, Final Round AI [C] | A different product with different infrastructure (real-time audio, transcription, latency budgets) and no shared surface with a document compiler. **B11b** covers the defensible slice: preparing users for LinkedIn's AI screening. Teal's Mock/Coach modes are the benchmark if this is ever revisited. |
| **Agent skill packaging (`npx skills add`)** | RenderCV [V] | **B23 (MCP server) supersedes it.** MCP is the interoperable, multi-client standard with two competitors already shipping; a bespoke skill package would serve one client and duplicate the same tool layer. |
| **MCP server (third-party wrapper)** | workopia-mcp, resumake-mcp [V] | Not a feature to build — it is what *others* did to products lacking a first-party server. **B23** makes it moot. |
| **Multi-region phone support** | both Bold brands, 6+ countries [V] | A services business: headcount-bound and unscalable, and Zety explicitly declines resume-writing services for the same reason. **B56** (accessibility support) is the part with a real obligation behind it. |
| **beamer-based resume templates** | — | Incompatible with PDF tagging [V]. Forecloses B9. |
| **XeLaTeX as the default engine** | Awesome-CV requires it [V] | **XeLaTeX does not support PDF tagging** [V]. If B9 matters, default to LuaLaTeX. Keep XeLaTeX available. |


### Actionable items extracted from Part D

Most of Part D is a set of decisions **not** to build, and those correctly have no issue — filing "do not paywall PDF export" as a task would be nonsense. But **five rows hide real engineering or verification work**, and one of them found a live problem:

| id | task | issue |
|---|---|---|
| **D1** | Default the compiler to LuaLaTeX, keep XeLaTeX available | [1407](https://github.com/sanskarpan/Latexy/issues/1407) |
| **D2** | Guard against beamer-based templates (breaks PDF tagging) | [1408](https://github.com/sanskarpan/Latexy/issues/1408) |
| **D3** | Verify and document that user resumes never train models; keep it default-off | [1409](https://github.com/sanskarpan/Latexy/issues/1409) |
| **D4** | Verify no session recording on editor surfaces, and add a guard | [1410](https://github.com/sanskarpan/Latexy/issues/1410) |
| **D5** | Audit our own marketing copy for unsubstantiated and ATS-emulation claims | [1411](https://github.com/sanskarpan/Latexy/issues/1411) |

**D5 originally found a real violation:** the gallery advertised 147 templates while many rows were fixtures. The fixtures have been removed, `Clean Simple` is healthy, and #1687 makes the 56-file source catalog and its generated assets part of automatic production delivery.

The remaining **24 Part D rows stay as refusals with stated reasons** — that is their purpose. Each reason is recorded so the decision can be revisited if the reasoning changes, which is not the same as being a backlog item.

---

# Part E — Open research

Honest gaps. Each would change a recommendation above.

1. ~~Does tagged PDF help ATS parsers?~~ **RESOLVED — no.** Every documented extractor reads a flat text layer; no parser or ATS vendor mentions tags; no compliance driver reaches a submitted resume; and a blindness research centre's own resume guidance never mentions tagged PDF. See B9. **The ATS framing is withdrawn**; the accessibility framing survives at P2.
2. **Do Indian job-seekers want non-Latin-script resumes?** B10 assumes yes. Unvalidated.
3. **Does parse fidelity affect outcomes?** One experienced recruiter says no — *"when it does [butcher parsing] we just open the actual resume itself"* [V]. If representative, B11's value drops sharply.
4. ~~ATS-side and parser-side schemas~~ **RESOLVED.** Eight schemas verified field-by-field (Textkernel, RChilli, Affinda, HireAbility; Greenhouse, SmartRecruiters, Lever, Ashby) → the six-group convergent field set in **B10c**, plus Textkernel's quality-code table in **B9b**. **Still open:** **Workday** (`apidocs.workday.com` does not resolve; REST directory is a JS SPA behind Community auth) and **DaXtra** (no public schema; docs subdomains dead or 403). Both are [C] marketing claims only.
5. ~~Devanagari/Indic LaTeX specifics~~ **RESOLVED.** LuaLaTeX + `luahbtex` + HarfBuzz (XeLaTeX shapes fine but tagpdf doesn't recommend it); **babel ≥24.14 over polyglossia**; `texlive-lang-indic` does not exist in Debian and the macros are already in packages we ship; **~52 MB minimum**. See B10. **Still untested: tagged PDF + Devanagari text extraction** — no tagpdf issue mentions Indic scripts either way.
6. **Whether BYOK or a TUI monetises.** No revenue data, case study or independent analysis found for either.
7. **Canva / Figma PDF exports** — **partially resolved, see B9c.** Canva's default export appears to retain a text layer; the documented hazard is a separate **"Flatten PDF"** checkbox that Canva says produces a static image. Figma's docs claim text stays selectable while five years of user reports say it is outlined — unreconciled. **Still open:** the decisive `pdffonts`/`pdftotext` bake-off across Canva (±flatten), Figma and Express. Needs accounts we do not have. **Our own output is now measured and passes** (B9c).
8. **HR Open "Trusted Career Profile" and Europass/ELM object shapes** — landing pages reached, specs not.
9. **Latexy's own GDPR posture** — data export and account-deletion endpoints still not verified. Worth prioritising now that C11 shows the category is weak here (Enhancv requires an email to a human; only Reactive Resume and Novoresume are strong), making it a cheap differentiator rather than table stakes.
10. **Group C of the editor research** (OpenAI/Canva/Notion/Microsoft) was almost entirely blocked by 403/404 and should be re-run.
11. **Whether LinkedIn's classic Interview Preparation product still exists** as a distinct surface — `/interview-prep/` is login-walled and absent from every current help index. Leaning absorbed into AI insights + Learning coaching + practice AI interview [V on what occupies the slot]. Affects how B11b is positioned.
12. **LinkedIn's current Commercial Use Limit numbers** — deliberately unpublished.
13. **Simplify and Careerflow depth.** Their entries rest on first-party sources (Simplify's own supported-ATS page; Careerflow's autofill list, which **contradicts its own marketing by omitting Workday**), so the gap is depth, not substance.
14. ~~The mid-tier builders' long tail is thin~~ **RESOLVED — the re-run completed.** All nine products (VisualCV, Standard Resume, Novoresume, Reactive Resume, Rezi, Teal, Kickresume, Enhancv, Resume.io) were enumerated at editor level: undo/version history, keyboard shortcuts, page-break control, photo handling, section limits, margins, i18n, mobile/extension presence, GDPR posture and academic support. Results are in **C11**, **B23** and **B24**. Notable products of that pass: **Standard Resume is dormant** (last changelog Sep 2021, job board returns nothing); **two competitors ship MCP servers**; **nobody has an accessibility statement or real academic-CV support**. Three premises in the brief failed verification — recorded in C11.

**Two claims of mine that this research corrected**, recorded so they are not reintroduced:
- I wrote that **nobody** ships rejection or outcome feedback, then over-corrected to say LinkedIn fills the gap. **Both were wrong.** LinkedIn's responsiveness signals — review recency, typical response time, *"Responses managed off LinkedIn"* — are **pre-application only**, shown on the job post before you apply. After you apply it shows *viewed* and *downloaded* and nothing else: no responsiveness data, no rejection status, no reason. So the post-application gap is **fully intact**, and is now verified across SmartRecruiters, Greenhouse, Handshake and Ashby rather than asserted.
- I treated the archive-based LinkedIn import as a friction choice. It is **the only compliant route in existence** — LinkedIn's self-serve API has no profile-read permission at any tier.

---

# Part F — Legacy catalog reconciliation

**Why this exists.** The question was whether `docs/FEATURES-2026-07-legacy.md` is fully covered by this file. It was **not**. All **92** legacy entries are mapped below; every row was checked against a route path or a component file, not against memory.

**Result:**

| verdict | count | meaning |
|---|---|---|
| ✅ shipped, already covered | 50 | correctly marked before this audit |
| 🔴 **shipped but was missing → now ✅** | 19 | **the audit's main finding** — see **A2b** |
| 🔴 **was missing → now backlog** | 3 | genuine gaps this file had dropped → **B25**, **B19.14**, **B19.15** |
| 🟠 partial | 4 | exists but incomplete; caveats stated |
| ⬜ backlog | 12 | not shipped, correctly tracked |
| 🚫 not recommended | 4 | deliberate, reason in Part D |

**Coverage before this audit: 71/92 (77%). After: 92/92.** The 18 recovered shipped features are the substantive finding — this catalog was understating the product, which is the same failure mode it criticised the legacy file for, in the opposite direction.

**Nothing in the legacy file is now unaccounted for.** Its per-feature "What to build" prose remains the better reference for unshipped items; that is why it is retained rather than deleted.

| legacy | feature | legacy pri | verdict | where it lives now |
|---|---|---|---|---|
| 1.1 | Template Gallery (50+ Templates) | P0 | ✅ shipped | **56 source-owned templates**: 51 résumé/academic templates and 5 Beamer presentations; production synchronization is enforced by #1687 |
| 1.2 | Document Version History + Diff | P0 | ✅ shipped | already covered |
| 1.3 | Compile-on-Save / Auto-Compile | P0 | ⬜ backlog | B19.2 → **B19.2** [#1352](https://github.com/sanskarpan/Latexy/issues/1352) |
| 1.4 | Multiple LaTeX Compilers (XeLaTeX, LuaLaTeX) | P1 | ✅ shipped | already covered |
| 1.5 | Shareable Resume Links (Read-Only PDF URL) | P1 | ✅ shipped | already covered |
| 1.6 | Compile Timeout per Plan | P1 | ⬜ backlog | C8 ➖ timeout tiers → **B33a** [#1368](https://github.com/sanskarpan/Latexy/issues/1368) |
| 1.7 | Compilation History Diff Viewer | P1 | ⬜ backlog | B21 → **B21** [#1305](https://github.com/sanskarpan/Latexy/issues/1305) |
| 1.8 | Project-Wide Search | P1 | ✅ shipped | already covered |
| 1.9 | BibTeX Smart Import (DOI / arXiv) | P1 | 🔴 was missing → now ✅ | A2b · `fetch_doi`/`fetch_arxiv` |
| 1.10 | Spell Check & Grammar | P2 | ✅ shipped | already covered |
| 1.11 | Symbol Palette | P2 | ⬜ backlog | B16 → **B16** [#1300](https://github.com/sanskarpan/Latexy/issues/1300) |
| 1.12 | GitHub / Git Integration | P2 | ⬜ backlog | C7 ➖ GitHub import only → **B32** [#1314](https://github.com/sanskarpan/Latexy/issues/1314) |
| 1.13 | Compiler Settings per Resume | P2 | ✅ shipped | already covered |
| 1.14 | Project-Level Tags & Organization | P2 | 🔴 was missing → now ✅ | A2b · `/tags` |
| 1.15 | Real-Time Collaboration (Multi-Cursor CRDT) | P2 | ✅ shipped | already covered |
| 1.16 | Track Changes (Accept/Reject) | P2 | ⬜ backlog | B20 → **B20** [#1304](https://github.com/sanskarpan/Latexy/issues/1304) |
| 1.17 | Dropbox / Cloud Storage Sync | P3 | ✅ shipped | already covered |
| 1.18 | Zotero / Mendeley Reference Import | P2 | ✅ shipped | already covered |
| 1.19 | WYSIWYG / Rich Text Editor Mode | P3 | ✅ shipped | already covered |
| 1.20 | Mobile App (PWA First, Then Native) | P3 | ⬜ backlog | P3 PWA → **B36** [#1318](https://github.com/sanskarpan/Latexy/issues/1318) |
| 2.1 | Cover Letter Generator | P0 | ✅ shipped | already covered |
| 2.2 | Resume Variant / Fork System | P0 | ✅ shipped | already covered |
| 2.3 | Real-Time ATS Score (Debounced) | P0 | ⬜ backlog | C3 ➖ debounced scoring → **B28a** [#1366](https://github.com/sanskarpan/Latexy/issues/1366) |
| 2.4 | Job Application Tracker | P1 | ✅ shipped | already covered |
| 2.5 | LinkedIn Profile Import (Structured) | P1 | ✅ shipped | already covered |
| 2.6 | Interview Question Generator | P1 | ✅ shipped | already covered |
| 2.7 | Multi-Dimensional Score Card | P1 | ⬜ backlog | C3 (score exists; multi-dimensional card partial) → **B28b** [#1367](https://github.com/sanskarpan/Latexy/issues/1367) |
| 2.8 | Email Notifications | P1 | ✅ shipped | Resend/SMTP delivery, per-trigger preferences, Modal parity, and deduplicated/debounced triggers → **B29** [#1311](https://github.com/sanskarpan/Latexy/issues/1311) |
| 2.9 | Resume View Analytics (Link Tracking) | P2 | ✅ shipped | already covered |
| 2.10 | Multilingual Resume Translation | P2 | ✅ shipped | already covered |
| 2.11 | Salary Estimator from Resume | P2 | ✅ shipped | already covered |
| 2.12 | Industry-Specific ATS Calibration | P2 | 🔴 was missing → now ✅ | A2b · `industry_ats_profiles.py` |
| 2.13 | Anonymous Resume Mode (Blind Review) | P2 | 🔴 was missing → now backlog | **B25** (new) → **B25** [#1309](https://github.com/sanskarpan/Latexy/issues/1309) |
| 2.14 | Resume Freshness Tracker | P2 | 🔴 was missing → now ✅ | A2b · `freshness_status` |
| 2.15 | Bulk / Batch Resume Export (ZIP) | P2 | ✅ shipped | already covered |
| 3.1 | AI LaTeX Error Explainer | P0 | ✅ shipped | already covered |
| 3.2 | Real-Time Page Count Warning | P0 | 🟠 partial | ➖ `page_count` extracted in `latex_worker`, not surfaced as a warning → **B30** [#1312](https://github.com/sanskarpan/Latexy/issues/1312) |
| 3.3 | Font & Color Visual Editor | P1 | 🔴 was missing → now ✅ | A2b · `DesignPanel.tsx` |
| 3.4 | Developer Public API | P1 | ✅ shipped | already covered |
| 3.5 | AI Bullet Point Generator | P1 | ✅ shipped | already covered |
| 3.6 | AI Writing Assistant (In-Editor) | P1 | 🟠 partial | ➖ no AI chat over the document (C2) → **B31** [#1313](https://github.com/sanskarpan/Latexy/issues/1313) |
| 3.7 | AI Professional Summary Generator | P1 | ✅ shipped | already covered |
| 3.8 | AI Proofreader (Writing Quality) | P1 | ✅ shipped | already covered |
| 3.9 | ATS Simulator + PDF Parse Pre-flight Check | P2 | ✅ shipped | already covered |
| 3.10 | One-Click Resume Tailoring | P1 | ✅ shipped | already covered |
| 3.11 | Before/After Optimization Comparison | P1 | 🔴 was missing → now ✅ | A2b · `VersionHistoryPanel.tsx` |
| 3.12 | Resume Heatmap (Recruiter Attention Prediction) | P2 | 🔴 was missing → now ✅ | A2b · `heatmap-generator.ts` |
| 3.13 | Resume Score History Chart | P2 | 🔴 was missing → now ✅ | A2b · `/score-history` |
| 3.14 | AI Section Reordering | P2 | ✅ shipped | already covered |
| 3.15 | Industry Keyword Density Map | P2 | 🔴 was missing → now ✅ | A2b · `/ats/keyword-density` |
| 3.16 | Resume Age Analysis | P2 | ✅ shipped | already covered |
| 3.17 | AI Custom Optimization Persona | P2 | ✅ shipped | already covered |
| 3.18 | Smart Date Formatting Standardizer | P2 | ✅ shipped | already covered |
| 3.19 | Publication List Auto-Generator | P2 | ✅ shipped | already covered |
| 3.20 | Resume Confidence Score | P2 | ✅ shipped | already covered |
| 3.21 | Career Path Visualization + Skills Gap Analysis | P3 | ✅ shipped | already covered |
| 3.22 | Resume Benchmarking (Anonymous Percentile) | P3 | ⬜ backlog | C3 ❌ benchmark vs applicants → **B34** [#1316](https://github.com/sanskarpan/Latexy/issues/1316) |
| 4.1 | LaTeX Package Manager UI | P1 | 🔴 was missing → now ✅ | A2b · `PackageManagerPanel.tsx` |
| 4.2 | LaTeX Linter (Real-Time Best Practices) | P1 | ✅ shipped | already covered |
| 4.3 | Smart Code Snippet Auto-Insert | P1 | ✅ shipped | already covered |
| 4.4 | Regex-Aware Find & Replace | P1 | 🔴 was missing → now backlog | **B19.14** (new) → **B19.14** [#1364](https://github.com/sanskarpan/Latexy/issues/1364) |
| 4.5 | LaTeX Documentation Lookup Panel | P2 | 🔴 was missing → now backlog | **B19.15** (new) → **B19.15** [#1365](https://github.com/sanskarpan/Latexy/issues/1365) |
| 4.6 | Keyboard Shortcuts Reference Panel | P2 | 🔴 was missing → now ✅ | A2b · `KeyboardShortcutsPanel.tsx` |
| 4.7 | LaTeX Snippet Marketplace | P3 | ✅ shipped | already covered |
| 4.8 | Keyboard Macro System | P3 | ✅ shipped | already covered |
| 4.9 | TikZ / Diagram Visual Editor | P3 | 🔴 was missing → now ✅ | A2b · `TikZEditor.tsx` |
| 4.10 | QR Code Auto-Inserter | P2 | ✅ shipped | already covered |
| 4.11 | Resume Template Customizer | P2 | 🔴 was missing → now ✅ | A2b · `TemplateCustomizerPanel.tsx` |
| 4.12 | Contact Info Formatter | P2 | ✅ shipped | already covered |
| 4.13 | Browser Push Notifications | P2 | 🔴 was missing → now ✅ | A2b · `usePushNotifications` + `Notification.requestPermission()` — **shipped since `308b7513`**; [#1213](https://github.com/sanskarpan/Latexy/issues/1213) closed as stale |
| 5.1 | Advanced Subscription Tiers | P1 | ⬜ backlog | B3 + B6 → **B57b** [#1406](https://github.com/sanskarpan/Latexy/issues/1406) |
| 5.2 | Team / Agency Workspace | P2 | ✅ shipped | already covered |
| 5.3 | Custom Domain Resume Hosting | P2 | ✅ shipped | already covered |
| 5.4 | White-Label for Agencies / Career Centers | P3 | ⬜ backlog | C10 ❌ white-label → **B37a** [#1370](https://github.com/sanskarpan/Latexy/issues/1370) |
| 5.5 | Resume-to-Portfolio Site | P2 | ✅ shipped | already covered |
| 5.6 | Job Board URL Scraper | P1 | ✅ shipped | already covered |
| 5.7 | Multi-Resume Merge | P2 | ✅ shipped | already covered |
| 5.8 | Reference Page Generator | P2 | 🔴 was missing → now ✅ | A2b · `/generate-references` |
| 5.9 | Watermark Control | P2 | 🚫 not recommended | Part D — watermarking free output — **no issue, by design** |
| 5.10 | Compile Queue Priority | P1 | 🔴 was missing → now ✅ | A2b · `get_task_priority()` |
| 5.11 | Presentation / Beamer Support | P3 | 🚫 not recommended | Part D — beamer breaks tagging (guard: D2) — **no issue, by design** |
| 5.12 | Smart Import from Resume Builders | P2 | 🟠 partial | ➖ `/sources/import-url` + LinkedIn only; no competitor-specific importers → **B35** [#1317](https://github.com/sanskarpan/Latexy/issues/1317) |
| 5.13 | One-Click Job Application Integration | P3 | ✅ shipped | already covered |
| 5.14 | Recruiter / Agency View | P2 | ✅ shipped | already covered |
| 5.15 | Resume Collaboration Comments | P2 | ✅ shipped | already covered |
| 5.16 | Bulk Apply Package | P2 | 🚫 not recommended | Part D — bulk apply throttles user accounts — **no issue, by design** |
| 5.17 | Dark Mode PDF Preview | P2 | 🚫 not recommended | C1 ❌ dark-mode viewer → **B43** [#1325](https://github.com/sanskarpan/Latexy/issues/1325) |
| 5.18 | Compile Error History | P3 | 🔴 was missing → now ✅ | A2b · `/error-history` |
| 5.19 | Print Preview Mode | P3 | 🔴 was missing → now ✅ | A2b · `lib/print-preview.ts` |
| 5.20 | Export to Canva / Figma | P3 | 🔴 was missing → now ✅ | A2b · `/export/{id}/canva`+`/figma` |
| 7.1 | Academic CV → Industry Resume Conversion | P1 | ✅ shipped | already covered |
| 7.2 | DOCX Export Quality (Macro-Aware Conversion) | P1 | ✅ shipped | already covered |
