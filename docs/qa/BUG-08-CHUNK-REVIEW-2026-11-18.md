# BUG-08 React chunk review — 2026-11-18

## Decision

Accepted two additional reviewed byte-sets into the BUG-08 tamper-evidence
gate:

- `react-6b61a8d1` — PR #2046
- `react-cc389d03` — PR #2048

Both are exact-hash pins. The gate still accepts only these reviewed byte-sets,
and any unreviewed chunk still fails closed. No package manifest or lockfile was
changed.

## Pull requests and builds

| Item | PR #2046 | PR #2048 |
| --- | --- | --- |
| PR | https://github.com/sanskarpan/Latexy/pull/2046 | https://github.com/sanskarpan/Latexy/pull/2048 |
| Branch | `dependabot/npm_and_yarn/npm-minor-and-patch-b4d7a6816d` | `dependabot/npm_and_yarn/npm-minor-and-patch-5fc755bea2` |
| Head SHA | `8380e82a7fcd4060b106ec976d99a46d0fb29c04` | `07a6aa4d7c8cc3d2c09ae160ad8778e270b7607c` |
| CI run | https://github.com/sanskarpan/Latexy/actions/runs/42594567718 | https://github.com/sanskarpan/Latexy/actions/runs/43840223919 |
| `hydration-bundle-review` artifact | `13663525101` | `14213675049` |
| Artifact expires | 2026-11-23T09:38:36Z | 2026-11-30T09:32:54Z |
| Cross-Browser result | failed: `Original-case owner-isolation hydration diagnostic could not be verified` | failed: same diagnostic error |
| Cross-Browser job | [129084118669](https://github.com/sanskarpan/Latexy/actions/runs/42594567718/job/129084118669) | [133206852113](https://github.com/sanskarpan/Latexy/actions/runs/43840223919/job/133206852113) |

The Frontend Build job runs `pnpm build`, then
`scripts/ci/collect-hydration-bundle.mjs` copies the one 150–200 KB chunk
containing the reviewed `function rD(e){var n=Error(i(418,` anchor from
`frontend/.next/static/chunks`. Those are the same bytes the Cross-Browser
Quality job serves from its disposable production build.

### Vercel preview check for PR #2048

- Preview URL: https://latexy-frontend-git-de-55e87d-sanskar-pandeys-projects-7732c7d9.vercel.app
- Vercel inspect URL: https://vercel.com/sanskar-pandeys-projects-7732c7d9/latexy-frontend/FM912ZETMG3Jd5Fd1uwv6kxbedg9
- Deployment identifier in the fetched HTML: `dpl_D57vjxNwUVmGZNDVWj4yF5YKDFRm`
- Fetch result: HTTP 200, 334,786 bytes; no authentication challenge.
- The preview is a **Turbopack** build. Its HTML contains 189
  `/_next/static/immutable/chunks/` references and zero
  `/_next/static/chunks/` references, so it does not serve the Webpack chunk
  that the Playwright gate observes. The authoritative Webpack bytes for this
  review are therefore the Frontend Build artifact above, not the Vercel
  preview response.

## Reviewed byte sets

| Variant | Chunk | SHA-256 | Bytes | Claim column | Last column | Header bytes | Implementation bytes | Implementation SHA-256 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `react-3ea14a6d` (existing reference) | `/_next/static/chunks/bb3797b0-cb37aa562aab9c82.js` | `3ea14a6d5ba4985d418ae811b25f38c0a2a7e2a64f935bc032adc4f35602a08b` | 173132 | 35053 | 35059 | 141 | 172991 | `e6604c561c5dad505ada5a21b724933432022bf7fce468ca7a0d21c1b202f274` |
| `react-6b61a8d1` (new, #2046) | `/_next/static/chunks/d1346401-5b33fe58e024623e.js` | `6b61a8d1e2c080abf2b51ee0bf7e82350b3eef910d0d7c6c7b60d80594960372` | 173132 | 35053 | 35059 | 141 | 172991 | `e6604c561c5dad505ada5a21b724933432022bf7fce468ca7a0d21c1b202f274` |
| `react-cc389d03` (new, #2048) | `/_next/static/chunks/7edc1f54-58736c01cf0589d0.js` | `cc389d03e19cffdc2cc5247977f3252741e765d79b44a6a927bc0bcaf24a7674` | 173133 | 35054 | 35060 | 142 | 172991 | `e6604c561c5dad505ada5a21b724933432022bf7fce468ca7a0d21c1b202f274` |

The reference row is the current reviewed main bundle. The helper already
records that its implementation suffix is byte-identical to canonical
`630253d5-0ac8e4a42daf72ba.js` (canonical SHA-256
`30a7c6602658fd76f41b975311e1e5a04c2cfafa17950130029f2184e13c3f8d`,
173132 bytes), whose implementation SHA-256 is the same
`e6604c561c5dad505ada5a21b724933432022bf7fce468ca7a0d21c1b202f274`.

Artifacts were downloaded without credentials and without writing to the
repository:

```text
gh run download 42594567718 -n hydration-bundle-review -D <tmp>/artifact-2046
gh run download 43840223919 -n hydration-bundle-review -D <tmp>/artifact-2048
gh run download 42358816614 -n hydration-bundle-review -D <tmp>/artifact-main
```

## Comparison result

Both new candidates have a **byte-identical 172,991-byte implementation suffix**
to the reviewed reference and to canonical. Only the Webpack header IDs before
the first `function ` differ:

- reference: `push([[7583],{64398:...t(92550),a=t(7303),o=t(39117),u=t(2848)`
- #2046: `push([[8264],{64464:...t(76732),a=t(757),o=t(21139),u=t(94018)`
- #2048: `push([[4102],{72312:...t(46084),a=t(67885),o=t(4827),u=t(28090)`

The #2048 header is one byte longer because its module IDs are five digits;
#2046 has the same header length as the reference. The complete React
implementation suffix, including the `rD` claim site at the reviewed columns,
is unchanged. This is not a materially different React runtime and does not
require re-certifying the Next 15.5.29 hydration backport.

Reproduction (run against the downloaded artifacts):

```text
node scripts/ci/review-react-chunk.mjs <candidate.js> \
  --canonical <reviewed-reference.js> \
  --expect-sha256 <64-hex> \
  --expect-bytes <n> \
  --expect-implementation-sha256 e6604c561c5dad505ada5a21b724933432022bf7fce468ca7a0d21c1b202f274
```

Both runs returned `"ok": true` with
`implementation_matches_canonical: true`. See
`scripts/ci/review-react-chunk.mjs`.

## Changes made

- `frontend/e2e/helpers/legacy-settings-hydration-diagnostics.ts` — added exact
  pins `react-6b61a8d1` and `react-cc389d03` with run/artifact evidence.
- `frontend/src/__tests__/legacy-settings-hydration-diagnostics.test.ts` —
  added success, drift, unselected-chunk, and project-metadata coverage for both
  variants. `pnpm --dir frontend exec vitest run
  src/__tests__/legacy-settings-hydration-diagnostics.test.ts` reports
  **121 passed**.
- `scripts/ci/review-react-chunk.mjs` — new dependency-free review helper.

## Remaining blocker

The helper now accepts both new byte-sets, but
`frontend/playwright.config.ts` still selects `react-3ea14a6d` for the Chromium
project. That file is outside this workstream's scope. Cross-Browser Quality
will keep failing until the selected metadata matches the build under test:
`react-cc389d03` for PR #2048 and `react-6b61a8d1` for PR #2046 (or a
per-branch/per-build selection mechanism). The gate must not auto-detect the
variant; an explicit reviewed pin is the point of the check.

Separate non-chunk blocker: the updated Better Auth test now asserts the
security invariant for direct client ID-token sign-in, and fails on Better Auth
1.7.18 because 1.7.18 actually creates/links the account and issues a session
cookie with HTTP 200. The original Frontend Lint failure was job 129084118603
(`AssertionError: expected 200 to be greater than or equal to 400`); removing
that status-only assertion exposes the stronger failure. In a disposable
1.7.18 repro, the updated test reports **4 failed / 12 passed**, all four
failures on the session-cookie assertion. The production fix belongs in
`frontend/src/lib/oidc-provider.ts` (outside this workstream). In the same
1.7.18 repro, rejecting the direct path via
`provider.getUserInfoFromIdToken = async () => null` keeps the normal redirect
callback working and makes all 16 Better Auth tests pass. Provider-wide
`disableIdTokenSignIn` is not suitable because it also disables JWKS
verification for the redirect callback (the valid callback then fails with
`unable_to_get_user_info`).
