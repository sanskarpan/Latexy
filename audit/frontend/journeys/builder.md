# Non-technical journey: build a resume, preview it, optimize, cover letter, tracker

**Window:** 2026-11-27T20:56Z-21:10Z (IST). **Environment:** production `https://latexy.xyz`, backend `ee1a405d`.
**Identity:** synthetic free user (`audit.fe.free.20261127150805@example.test`), later deleted.
**Evidence:** `builder-journey.json`, `builder-preview-result.json`, `optimize-action.json`, `cover-template-result.json`, `tracker-pro-result.json`, screenshots in this folder.

## 1. Create through the guided builder

- Opened `/workspace/builder/new`.
- Entered title `Audit UI Journey 1795793570144`, left the default ATS-Safe template, clicked **Start my résumé**.
- `POST /resumes/builder/v1` returned **201**; URL changed to `/workspace/builder/e4672413-…`.
- The create transition can show **"Creating your résumé…" for ~30s**; in one run the client waited the full 30s before navigating. This is the same slow-compile UX that the frontend defect FE-01 describes.

Evidence: `builder-create-stuck.png`, `builder-create-net.json`.

## 2. Fill the resume

- Opened **Profile & Summary**; the editor has 10 visible text inputs but **none has an `id`, `name`, `placeholder` or `aria-label`**. Labels are visual only. This is FE-07.
- Filled name, headline, email, phone, location, LinkedIn, GitHub, website and summary.
- Completeness moved **0% → 35%**; sections included 1; template Ats Clean; no console/page errors.
- The live preview updated with the contact block and summary.

Evidence: `builder-profile-controls.json`, `builder-filled.png`.

## 3. Preview and download

- Clicked **Preview PDF**. Button changed to **"Preparing PDF…"**; the PDF viewer appeared only after roughly **20–60s** (`POST /jobs/submit` 200, job `a5a5ade3-…`).
- The resulting PDF rendered correctly: name, contact line, Summary. The contact URL `github.com/audit` wrapped mid-token as `github.com/au-` / `dit` (FE-11).
- **Download PDF** became enabled once the PDF was ready.

Evidence: `builder-preview.png`, `builder-preview-after.png`, `builder-preview-result.json`.

## 4. Optimize

- Opened `/workspace/{id}/optimize` on the builder resume. In one run the page loaded after ~8s; in another it showed only **"Checking feature availability"** for **25s+** (FE-01).
- When loaded, the page showed the LaTeX editor, an **ATS 46** badge and the ATS Simulator; job description and Optimize Resume controls were present.
- A free-account auto-compile produced a **402** on `/jobs/submit` because the compile quota was exhausted; no user-facing error was shown on the optimize shell.

Evidence: `optimize-builder-resume.png`, `optimize-after-25s.png`, `optimize-action.json`.

## 5. Cover letter

- Opened `/workspace/{id}/cover-letter`, filled a 159-character job description, clicked **Generate Cover Letter**.
- The button stayed at **"Generating…"** for **45s**; live logs said "No log output yet"; the document stayed empty. No console/HTTP error. This is FE-13.

Evidence: `cover-letter-after-generate.png`, `cover-template-result.json`.

## 6. Tracker

- On a fresh synthetic account with no resume, `POST /tracker/applications` returned **201**, the card appeared under Applied, and the page showed 1 total / this week 1.
- On the earlier free account, the form stayed at "Adding…" after the free compile quota was exhausted; the tracker call itself is not proven to depend on quota, but the UX gave no error.

Evidence: `tracker-pro-result.json`, `tracker-after-add.png`.

## What this means

The builder's happy path is real: create → fill → preview → PDF works and looks polished. The failure modes are around **latency and feedback**: 30s creation, 20–60s preview, 25s+ optimize gate, 45s cover-letter spinner, and unlabeled fields. These are now tracked as FE-01, FE-07, FE-11 and FE-13.
