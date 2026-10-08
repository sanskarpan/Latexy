# Guided résumé builder acceptance — 8 October 2026

## Scope and method

Review of the existing beginner journey: Workspace → New résumé → Guided Builder → template → personal details → work/education/skills → saved résumé → preview and exports. The review used the Codex in-app browser against the normal local application, an authenticated disposable Team account, and synthetic résumé data. Screenshots were captured before recommending changes and saved unchanged. No production account, live payment, real applicant data, email delivery, or Drive upload was used.

This is a workflow review, not an accessibility compliance certification. Labels and named controls were checked through the visible browser DOM. Browser end-to-end fixtures are separate from the real local acceptance exercise.

## Findings and changes

| Step | Initial health | Evidence and change |
| --- | --- | --- |
| Choose creation route | Needs improvement | Entry copy described implementation concepts. The guided route now says what a person can do without code. [01](01-entry-before.jpg), [02](02-choose-before.jpg). |
| Choose a template/create | Needs improvement | Title now has an associated label. Creation waits for import parsing and rejects a blank or overlong title. Existing import and template options are retained. |
| Write content | Broken for natural list typing | Controlled fields discarded unfinished commas/newlines. Raw text is retained while editing, so Enter creates a second achievement and commas separate skills normally. Database/browser reload proof retained both bullets and keywords. |
| Read/edit on desktop | Needs improvement | The three-column layout squeezed title/template fields at the tested 1265px width. Full-width title/template controls and a two-column intermediate breakpoint make fields usable. [03](03-pdf-gap-before.jpg), [05](05-fields-after.jpg). |
| Review content | Needs improvement | Preview and renderer disagreed about technologies, education, certification URLs and project details. Both now include those values; empty entries and hidden sections do not inflate completeness/page estimates. Completeness is labelled “filled”, not an ATS result. [04](04-editor-after.jpg). |
| Save/reload | Needs improvement | Saves are serialized and carry a structured revision precondition. A PostgreSQL row lock admits one concurrent matching save and rejects the stale one. Conflict handling preserves the local draft. Ownership checks prevent another account from saving or inspecting revisions. |
| Return from code editing | Needs improvement | Reattachment asks explicitly before replacement and requires the current saved source baseline. Stale or missing baselines fail before overwriting code edits. |
| Export current content | Broken | Guided PDF export previously directed people to a compile button that was absent. The builder now has Preview PDF, Download PDF and retry handling. All exports await saves; SVG/JPEG/email/Drive also prepare the matching PDF. Cached PDF reuse requires the same saved version and source. |
| Anonymous sharing after edits | Needs improvement | Content changes now invalidate both anonymous PDF cache fields, including linked variants. A title-only save with identical rendered content retains a valid cached PDF. |
| Reopen a guided résumé | Needs improvement | Library Edit previously opened the advanced editor. Active, owned, original guided résumés now reopen the builder; manual, detached, shared and variant documents retain their existing editor. [13](13-library-return.jpg). |
| See the final PDF | Broken in the reviewed in-app browser | Native PDF embedding produced a blank frame despite a successful worker PDF. The builder now uses the application's browser-rendered PDF viewer with selectable text, zoom and download. [12](12-react-pdf-preview.jpg), [14](14-mobile-pdf-preview.jpg). |

## Real local browser exercise

The owned synthetic résumé was filled with a profile, two work achievements, two technologies, an education degree/field/GPA and three skills. Four optional sections were hidden and the template changed to Classic. A reload preserved the entered content, template, section visibility and separate achievements. The live preview displayed technologies, degree/field and GPA.

The first real PDF job failed before processing the résumé: the local LuaLaTeX font loader could not read its bundled Unicode data under `openin_any=p`. An isolated replay reproduced exit 255. The compatibility change is restricted to the validated LuaLaTeX engine; other engines retain paranoid input mode. All engine diagnostics and output now wait for transcript and recorder confinement checks, including failed and cancelled jobs. Tests cover missing/overwritten recorders and obfuscated private-file reads without releasing canary text, errors or artifacts. Progress events remain available while raw engine logs wait for verification.

After refreshing the local backend and worker, a normal edit regenerated the saved source with technologies. The final Alex PDF was visibly rendered in the real browser, downloaded through the UI, then independently extracted and rendered with Poppler. The one-page, 95,311-byte [PDF](alex-acceptance.pdf) contains both achievements, technologies, degree/field, GPA and three skills, with hidden/empty sections absent. The real SVG (148,894 bytes) and JPEG (96,410 bytes) exports also downloaded; the JPEG was visually inspected and matches the PDF. Files contain synthetic data only.

