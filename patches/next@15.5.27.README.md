# Next 15.5.27: React host hydration replay backport

This exact-version pnpm patch translates only the runtime helper and HostComponent replay call from React's official [commit c18662405cc436646411647f8a8965c1c0594c3c](https://github.com/react/react/commit/c18662405cc436646411647f8a8965c1c0594c3c), [PR #35494](https://github.com/react/react/pull/35494), into Next 15.5.27's four **normal-channel** vendored ReactDOM files. React remains `19.2.0-canary-0bdb9206-20250818`. Next, React, RSC and Scheduler versions are unchanged. The original React MIT headers and `dist/compiled/react-dom/LICENSE` are retained.

The helper retains the parent-fiber validity check, non-hydrating insertion branch, and non-null HostComponent-only cursor rewind. Its only invocation is immediately after `resetHooksOnUnwind` in replay's `case 5`, before unwind/reset/beginWork. Development invokes it in `replayBeginWork`; production/profiling invoke it in `replaySuspendedUnitOfWork`. DOM hydration support is compiled as true. Ordinary `popHydrationState`, completion checks, tail deletion, other fiber types and error reporting are unchanged.

`frontend/scripts/next-hydration-backport-integrity.json` pins all four complete preimages/postimages. The read-only guard verifies exact Next version, all postimages, their exact inverse preimages, and unchanged full compiled React/ReactDOM companion/Scheduler/RSC directory digests. It runs after install, before package build/dev/start, and when Next loads its configuration. Next's own channel-selection predicate and any nonempty inherited `__NEXT_EXPERIMENTAL_REACT` reject experimental React configurations rather than certifying unpatched experimental renderers. The guard never repairs or modifies installed files. Digest drift requires explicit review; do not refresh hashes to make a failing build pass.

The pre-install causal proof at [commit `5d7167d9cd7f0345ebfa689cdf2de7dea7ef6a82`](https://github.com/sanskarpan/Latexy/commit/5d7167d9cd7f0345ebfa689cdf2de7dea7ef6a82), [CI run 38147805437](https://github.com/sanskarpan/Latexy/actions/runs/38147805437), passed four cells once each. Both pending cells observed the same fulfilled-thenable, reason-7, hydrating HostComponent replay state. The original emitted one #418 and replaced all five SSR nodes; the faithful test-local patch preserved all five with zero errors. Both prefilled controls passed. Evidence JSON SHA-256: `6b481c0e620a7fa48bcff725a97a717245d64e693b0252c4fe53960e55396aa0`. This was a single synthetic Chromium/CDP proof, with debugger attachment potentially affecting scheduling; it did not validate the final installed package repair or full production application.

This is an install/build/channel integrity guard. A generated standalone `server.js` loads serialized Next configuration and does not rerun the source configuration guard at process startup. The standalone artifacts must come from the verified clean build; this patch does not establish a post-build tamper-detection policy.

The paired Chromium diagnostic reconstructs its original renderer by the validated exact inverse and imports the effective installed patched renderer for its green arm. Its pending original must still produce exactly one #418 and replace all five SSR nodes; its patched arm and both prefilled controls must report zero errors and preserve all nodes. No retry, scheduler replacement or error suppression is introduced. The original application/owner/quality gates remain required.

Reproduce from a clean checkout with Node 22 and pnpm 10.10.0:

- `pnpm install --frozen-lockfile`
- `pnpm --dir frontend verify:next-hydration`
- `pnpm --dir frontend test:unit`
- `pnpm --dir frontend typecheck` and `pnpm --dir frontend lint`
- Remove the prior `.next` tree, then `pnpm --dir frontend build`
- Run the existing zero-retry CI hydration and full application browser gates

Retire this patch only after a reviewed Next release incorporates the fix in the matched vendored runtime and the same strict causal/application tests pass. Do not upgrade to Next 16 solely to remove the patch.
