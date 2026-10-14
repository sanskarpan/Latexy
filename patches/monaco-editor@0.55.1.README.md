# Monaco 0.55.1: observe WordHighlighter cancellation

This local exact-version backport uses Monaco's existing upstream
`onUnexpectedError` handler for three `WordHighlighter.runDelayer.trigger()`
promises that previously had no rejection observer: cursor movement, editor
focus, and view-state restoration. The existing `Delayer.cancel()` rejects
pending work with `CancellationError("Canceled")` when the model/editor is
disposed or restoration replaces pending work. A strict Chromium owner-switch
test reproduced the disposal stack through `pr.cancel`, `pr.dispose`,
`DisposableStore.dispose`, and `WordHighlighter.dispose` in the shipped AMD
bundle.

Each promise now calls `.catch(onUnexpectedError)`. That upstream handler
recognizes expected cancellation and continues reporting genuine errors through
Monaco's normal unexpected-error handler. This is the same pattern already used
by Monaco's parameter-hints contribution. Scheduling, successful callbacks,
occurrence-highlighting options, capability gates, and owner isolation are
unchanged. No window-level error handler or browser-test filter is added.

The pnpm patch covers both
`esm/vs/editor/contrib/wordHighlighter/browser/wordHighlighter.js` and the actual
AMD distribution `min/vs/editor.api-CalNCsUg.js` (where `De` is the minified
`onUnexpectedError`). Monaco stays pinned to 0.55.1. The original Microsoft MIT
headers and license are retained. This does not claim that a particular newer
Monaco release already contains the fix. Retire the patch only after reviewing
an upstream release and passing the same strict lifecycle/browser checks.

`frontend/scripts/monaco-cancellation-backport-integrity.json` pins the full
original/patched file hashes. The read-only guard rejects a missing/drifted
patch or a different version before assets are prepared. pnpm's committed patch
and lockfile own installation; neither the guard nor preparation repairs an
installed package.

`prepare-monaco.mjs` fingerprints every sorted relative asset path and full file
contents, rather than only the package version. It replaces legacy same-version
generated assets, verifies the copy, and repairs missing/corrupt output. This
prevents a previous unpatched 0.55.1 AMD copy from surviving installation of the
same-version patch.

The focused unit test applies the committed patch to a disposable copy of exact
vendor bytes. For both distributions, it extracts and executes the real cursor,
focus, restore and disposal callbacks with the real vendor Delayer and error
handling code. The original control observes unhandled cancellation; the
patched control observes none and still reports genuine callback errors. Asset
tests cover legacy-version invalidation, repeat reuse, same-version content
changes, and missing/corrupt output. Shared installed dependencies are never
edited by the tests.

Verify with Node 22 and pnpm 10.10.0:

- `pnpm install --frozen-lockfile`
- `pnpm --dir frontend test:unit src/__tests__/monaco-cancellation-backport.test.ts`
- `pnpm --dir frontend prepare:monaco`
- `pnpm --dir frontend typecheck` and `pnpm --dir frontend lint`
- Run the unchanged strict D14 and owner-switch browser suites with zero retries

Offline lockfile resolution lacked package metadata in the local environment.
The lock update is therefore mechanical: add this patch's SHA-256/path, append
its patch identity to Monaco's importer/snapshot/dependency versions and their
peer-qualified consumers, and leave every package version, range and tarball
resolution unchanged. A clean independent frozen-lockfile installation is a
required acceptance check; a mismatch must fail rather than relaxing frozen
mode.