A second, newly created Jordan résumé exercised the full creation route: Workspace → New Resume → Open Guided Builder → blank-title rejection → title/template selection → Start → profile and summary → save → PDF → download. Its 50,028-byte [PDF](jordan-acceptance.pdf) was downloaded and independently rendered/inspected. Its 35% completeness correctly reflects the intentionally unfilled core sections. [09](09-create-entry-after.jpg), [10](10-layout-chooser-after.jpg).

At a 390 × 844 viewport, title, fields, actions and final PDF remained usable without document horizontal overflow (377px document width). [07](07-mobile-entry.jpg), [08](08-mobile-fields.jpg), [14](14-mobile-pdf-preview.jpg). The viewport override was cleared afterward. This is observed coverage at those sizes, not exhaustive device or accessibility certification. An initial transient fetch failure recovered through the visible Retry action after the local services were available.

## Automated checks

- Final frontend unit suite: **189 files, 1,220 tests passed**, including a regression that permits output delivery after the paid worker's four-minute budget. An earlier concurrent run had one five-second OAuth harness timeout; rerunning with two workers passed all cases without changing the test or its timeout.
- Frontend ESLint and TypeScript: passed.
- Builder renderer/API/conflict/cache tests on an isolated PostgreSQL test database: **49 passed**.
- Backend Ruff for all application, test and script paths: passed.
- Engine regression suite: **270 passed**, followed by **24 focused checks passed** including actual LuaLaTeX benign and obfuscated TeX/Lua private-file canary documents. Counts overlap.
- Earlier Dockerfile versions pass Buildx `--call=check` without warnings. Final recipes normalize font-directory timestamps and run `fc-cache` before switching users, then run the trusted helper as the runtime UID. Final RUN shell syntax, ordering assertions and Ruff pass. The final helper uses separate fixed Latin/SC/TC/JP/KR probes under one total 600s setup deadline to release memory between faces. **Eight helper checks passed; one real-engine case was skipped on the host.** Earlier Latin-only fresh-cache ownership and a subsequent document within 30s passed under development UID 1001 and production-style USER latexy (six checks each); those results predate the final sequential helper.
- Docker Desktop later became unresponsive (engine API returns HTTP 500; its WSL shell also hangs). The final extended fresh-cache exec returned no completion evidence, and OCI round-trip verification could not start. Those checks are pending. No final image build, successful fresh-container cache proof, or full deployment font parity is claimed. Unrelated engine containers were not stopped or modified to work around the outage.
- After the fixed four-face warmup, **all four CJK engine/extraction checks passed in 59.26s total**, with each document retaining its existing 45-second deadline and no missing-glyph acceptance relaxation. The matrix before face warmup reproduced the earlier failures. This verifies the reviewed local image/cache, not every deployed engine image.
- Final independent frontend source review: no merge blockers found.
- GitHub's default-branch braces advisory remains visible because no patched upstream version is available. The existing frozen-lock depth patch is preserved, and its installed-package regression passed. The advisory was not dismissed.
- Staged credential scans passed with zero findings: ten frontend/CI paths at `66b973bc`, then 34 backend/evidence paths at the final checkpoint. Local environment files and private fixtures are excluded. The two expressly staged PDF evidence files contain inspected synthetic data.
- Host production build completed compilation, lint and type checking; Windows standalone packaging failed with an EPERM symlink error. The GitHub Linux build is the artifact gate.
- Source-editor synchronization browser fixtures now explicitly select Source because the product intentionally starts in the visual editor. Their assertions and timeouts remain intact.

## Merge status

PR [#1834](https://github.com/sanskarpan/Latexy/pull/1834) contains the main integration, payment work and builder changes. CI at baf29e36 passes backend, frontend build/lint, full-stack smoke and template/deployment contract checks. Twenty-two desktop browser scenarios passed; one assertion expected the obsolete busy label “Compiling…” instead of the current “Preparing…”. The assertion was corrected while retaining its disabled-state check. Fresh CI is required for the final changes.

Frontend checkpoint `66b973bc` adds the eight guided-builder scenarios to the existing production browser job. Its backend CI exposed an exact step-name fixture mismatch; the manifest contract is updated to require the new name and builder path while retaining production mode, serial execution, zero retries and trace/artifact gates. Direct execution of that pure contract passed. Latest-head CI remains required.

The previously rate-limited Vercel check is now successful on baf29e36. Branch protections remain enabled. This report does not claim a new full repository backend suite, completed external email/Drive delivery, or production billing cutover. Student checkout remains intentionally pending. Provider refund/currency and wider deployment conditions remain tracked in the payment acceptance audit and final PR summary.
