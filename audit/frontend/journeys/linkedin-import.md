# LinkedIn import journey - 2026-11-27

**Verdict:** PASS end-to-end with a synthetic LinkedIn-style text fixture, but the resulting resume is source-only (same dead-end as FE-02).

## Setup

- Fresh free user (`interact10.free.*@example.test`), email verified; signed in through the in-app browser incognito tab.
- Fixture: `linkedin-profile.txt` (synthetic profile with summary, two roles, education, skills; 2,342 characters after parsing).
- Flow: `/workspace/new` → **Import from LinkedIn** → upload the text file → **Create Resume**.

## Timeline

| Step | Observed |
|---|---|
| LinkedIn mode | Export instructions + file input visible |
| Upload `linkedin-profile.txt` | accepted; "Converting to LaTeX… 0%" |
| Conversion progress | 40% after ~8s; **"Plain Text converted to LaTeX"**; "PROFILE PARSED — 2,342 CHARACTERS READY" |
| Create Resume | button switches to **"Creating…"**; URL stays `/workspace/new` for **~30s** |
| Editor | `/workspace/d4ccb7bc-.../edit`, "LinkedIn Audit Import", **2,342 chars** in the source |
| Editability | **"This document uses a layout that cannot be edited safely through fields yet"**; Source tab available, preview not compiled |

No console errors and no HTTP >= 400. The conversion itself was successful.

## Findings

1. **The import works**, including plain-text input through the LinkedIn source hint. A real LinkedIn export is a PDF, which routes to the already-PASS PDF import wizard; this fixture exercises the distinct text-conversion path.
2. **The created resume is not field-editable** ("layout cannot be edited safely through fields yet"). For a non-technical LinkedIn user this is a dead end; only the Source tab is usable. This is FE-02 / #2325, now confirmed for LinkedIn imports.
3. **Creation is slow**: "Creating…" for ~30s after conversion (FE-14 class, #2342).

## Evidence

- `linkedin-import-converted.png` - converted state and "2,342 characters ready".
- `linkedin-import-editor.png` - editor with the source-only warning.
- `linkedin-profile.txt` - synthetic fixture (no real personal data).

## Cleanup

- Resume deleted through `DELETE /resumes/{id}` with the owner token.
- Synthetic user, session and any rows deleted; remaining `interact10.%` users: **0**.
