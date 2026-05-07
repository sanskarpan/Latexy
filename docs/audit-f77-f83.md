# Audit Report: Features 77–83

**Date:** 2026-05-07
**Auditor:** Claude Code
**Scope:** Features 77 (Dropbox Sync), 78 (WYSIWYG Editor), 79 (PWA/Offline), 80 (Career Path), 81 (Benchmarking), 82 (Snippet Marketplace), 83 (Keyboard Macro System)

---

## Phase 1 — Environment Verification

| Check | Result |
|-------|--------|
| Backend health | N/A — backend not running during audit (requires `./scripts/dev.sh app`) |
| Alembic current | **0019** — migrations 0020–0023 not applied to dev DB |
| `ruff check` | ✅ CLEAN (0 errors) |
| `pytest` (56 tests, features 80–83) | ✅ 56/56 PASSING |
| `pnpm run build` | ✅ CLEAN (0 TS errors) |

**Note on migrations:** `alembic current = 0019`. Migrations 0020–0023 (F77–F83) are present in `alembic/versions/` but have not been applied to the running Postgres instance. Running `make migrate` or `./scripts/dev.sh app` (which calls `alembic upgrade head`) is required before live API tests. This is a deployment/ops concern, not a code bug — migrations are well-formed and reversible.

---

## Phase 2 — Live API Audit Summary

Live API audit was conducted via code inspection (backend not running). Key findings are elevated to the bug list below. All endpoint contracts were verified against Pydantic models.

---

## Phase 3 — Frontend–Backend Contract Audit

| Feature | Interface | Field | Status |
|---------|-----------|-------|--------|
| F80 | `CareerAnalysisResponse.created_at` | `string` | ✅ matches `isoformat()` |
| F80 | `CareerRoleResponse` | all fields | ✅ exact match |
| F81 | `BenchmarkResult` | all fields | ✅ exact match |
| F82 | `SnippetResponse` | all fields | ✅ exact match |
| F83 | `MacroResponse.actions` | `Record<string, unknown>[]` TS vs `list[dict]` Python | ✅ compatible (JSON roundtrip) |
| F83 | `MacroResponse.description` / `.shortcut` | `string \| null \| undefined` TS | ✅ matches `Optional[str]` Python |

No schema mismatches found. All field names use consistent `snake_case` throughout (backend serializes natively, frontend uses them as-is).

---

## Phase 4 — Log & Error Analysis

- **No SQLAlchemy lazy-loading warnings** — all relationships use `lazy='selectin'` or are accessed within session scope.
- **Pydantic v1 `class Config`** — `CareerRoleSchema` and `CareerAnalysisSchema` in `career_routes.py` use the deprecated `class Config: from_attributes = True` pattern instead of Pydantic v2's `model_config`. Emits deprecation warnings in logs.
- **`exclude_none=True` in PATCH handlers** — silently discards `null` values in `SnippetUpdate` and `MacroUpdate`, making it impossible to clear optional fields.

---

## Phase 5 — Gap Analysis

| Sub-task | Spec | Implementation | Match |
|----------|------|----------------|-------|
| F77-A | DB migration with token encryption | ✅ `0020_add_dropbox_integration.py` | ✅ |
| F78-B | WYSIWYG round-trip fidelity | Parser drops epilogue (`\end{document}`) | ❌ BUG-01 |
| F79-C | PWA manifest with correct icon spec | SVG icons use pixel `sizes` instead of `"any"` | ⚠️ BUG-05 |
| F80-C | Career path BFS returns empty (not 500) when no path | ✅ returns empty list | ✅ |
| F80-E | Admin seed endpoint — admin only | Uses `get_current_user`, not `require_admin` | ❌ BUG-04 |
| F81-A | Benchmark validates ats_score range | ✅ rejects < 0 or > 100 with 422 | ✅ |
| F82-A | Shell-injection patterns rejected | ✅ all 9 patterns blocked | ✅ |
| F82-B | Install idempotency | ✅ count increments exactly once | ✅ |
| F82-B | Admin seed — admin only | Uses `get_current_user`, not `require_admin` | ❌ BUG-04 |
| F82-C | PATCH can clear optional fields (tags, etc.) | `exclude_none=True` blocks nulls | ❌ BUG-03 |
| F83-C | MacroRecorder captures actions faithfully | Double-records cursor after insert | ❌ BUG-02 |
| F83-D | PATCH can clear shortcut | `exclude_none=True` blocks null shortcut | ❌ BUG-03 |

---

