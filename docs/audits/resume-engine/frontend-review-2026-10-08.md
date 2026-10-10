# Frontend engine follow-up review — October 8, 2026

Reviewed the shared PDF renderer loader/preload and quota-safe preview scheduler
follow-up, then rechecked the current engine branch after rebasing onto main
`bdee4892`. The frontend uses the actually committed Next **15.5.27** and canonical
pnpm **10.10.0** lockfile. This review does not certify production renderer latency,
paid semantic model quality, live OAuth or backend migration acceptance.

## Confirmed defects and repairs

1. **Cancelled guest previews blocked later previews.** Save a field in `/try`,
   allow its automatic preview to start, and click Stop. The cancel endpoint is
   `DELETE /jobs/{job_id}`. After its successful acknowledgement the page detached
   its stream by clearing the active job. The scheduler never received that
   stream's terminal event and retained its running-job fence indefinitely.
   A separate acknowledged cancellation receipt now completes only that scheduler
   job. Pending fields remain behind the same running-job fence, backend quota
   authority and automatic typing throttle. Account changes ignore late cancel
   responses; a late acknowledgement cannot clear a newer active job.
2. **Delayed guest field responses crossed account changes.** Start a guest field
   patch, change the account while preserving the same source buffer, then let
   the response arrive. The previous check compared only source text, so the old
   response could replace the new account's current buffer. The response now
   checks the captured account/device identity before adopting its source or
   requesting a preview. The production browser regression uses Better Auth's
   actual cross-tab storage notification path to change the session without
   remounting the editor.
3. **Original PDF attachments remained visible before effect cleanup.** Open an
   original PDF, then render the component under a different owner or resume.
   Clearing state in an effect happened after the first changed-identity render.
   The receipt now carries the identity that fetched it; render-time identity
   matching immediately hides the previous attachment and blob preview. Existing
   abort, token-bound request and object URL cleanup remain in place.

Regression fixtures are committed in:

- `frontend/src/__tests__/preview-cancellation.test.ts`
- `frontend/src/__tests__/resume-original-identity.test.ts`
- `frontend/e2e/quality/resume-preview-recovery.spec.ts`

## Reviewed invariants

- The renderer chunk is shared between speculative preload and rendering, kept
  behind the browser-only boundary, and a failed speculative load can retry.
  Preload ordering is evidence; no measured speedup follows from ordering alone.
- Automatic typing previews wait for five seconds of quiet and ten seconds
  between admissions. Explicit committed field/structure/review actions can run
  promptly, sharing the same single admitted/running preview fence. Failed or
  ambiguous admissions are not retried for unchanged source.
- Managed field and structure responses compare captured account generation and
  exact local source after awaiting the server. Semantic decisions additionally
  compare source hash and content revision before adopting authoritative output.
- Artifact previews check immutable identifiers, byte length, PDF hash and
  account/job/artifact identity before adopting bytes. Candidate previews remain
  separate from authoritative export decisions. Conservative ambiguous geometry
  remains read-only.
- PDF adaptation remains explicit and preserves verified original bytes. Resume
  mode uses plain fields and Source mode loads its editor on demand.

## Validation

Fresh independent Linux dependency volume, Node **22.23.3**, frozen pnpm lockfile:

- TypeScript check passed.
- Full ESLint passed with zero warnings.
- Full frontend unit suite: **1,162 passed across 182 files**, no failures/skips,
  163.89 seconds, two workers. Focused regression/preload/scheduler run also
  passed all 18 cases; these overlap the full suite and must not be added to it.
- Complete production build passed, generated all 40 static pages, assembled the
  standalone server and passed the repository build-artifact validator. Build
  authentication/database settings were inert QA values; no live database or
  production credentials were used.
- All nine production Chromium contracts passed with zero retries against that
  actual Linux standalone bundle, using the worktree's Playwright 1.62.1 and the
  installed Windows Chrome browser. This includes both new cancellation/account
  race regressions and the existing import, semantic review, Source, exact-PDF
  selection and structure contracts. Runtime error assertions were preserved.

The initial browser attempt passed five cases and failed four solely because the
QA startup copied `public` into an already present `public` directory, producing
`public/public/sw.js`. Next enumerates public assets at server startup, so copying
the missing file afterward did not repair that live instance's 404. The QA copy
was corrected to copy directory contents and the owned standalone server was
restarted; `HEAD /sw.js` then returned 200. No product source, browser assertion,
deadline or security guard was changed for this harness repair. The repository's
production Dockerfile already copies contents using Docker `COPY` semantics.
Both initial and corrected browser diagnostics remain local under separate
result directories rather than overwriting the failed evidence.

Reproduce unit and static checks from the frontend directory:

```sh
pnpm typecheck
pnpm lint
pnpm exec vitest run --maxWorkers=2
```

Production browser contracts comprise `pdf-import-flow.spec.ts`,
`resume-engine-preview.spec.ts`, `resume-structure-flow.spec.ts` and the new
`resume-preview-recovery.spec.ts`. They mock authentication/API/job streams. The
PDF render/import contracts use valid PDF bytes; the new cancellation and account
race cases exercise admission and buffer recovery. They invoke no paid AI providers. The exact-PDF
contract includes mobile/keyboard navigation. These are Chromium contracts, not
Firefox/WebKit certification or a real-backend latency distribution.
