# Managed English outline rerun removal — 2026-10-08

Fresh repository-owned English builder output now uses `hyperref[hidelinks,bookmarks=false]`. The prior setting generated an empty `resume.out`, whose `rerunfilecheck` warning caused a second TeX pass. The builder's five categories use starred section headings or plain styled headings, with no outline-writing commands. Disabling their unused outline preserves clickable links and removes that particular rerun signal.

This changes one generated source line's content, preserving its line number and every body line. Existing saved/custom sources are not rewritten. The normal rerun matcher, three-pass bound, bibliography handling, auxiliary reuse rules, cancellation/deadline checks and isolation policy remain unchanged. Documents with actual references still require convergence; the existing real reference and classic bibliography tests remain part of the focused validation.

## Actual experiment

The committed `backend/scripts/benchmark_managed_bookmarks.py` uses the **current** builder's fixed `ats_safe` fixture. It adds synthetic URL/email links so annotation retention is actually exercised. The baseline changes exactly the hyperref option back to its previous value. Each render gets a new private workspace; neither condition uses a preloaded TeX source cache or the installed trusted format. Lua runs through `native_engine_command` and its mandatory Linux Landlock/seccomp launcher. Both compilers use the minimal engine environment, no shell escape, recorder checks and the unchanged rerun matcher. Every subprocess has a 30-second limit; at most three compiler passes are allowed. Log/artifact reads and SyncTeX expansion are bounded. The CLI accepts only this owned fixture, not an arbitrary source or format.

Two alternating pairs per compiler ran in the local TeX 2025 QA image `latexy-engine-qa:20261007-v2`, with read-only Linux source from `latexy-engine-runtime-20261008` (backend snapshot `3d556b87`) and a read-only current preamble/script overlay. The container had no network and ran as `appuser`. The image's inherited `/app/temp` path was overridden with `TEMP_DIR=/tmp/latex_compile`; initial attempts without this override failed during service import before compiling and are not timing samples. A read-only-volume mount attempt for the new test helper also failed before test execution; the accepted test run uses an additional small namespace-package overlay.

| Compiler | Pair order | Baseline seconds / passes | Current seconds / passes |
| --- | --- | --- | --- |
| LuaLaTeX | Baseline, current | 42.493 / 2 | 21.160 / 1 |
| LuaLaTeX | Current, baseline | 26.699 / 2 | 20.667 / 1 |
| pdfLaTeX | Baseline, current | 14.930 / 2 | 3.277 / 1 |
| pdfLaTeX | Current, baseline | 14.689 / 2 | 11.186 / 1 |

Every pair has exact parity for page count (one), extracted text, rendered 72-DPI page pixels, word coordinates/page geometry, normalized source SyncTeX records, forward mapping coordinates, and both actual hyperlink annotations. Every current render has no rerun messages or missing-glyph warning. Every baseline's first pass reports only the empty outline-file rerun; its second pass has no rerun signal. Lua has 360 source SyncTeX records and pdfLaTeX has 318; parity is checked **within each compiler**, not across compilers.

The host was running other validation/build workloads. Four renders per compiler establish the pass-removal mechanism and output parity, not a production latency percentile, browser latency, cold-start promise or multilingual acceptance. No claim that the project's latency targets have been met follows from these samples. The broader baseline benchmark's 30 Lua pairs measured a separate end-to-end pipeline and must not be compared as though host load or scope were identical.

Raw synthetic reports: [Lua](managed-bookmarks-lua-2026-10-08.json), [pdfLaTeX and private owned-format check](managed-bookmarks-pdflatex-2026-10-08.json).

Current unmodified builder fixture source SHA-256: `38d96ff6023f8efd3a7c4c9f771c95d36036815718e15cbba5418b238c77bc84`. Actual image assets fingerprint: `engine_assets_fingerprint:d50065510d953251a32735c8072e676702e9cc71bdc93441c545836251d338b6`.

## Format and identity safety

The owned pdflatex format ID changes from `latexy-managed-english-v1` to `latexy-managed-english-v2`. A stale v1 profile cannot handle the new preamble; ordinary rendering is the safe fallback. Current v2 profile metadata is tested against the new preamble hash. Changing the source changes the exact cache key for **both** LuaLaTeX and pdfLaTeX even when no trusted profile exists; changing a verified profile identity also changes the key. No old output/auxiliary result is intentionally replayed across the new source.

The probe additionally dumped the new v2 pdflatex format into a private temporary directory using the image-build script's owned preamble/format arguments. Its 3,465,895-byte format rendered the current fixture in one pass with all the same output/source parity checks. This proves local build compatibility; it does **not** certify installed immutable image assets or change a running image. The existing build script reads the dependency-free preamble constants, so it will generate the v2 name, preamble hash and profile identity on a later authorized image rebuild.

**Release gate:** rebuild the pinned renderer image to install the v2 readonly format/manifest, verify immutable metadata and dependencies, and rerun the image-built trusted-format certification before enabling that acceleration. Retain ordinary fallback until that gate passes. Lua currently has no owned preloaded-format implementation and receives this improvement through its regular compiler path. Modal/default-language certification gates remain unchanged. This English fixture does not establish multilingual glyph coverage.

## Reproduction and regression scope

On a supported Linux runtime with the repository backend, installed TeX/Poppler/SyncTeX and a writable temporary directory, run from `backend`:

```sh
PYTHONPATH=. TEMP_DIR=/tmp/latex_compile SKIP_ENV_VALIDATION=true ENVIRONMENT=test DEPLOY_TARGET=local \
  python scripts/benchmark_managed_bookmarks.py --compiler lualatex --pairs 2 --output /tmp/managed-lua.json
PYTHONPATH=. TEMP_DIR=/tmp/latex_compile SKIP_ENV_VALIDATION=true ENVIRONMENT=test DEPLOY_TARGET=local \
  python scripts/benchmark_managed_bookmarks.py --compiler pdflatex --pairs 2 --verify-owned-format --output /tmp/managed-pdftex.json
SKIP_INFRA_CHECK=true DEPLOY_TARGET=local LATEXY_RENDER_BACKEND=native TEMP_DIR=/tmp/latex_compile \
  python -m pytest -p no:cacheprovider -o addopts=--tb=short \
  test/test_trusted_render_profiles.py test/test_render_passes.py --junitxml=/tmp/managed-bookmarks-focused.xml -q
```

`--pairs` is bounded to 1–5. A failed convergence, mismatch or missing annotation returns nonzero and records `verified: false`. The optional format check never installs or changes an image asset. Ordinary parity hashes intentionally exclude PDF timestamps; they compare rendered/extracted content and source mappings instead.

The focused tests cover every owned category's heading invariant, actual one-pass Lua/pdfLaTeX builds with links and SyncTeX, stale v1 fallback, current identity validation, memoized asset replacement, exact cache identity separation, and the unchanged real custom reference/bibliography convergence behavior. Ruff validation covers all changed Python files.

The initial focused run passed 23 cases and failed the unchanged real bibliography case at its existing shared 15-second deadline (97.72 seconds total). The serial recheck ran the exact-cache identity case followed by that same bibliography case: both passed in 35.533 seconds, with the bibliography test taking 6.811 seconds. Neither source, assertion nor 15-second deadline was changed for the recheck. The recheck overlaps the initial suite and is not two additional unique tests. Retained JUnit files are `managed-bookmarks-focused.xml` and `managed-bookmarks-bibliography-rerun.xml` in the dated local QA directory.
