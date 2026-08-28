# PRD: Input-Driven, Collaborative Resume Optimization

- **Status:** Core collaborative flow shipped; measurement/guardrail follow-ups remain
- **Date:** 2026-08-02
- **Reconciled:** 2026-08-28 against current `main`
- **Owner:** TBD
- **Tier:** Core UX (applies to all optimize users; some steps AI-tier)
- **Related:** [External Sources → Resume PRD](2026-08-02-external-sources-to-resume.md)

---

## Implementation reconciliation (2026-08-28)

The central product direction in this PRD is now implemented:

- `GuidedIntakePanel` captures industry, seniority, tone, emphasize, and
  downplay inputs and the backend threads all five into the optimization prompt.
- `POST /optimize/segment-changes` produces deterministic change hunks and
  `POST /optimize/apply-changes` reconstructs only the accepted set.
- `ChangeReviewModal` supports accept, reject, accept-all, reject-all, and local
  editing of each proposed hunk before apply.
- Optimization output stays staged on `/try` and the authenticated editor until
  explicit approval; completing a stream no longer overwrites the document.
- The writing assistant exposes steer/regenerate-with-a-note and keeps progress
  or logs separate from the final user decision.

The review atoms are derived by a deterministic server-side diff over original
and optimized LaTeX rather than requiring the LLM to emit trustworthy offsets.
This is safer than the original output-contract proposal and preserves edited
hunks during reconstruction. Remaining work in this document is product
measurement, density/parse-clean guardrails, and deciding whether review should
be the default entry path everywhere.

## 1. Summary

Shift resume optimization from **"AI auto-rewrites the whole document, take it or leave it"** to **"AI drafts, you direct and approve."** Concretely: a **per-change accept/reject/edit review layer**, preceded by a **short guided-intake step**, with a **one-line rationale** on each suggested change, and (later) **steer-and-regenerate** controls. This makes users feel heard, improves actual output quality, and — because none of the market's resume tools have a clean Grammarly-style per-change review — it's a differentiator Latexy is uniquely positioned to build (the diff/variants/checkpoint machinery already exists).

## 2. Problem & motivation

Founder's insight: today Latexy **forces** ATS-driven changes onto users; they'd trust and value the product more if their **input were respected first**. This matches the research:
- Full auto-rewrite is the pattern users resent; the best-reviewed competitor UX (Teal) sits on the **suggest + per-item control** side, and Rezi explicitly applies changes section-by-section "to avoid overwhelming rewrites."
- Human-in-the-loop research: "when behavior is predictable and control is clear, people lean in rather than work around the system"; override/undo mechanisms restore trust.
- For a document as personal as a resume, **ownership drives trust and retention** — full automation maximizes speed but minimizes ownership.

## 3. Goals / Non-goals

**Goals**
- Make AI edits feel collaborative (accept/reject/edit per change), not imposed.
- Respect and *reflect back* user direction (role, seniority, tone, what to emphasize/downplay).
- Keep real ATS value while avoiding keyword-stuffing harm.
- Reuse existing diff/variants/checkpoint/request-field infrastructure — mostly UX sequencing, not a rebuild.

**Non-goals**
- Not removing the fast one-shot "optimize everything" path — keep it as an option for users who want speed.
- Not a full conversational editor rebuild.
- Not over-asking: intake stays short (progressive disclosure).

## 4. Current state (reconciled with shipped code)

The optimize flow accepts rich direction, stages the draft, and provides
selective review before apply:

