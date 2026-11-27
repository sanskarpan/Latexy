# PDF import journey - 2026-11-27

**Verdict:** PASS (end-to-end), with a slow perceived-wait issue already tracked as FE-15.

## Setup

- Fresh free user (`interact6.free.*@example.test`), email verified.
- Source PDF: a 1-page LatexY-generated resume PDF (`audit_free_compiled.pdf`).
- Entry point: `https://latexy.xyz/workspace/new` → **Import File**.

## Evidence

`pdf-import-completion.json` (timings/DOM), `pdf-import-created-final.png` (editor after creation), `pdf-import-layout.png` (review/extraction UI).

## Timeline (final run)

| Step | Observed |
|---|---|
| Set resume title | `PDF Import Audit Resume` |
| Upload POST `/resumes/imports/pdf` | 201 at ~6.1s |
| Review wizard visible | ~6.4s |
| Original PDF fetched (`/imports/{id}/original`) | ~13.1s |
| Layout selected | `Data Scientist` (`#pdf-import-template`) |
| "Create editable resume" click | enabled after a layout was chosen |
| Adapt POST `/resumes/imports/{id}/adapt` | 200 at ~15.9s |
| Editor reached | `/workspace/f8f479d8-.../edit` 12.8s after click |

No console errors and no HTTP >= 400 during the final run.

## Findings

1. **Creation requires a reviewed field and a layout.** The button stays disabled until the layout is chosen and at least one extracted field is non-empty. With this PDF all extracted fields were empty, and selecting a layout alone still left the button disabled in one run; filling/altering a field is the documented contract (`frontend/e2e/quality/pdf-import-flow.spec.ts`). The UI hint says "Enter a resume title above" but does not explicitly say "edit at least one field", which is the actual blocker. Recommend an inline reason next to the disabled button.
2. **Extraction takes ~6-16s.** The wizard appears at ~6s but the layout select can take ~13s. During this time the UI says "Preserving your PDF and extracting its text…" with no progress. This is the same class as FE-15 and is covered by its acceptance criteria.
3. **The editor opens before fields are hydrated** ("Loading your resume fields…" and "Your PDF will appear here / Compile to render a live preview"), which is expected but reinforces the need for skeleton/progress states.

## Cleanup

- User, resume, compilation and session rows deleted.
- Remaining `interact6.%` users: **0**.
