# TUI control-key input recovery — issue #1805

Scope: prevent global control-key shortcuts from modifying a focused TUI text
field. Do not change OAuth configuration, CLI publication, real account state,
or CI requirements as part of this repair.

## Verified baseline

Main `4470b771bbc4025ac698d3a7dafe3f527019266e`, after OAuth PR #1831,
failed canonical CI `37539382918` with TUI as the only failing job. All thirteen
other jobs succeeded. TUI job `112528420131` reported 223 passing tests, one
failure, and 66 skipped live-infrastructure tests. The real terminal scenario
`ctrl_l_empty` expected an empty prompt and received literal `l`.

The accepted OAuth PR changed no TUI source, and its TUI job passed. Local
end-cursor terminal controls also passed; neither result makes the Linux
failure a false positive. Keep the original failure evidence rather than
rerunning until green.

An actual React/Ink/ink-text-input runtime probe gives a deterministic second
reproduction: start with `abc`, move Left, then press Ctrl+L. The old field
becomes `ablc` instead of retaining `abc`. Ink normalizes the control byte to
`input = 'l'`, `key.ctrl = true`; ink-text-input inserts at its cursor, whereas
the separate guard only trims a suffix. Each Ink input listener batches its
own callback; a later passive-effect repair is not an input-dispatch ordering
guarantee. Restoring a deferred suffix trim is therefore not an accepted fix.

Retained evidence, outside the repository:

- `/tmp/latexy-main4470-tui-job-20261007.log`
- `/tmp/latexy-tui-1805-runtime-controls-20261007.log` (original five controls,
  four pass and the middle-cursor case fails)
- `/tmp/latexy-tui-1805-pty-controls-local-20261007.log`
- `/tmp/latexy-tui-1805-root-baseline-runtime-20261007.log` (in-progress
  expanded probe, not an accepted final suite; includes harness/control
  expectation failures as well as baseline regressions)
- `/tmp/latexy-tui-1805-root-coalesced-red-20261007.log` (two actual raw-C0
  insertion failures on the initial repair, plus an incorrect monochrome
  cursor-cell assertion; that assertion is not an application failure)

## Repair and acceptance

Reject normalized control-letter events inside the text input handler before
either its controlled value or its cursor is changed. Strip raw C0 controls
from coalesced input, retaining tab/newline/carriage-return paste whitespace
and calculating cursor offsets from the sanitized text. This protects fields;
it does not invent global-shortcut metadata for chunks Ink does not normalize.
Apply the same input to
prompt, picker/filter, and login fields. Preserve ordinary typing, genuine
trailing `l`/`L`/`c`, masked values, cursor navigation, submission, pasted
commands, focus behavior, and global Ctrl+C handling. Do not modify user CLI
configuration during verification; terminal scenarios use isolated temporary
XDG directories and a stub backend.

- [x] Deterministic baseline failure in actual Ink runtime, not a mocked guard.
- [x] Source repair reviewed independently of its author.
- [x] Runtime regression and focus/unmount/cursor/control cases pass (17).
- [x] All original real-PTY controls and new cursor/control cases pass (16).
- [x] Full TUI suite, TypeScript, and Node 22 bundle pass on stable source.
- [ ] Focused one-file commits, protected PR CI, normal main merge.
- [ ] Exact post-merge CI and deployment results recorded truthfully.

The failed main CI correctly skipped the formal Vercel certification and Modal
deployment follow-ons. Vercel's independent frontend deployment is Ready and
canonical identity reports `4470b771`; these are separate facts. A subsequent
TUI-only change may legitimately be skipped by Vercel as “Not affected”; the
existing strict exact-main certificate does not yet support that case (#1802).
Do not claim a skipped revision was deployed, weaken the certificate, or
publish an npm release as an implicit part of this keyboard repair.

## Root validation checkpoint

On Node `22.23.2`, root rebuilt the final source and ran the complete TUI
suite: 244 passed, 66 live-infrastructure cases skipped, 38 files passed and
seven files skipped. The skip count is disclosed, not treated as live testing.
Standalone strict TypeScript also checks the new runtime test, which the
package's normal source-only TypeScript configuration excludes. Both checks
exit successfully with empty diagnostic logs.

The FORCE_COLOR run verifies that the actual focused cursor has inverse
styling and the unfocused field does not. Default monochrome rendering checks
content rather than unreliable frame counts or trailing blank cells. Ink
performs capability-aware styling; placeholder gray and masking are retained.
The test fixture captures runtime failures through Ink's real
`waitUntilExit`, not an unsupported `render` option, and cleans up its streams.

Final shared input SHA-256:
`a79a0ca2f527cba2988c4427c5332e83d59f702d804faa7da9335f91ddd09ec3`.
No dependencies, lockfiles, workflow gates, real account settings, or user CLI
configurations were modified. The unused suffix-repair hook is removed;
historical source remains recoverable in Git. Existing Unicode/grapheme-width
limitations are not claimed fixed by this control-key repair.

Root logs:

- `/tmp/latexy-tui-1805-root-build-final-20261007.log`
- `/tmp/latexy-tui-1805-root-source-types-final-20261007.log`
- `/tmp/latexy-tui-1805-root-test-types-final-20261007.log`
- `/tmp/latexy-tui-1805-root-full-suite-final-20261007.log`
- `/tmp/latexy-tui-1805-root-runtime-final-20261007.log`
- `/tmp/latexy-tui-1805-root-force-color-final-20261007.log`
- `/tmp/latexy-tui-1805-root-classifier-20261007.log` (21 pass; repair maps
  only to TUI, with the unconditional privacy/classifier guards retained)