| Thing | Status | Location |
|---|---|---|
| Request fields: `job_description`, `optimization_level`, `industry`, `target_sections`, `custom_instructions`, `persona`, `model` | **EXISTS** (input plumbing is end-to-end) | `JobSubmissionRequest` `job_routes.py:160-174` |
| Prompt threading of level/JD-keywords/target_sections/custom_instructions/persona | **EXISTS** | `orchestrator.py:356-410`, `llm_service._create_optimization_prompt:290-358`, `optimization_personas.py` |
| Guided intake: industry, seniority, tone, emphasize, downplay | **SHIPPED** — UI, job payload, worker boundary, and prompt blocks | `guided-intake.ts`, `GuidedIntakePanel.tsx`, `orchestrator.py`, `llm_service.py` |
| Structured change metadata `changes_made` (`{section, change_type, reason}`) | **SHIPPED** as advisory rationale input to deterministic segmentation | `orchestrator.py`, `ChangeReviewModal.tsx` |
| Stable change atoms with `original_text`/`new_text` | **SHIPPED** via server-side diff rather than LLM-provided offsets | `resume_diff_service.py`, `optimize_routes.py` |
| Whole-document diff review (Compare before/after, Diff viewer, checkpoints, variants) | **EXISTS** (scaffolding for granular review) | `optimize/page.tsx` CompareModal/DiffViewerModal/VersionHistoryPanel; `getResumeDiffWithParent` |
| Per-suggestion accept/reject/edit UI + selective apply | **SHIPPED** | `ChangeReviewModal.tsx`, `/optimize/segment-changes`, `/optimize/apply-changes` |
| Explicit staging before document mutation | **SHIPPED** on anonymous Studio and authenticated editor | `try/page.tsx`, `workspace/[resumeId]/edit/page.tsx` |
| Steer-and-regenerate with a note | **SHIPPED** for the writing assistant | `WritingAssistantWidget.tsx`, `POST /ai/rewrite` |
| ATS scoring surfaced to user | **EXISTS**, advisory only, **not fed back into the prompt** | `ats_scoring_service.py`, `ATSScoreCard`/`AtsSimulatorPanel` |
| Editor AI helpers (bullets/summary/rewrite/translate), metered `ai_assists` | **EXISTS** (separate from optimize) | `ai_routes.py` |

**Takeaway:** the model drafts a complete candidate, but the product keeps it
staged and derives independently applicable hunks so the user remains the final
author. The old auto-apply description is historical.

## 5. Market grounding (why this specific shape)

- **Nobody in the resume-SaaS set (Teal, Rezi, Enhancv, Kickresume, Jobscan, Careerflow, Huntr, Standard Resume) has a clean per-change accept/reject/edit diff for optimization.** Open gap Latexy can own.
- **JD-paste + match-score-before-acting is table stakes** — Latexy already takes JD input, but spends it on one-shot rewrite instead of a review loop.
- **Transparency raises agreement** (revealing AI reasoning lifted agreement ~2–4 pts, significant) — **but** extensive reasoning can cause **over-trust that crowds out the user's own judgment.** → Keep rationales **short, contrastive, ATS-tied**, always paired with an easy reject.
- **ATS reality:** keyword filters are near-universal (~99.7% of recruiters), **but keyword stuffing backfires** (NLP screening penalizes unnatural density; "perfect score" is a myth — ~80% is the sweet spot). The credible rule: **"prove the keyword in a real achievement,"** which is itself the justification for asking the user for input. Parsing failures are the underrated risk — clean, single-column, standard-heading formatting is where ATS value is genuinely won, and **parse-clean LaTeX templates are an ownable differentiator** (most builders lose >50% of data on re-parse).

## 6. Delivery status of the prioritized solution

### P0 — Per-change suggestion / accept–reject review layer (SHIPPED)

Turn the one-shot rewrite into an **interactive review**: the optimizer returns **atomic, individually-applicable changes** (per bullet/section), each with `original_text` + `new_text` (fields already exist on `OptimizationChange`). The user **accepts / rejects / edits** each; accepted changes apply incrementally to the LaTeX; recompile reflects the partial acceptance.

- **Reuses:** the delimiter state machine that already separates rewritten LaTeX from change metadata (`orchestrator.py:424-555`); diff-vs-parent; checkpoints (natural undo/branch points).
- **Net-new:** (1) optimizer emits **structured atomic changes** instead of one blob (populate `original_text`/`new_text` + a stable anchor per change); (2) accept/reject/edit UI; (3) selective apply + recompile.
- **Framing:** *AI drafts, you direct and approve* (Grammarly/Copilot norm).

### P1 — Lightweight guided intake before optimize (SHIPPED)

A **3–4 field pre-step** (progressive disclosure, smart defaults, advanced collapsed):
- Target role / JD (already have it) · Seniority · Tone/voice · "Which 1–3 achievements to emphasize / anything to downplay."
- **Reuses:** `optimization_level`, `industry`, `custom_instructions`, `persona` already in the request — this is mostly a **UI surface + defaulting layer**, plus feeding "emphasize/downplay" and (finally) **`industry` into the prompt**.
- **The "feel heard" win:** *reflect the choices back in the output* — a short "what changed & why" recap ("emphasized your AWS migration; kept to 1 page; added 'Kubernetes' from the JD"). Visible cause→effect is the strongest antidote to "the AI forced changes."
- Keep it short — research warns hard against the wall-of-configuration.