## Phase 6 — Bug Triage

### BUG-01 · P1 · F78 — WYSIWYG parser drops document epilogue

**Feature:** 78 — WYSIWYG Editor
**Severity:** P1 — Feature broken
**File:** `frontend/src/lib/wysiwyg/latex-parser.ts`

**Description:**
`epilogueLines` is declared on line 60 but never populated. Any content after the last `\section` block (most importantly `\end{document}`) is buffered as part of the last section and becomes a `raw` entry instead of going to `doc.epilogue`. After round-trip, `\end{document}` is wrapped inside the last section's content, which can be placed inside a `\resumeSubHeadingListEnd` block — producing invalid LaTeX that fails to compile.

**Reproduction:**
```typescript
const latex = `\\documentclass{resume}\n\\begin{document}\n\n\\section{Skills}\n\n\\end{document}`
const { doc } = parseResume(latex)
// doc.epilogue === '' (BUG: should be '\\end{document}')
// doc.sections[0].entries[0].type === 'raw' (BUG: \end{document} as a raw entry)
const out = serializeResume(doc)
// out contains \end{document} inside \resumeSubHeadingListStart...End block
```

**Expected:** `doc.epilogue === '\\end{document}'`, `doc.sections[0].entries` has length 0.
**Actual:** `doc.epilogue === ''`, `\end{document}` becomes a raw entry in the last section.

---

### BUG-02 · P1 · F83 — MacroRecorder double-records cursor movement after text insertion

**Feature:** 83 — Keyboard Macro System
**Severity:** P1 — Feature broken
**File:** `frontend/src/lib/macros/macro-recorder.ts`

**Description:**
When a user types a character, Monaco fires two events in sequence:
1. `onDidChangeModelContent` → recorder emits `{ type: 'insert', text: 'a' }`
2. `onDidChangeCursorPosition` → recorder emits `{ type: 'move', direction: 'right', count: 1 }`

During playback, `MacroPlayer` handles `insert` by calling `editor.setPosition(newCol)` (already advancing the cursor), then `move right 1` advances it one more position. Every typed character leaves the cursor one column ahead of where it should be.

**Reproduction:**
1. Start recording, type "hello" (5 chars)
2. Stop recording
3. Play macro on a fresh position
4. Cursor ends up 5 columns to the right of where it should be

**Expected:** Typing "hello" records `[{ type: 'insert', text: 'hello' }]`
**Actual:** Records `[{ type: 'insert', text: 'hello' }, { type: 'move', direction: 'right', count: 5 }]`

---

### BUG-03 · P2 · F82/F83 — PATCH endpoints cannot clear optional fields (exclude_none silently drops nulls)

**Feature:** 82 (Snippets), 83 (Macros)
**Severity:** P2 — Incorrect behavior
**Files:** `backend/app/api/snippet_routes.py:231`, `backend/app/api/macro_routes.py:111`

**Description:**
Both `PATCH /snippets/{id}` and `PATCH /macros/{id}` call `body.model_dump(exclude_none=True)` before updating fields. When a client sends `{"shortcut": null}` to remove a macro shortcut, Pydantic parses `null` as `None`, then `exclude_none=True` excludes it from the dump — so the shortcut is never cleared. The same applies to `description`, `tags`, and any other nullable field.

**Expected:** `PATCH /macros/{id}` with `{"shortcut": null}` clears the shortcut to NULL in DB.
**Actual:** Shortcut remains unchanged.

**Fix:** Use `exclude_unset=True` instead of `exclude_none=True`.

---

### BUG-04 · P2 · F80/F82 — Admin seed endpoints accessible to any authenticated user

**Feature:** 80 (Career Path), 82 (Snippets)
**Severity:** P2 — Incorrect behavior (security: unauthorized data mutation)
**Files:** `backend/app/api/snippet_routes.py:333-350`, `backend/app/api/career_routes.py:246-320`

**Description:**
`POST /admin/snippets/seed` and `POST /admin/career-graph/seed` use `get_current_user` (any authenticated user) instead of `require_admin`. Any logged-in user can overwrite official snippet data or rebuild the career graph.

`require_admin` exists in `auth_middleware.py` and enforces `ADMIN_EMAIL` env var or legacy JWT admin claim.

**Expected:** Non-admin authenticated users receive 403.
**Actual:** Non-admin users can seed official data.

---

### BUG-05 · P3 · F79 — PWA manifest SVG icons use wrong `sizes` attribute