### P2 — Rationale on each suggestion (SHIPPED where optimizer reasons map to hunks)

Attach a **one-line, ATS-tied reason** per atomic change ("adds 'CI/CD' — required keyword missing from JD"; "quantified impact — recruiters favor metrics"). Concise, contrastive, actionable — **not essays**, always paired with reject (avoid the over-trust/crowding-out effect).

### P3 — Steer-and-regenerate loop (SHIPPED for writing-assistant selections)

Per bullet/section: tone control + quick actions ("more concise / more impact-focused / more technical") + **regenerate-with-a-note**. **Reuses the variants system** — each regeneration is a variant the user promotes.

### Cross-cutting guardrails (from ATS research)

- **Cap keyword additions; warn on unnatural density.** Sell "prove the keyword in a real bullet," not stuffing. Surface a warning when skills-vs-bullets mismatch grows.
- **Validate & market template parse-cleanliness** — run Latexy's templates through parse checks; make "parse-safe" a marketing claim if it holds.

## 7. Detailed design notes

- **Optimizer output contract (shipped):** the LLM still returns the complete
  candidate LaTeX plus advisory reasons. The pure `resume_diff_service`
  computes stable, bounded hunks from original→candidate text. This avoids
  trusting model-generated offsets or applying ambiguous replacements.
- **Apply engine (shipped):** map accepted change ids to the reviewed hunk
  payload, reconstruct from the original in source order, and leave rejected
  spans untouched. Locally edited `new_text` is preserved.
- **Intake → prompt (shipped):** `emphasize[]`, `downplay[]`, `tone`,
  `seniority`, and `industry` are explicit prompt blocks alongside custom
  instructions.
- **Keep the one-shot path** for speed-seekers; the review layer is the default for the AI tier.
- **Metering:** the optimize run already consumes `optimizations`. Regenerate-with-note (P3) and per-bullet AI (existing) consume `ai_assists`. No new dimension required.

## 8. Success metrics

- **Accepted-suggestion rate** (accepted / proposed) — primary quality signal; expect higher than accept-all-or-discard.
- Optimize→save conversion (do more users keep the result?).
- Retention / repeat-optimize rate (ownership → retention hypothesis).
- Reduction in "restore original / discard" rate vs today's one-shot.
- ATS score delta *without* density-warning triggers (real value, not stuffing).

## 9. Delivery evidence

| Phase | Shipped evidence | Remaining follow-up |
|---|---|---|
| P1 intake | `GuidedIntakePanel`, request types, worker payload, prompt tests | Measure completion/abandonment and tune defaults |
| P0 review layer | `resume_diff_service`, optimize review routes, `ChangeReviewModal`, client tests | Decide default entry path across every optimize surface |
| P2 rationale | advisory reasons are attached to review hunks when available | Improve mapping quality metrics without inventing reasons |
| P3 steer/regenerate | writing-assistant `steer` action and client/backend coverage | Consider section-level steering in the full optimize flow |

Regression coverage includes `test_resume_diff.py`,
`change-review-client.test.ts`, `guided-intake-client.test.ts`,
`optimization-staging.test.ts`, and `steer-rewrite-client.test.ts`.

## 10. Open decisions for founder

1. **Default flow:** make the review layer the **default** for the AI tier (one-shot as an explicit "optimize everything" button), or keep one-shot default and review opt-in? (Recommend: review default for AI tier.)
2. **Intake length:** exactly which 3–4 fields? Confirm seniority + tone + emphasize/downplay is the right minimal set, or swap one.
3. **Granularity:** per-bullet vs per-section change atoms (bullet = more control but more clicks; section = faster). Recommend per-bullet with section grouping.
4. **Rationale copy:** how prescriptive should the ATS reasons be (risk of over-trust)? Keep to one contrastive line.
5. **Parse-clean claim:** do we invest in validating templates against real ATS parsers to market "parse-safe"? (Recommended — genuine differentiator.)