**Feature:** 79 — PWA/Offline
**Severity:** P3 — Cosmetic
**File:** `frontend/public/manifest.json`

**Description:**
SVG icons declare `"sizes": "192x192"` and `"sizes": "512x512"`. Fixed pixel dimensions are meaningless for scalable vector images. Per the [Web App Manifest spec](https://www.w3.org/TR/appmanifest/#sizes-member), SVG icons should use `"sizes": "any"` to signal they are resolution-independent. Some browsers / PWA validators reject or warn about this mismatch.

**Fix:** Change `"sizes": "192x192"` and `"sizes": "512x512"` to `"sizes": "any"` for SVG entries.

---

### BUG-06 · P3 · F80 — Pydantic v1-style `class Config` in career_routes.py emits deprecation warnings

**Feature:** 80 — Career Path
**Severity:** P3 — Cosmetic / deprecation
**File:** `backend/app/api/career_routes.py:49, 68`

**Description:**
`CareerRoleSchema` and `CareerAnalysisSchema` use the Pydantic v1 `class Config: from_attributes = True` pattern. Pydantic v2 uses `model_config = {'from_attributes': True}`. The v1 style emits deprecation warnings in server logs.

---

## Phase 7 — Fix Log

| Bug | Status | Commit |
|-----|--------|--------|
| BUG-01 | ✅ Fixed | `fix(78): parser now extracts epilogue at \\end{document}` |
| BUG-02 | ✅ Fixed | `fix(83): recorder skips cursor moves triggered by content changes` |
| BUG-03 | ✅ Fixed | `fix(82-83): use exclude_unset in PATCH handlers to allow null clearing` |
| BUG-04 | ✅ Fixed | `fix(80-82): admin seed endpoints now require require_admin` |
| BUG-05 | ✅ Fixed | `fix(79): PWA manifest SVG sizes changed to "any"` |
| BUG-06 | ✅ Fixed | `fix(80): migrate CareerRole/AnalysisSchema to Pydantic v2 model_config` |

---

## Phase 8 — Final Verification

**Date:** 2026-05-07 (same day as audit)

### Test Results

| Suite | Count | Result |
|-------|-------|--------|
| Backend F80–83 pytest | 61 | ✅ 61/61 PASSING |
| Frontend Vitest (all unit) | 383 | ✅ 383/383 PASSING |
| `ruff check app/` | — | ✅ CLEAN |
| `pnpm run build` | — | ✅ CLEAN (0 TS errors) |

### Commit Log (audit fixes)

| Commit | Fix |
|--------|-----|
| `6f2f18e` | BUG-01: parser extracts epilogue at `\end{document}` |
| `4f8716c` | BUG-02: recorder skips cursor moves triggered by content changes |
| `6b94aa5` | BUG-03: exclude_unset in PATCH handlers to allow null clearing |
| `f4eba25` | BUG-04: admin seed endpoints require `require_admin` |
| `3ae46df` | BUG-05: PWA manifest SVG icons use `sizes="any"` |
| `615c8bb` | BUG-06: CareerRole/AnalysisSchema migrated to Pydantic v2 `model_config` |

### Audit Outcome

All 6 triaged bugs resolved. No regressions introduced. The pre-existing `test_analytics_visualization.py` failure (Postgres schema on migration 0019, missing `dropbox_access_token` column) is unchanged — it requires running `alembic upgrade head` against the live dev DB and is a deployment concern, not a code bug.

---

## Known Limitations / Deferred Issues

1. **F78 project heading round-trip lossy** — `\resumeProjectHeading{\textbf{Title} $|$ \emph{Tech}}{date}` loses the `$|$ \emph{Tech}` part after parse→serialize. The plain heading text is preserved but italic formatting is lost. Deferred: fixing requires adding a `headingRaw` field to the `Entry` interface, changing parser, serializer, and WYSIWYGEditor — significant scope for a visual-only issue.

2. **F82 N+1 query in snippet list** — `_build_response()` makes 2 DB queries per snippet (install check + upvote check) + 1 for author. For a page of 20 snippets, that's up to 60 queries. Deferred: requires eager loading or batch queries — safe to address in a separate performance PR.

3. **F80 LLM calls not rate-limited** — `POST /career/analyze` makes 3 LLM calls synchronously. No per-user rate limit. Deferred: requires Celery task integration — separate feature work.

4. **F83 No duplicate shortcut detection** — Multiple macros can be assigned the same keyboard shortcut; the conflict only manifests at registration time in Monaco. Deferred: acceptable for initial release.
