# Typeset Studio landing QA

Visual status: **PASSED for the independently inspected selected-mockup and production regression scope below**. Engineering status: **PASSED for local production build, lint, types, 2,936 unit tests and 53 production Chromium cases (3 intentional skips)**. No unresolved P0/P1/P2 findings remain in that inspected scope. This is close visual fidelity, not pixel-identical reproduction or live-backend certification.

## Scope and provenance

- Selected direction: the user-approved Typeset Studio concept (cream/navy/ochre, serif editorial layout).
- Main inspected before branching: `a5fe33c51ec96113941f76f258b491593de863e4`. Current main `6470eb032396224d07db602f4c57b4958bfe96fd` was integrated locally after the fidelity pass; its delta is backend security #1929.
- Original stacked base: PR #1932, branch `codex/typeset-studio-cta-20261018`, exact SHA `ce0d915caa28b4258433519ff27582afa3f6dba4`. Visual implementation commit: `d09ab4e9`; exact Export-state contracts: `0f50690e`.
- Original visual work used `c720fbe4ebbc012dd30ec1addff491fafc75ba13`; its documentation-only update to `45cdc5f4fa84d81b933c2d4feb58f0cf6b833a15` preserved frontend tree `14ac3d452b4a9151a7db667b93d12577352ae856`. Subsequently `c0c05be6328813bcd9ebbc4648b40956397c5d50` repaired failed-session retry and c05-aware Export copy. The single import conflict was resolved retaining both the base availability logic and the visual branch's demo-state repairs. `ce0d915c` adds only two regression tests.
- Runtime equivalence across the final test-only restack was verified from sorted Git tree entries for `frontend` plus `pnpm-lock.yaml`, excluding `__tests__` and `e2e`: SHA-256 `44d27b9e09f3e8d9ff8b4a47421403312a056ce6cf53fdf5eb8abf80c710558f` before/after. Styles, assets and selected fonts were not changed.
- This branch owns visual structure/styles/assets and landing contracts. The base owns marketing availability logic. No production merge, deployment, or indirect merge of #1930 is included. The local integration commit includes current main as a parent.
- Desktop manual review used the supported cloud browser and a native cloud terminal running Next. Manual preview used local synthetic signed-out availability/auth fixtures, not a live backend.
- Final responsive evidence uses the repository's Playwright quality tests, system Chromium, a production-mode Next bundle (initial `c3Blyp4bNUaUtIORanC2h`; final recovery/c05 build `z-qz33y9sNt76BvNsajEF`) and synthetic API fixtures. Earlier manual/iteration files used development mode. Widths: 320, 390, 768, 1440 CSS pixels; light/dark. A capture-only style suppresses the Next development badge; no application content is masked.
- Root typography remains unchanged. Landing Tinos is locally bundled by `@fontsource/tinos`; existing Reading font assets remain in use. No generic font was substituted to satisfy a build.
- Current still life: newly AI-generated, inspected, converted to WebP (2161 × 728). It contains a printed illustrative Alex Morgan résumé using safe example contact and qualitative bullets, navy notebook, brass pen and olive sprig. Interactive résumé demonstrations remain selectable HTML. The decorative raster is not an export preview.

## Reference comparison and intentional adaptations

Preserved: asymmetric résumé hero, open four-step workflow, review panel, paired general/tailored documents, source/layout preview, restrained FAQ and physical closing still life. The reference's fabricated achievement metrics are absent from all new UI and source examples. Examples use `alex@example.com` and clearly identify their illustrative nature. The review panel does not imply real AI execution or an ATS hiring prediction.

The implementation uses larger, legible document excerpts and real keyboard-operable controls rather than the concept image's miniature page text. On phones, documents and review controls reflow into readable excerpts. Dark mode is an adaptation using the existing semantic tokens; the provided concept is light only.

## Visual iterations

1. Actual desktop inspection found the review annotation intruding over document text (P1). An initial right-hand text lane improved desktop, but independent review subsequently found tablet history/date overlap. This initial fix was insufficient; see iteration 6.
2. Full-page comparison found overly long résumé excerpts and excess FAQ spacing (P2). Shortened repeated supporting excerpts, retained meaningful sample text, tightened section rhythm without shrinking body type.
3. Full-page capture initially missed the lazy closing image (P1 evidence gap). Ensured the image loads reliably and inspected the actual still life.
4. 320px element crops exposed an inherited two-column CTA minimum-width spill (P2). Replaced the phone action grid with wrapping flex, set zero minimum width on the copy and a bounded grid track. Regenerated light/dark pixels confirm the corrected gutters and readable wrap.
5. Next development badge overlapped some evidence (P2 evidence hygiene). Capture-only suppression added and evidence recaptured.
6. Independent review found tablet annotation over a history date/bullet (P1) and overly wide desktop paper (P2 reference fidelity). Reworked the desktop sheet to a portrait aspect with a meaningful angled rear-sheet silhouette and restored truthful sample text density. At tablet widths the annotation now has an independent below-paper row. All-stage tablet/desktop light/dark recapture and text-node overlap checks passed. Independent inspection confirms every date and sentence remains readable.
7. Added clearance between the tilted rear sheet and desktop stage tabs (P2), and made the paired versions portrait documents with existing truthful sample content (P2). Recaptured all sections; independent final pixel review found no unresolved P0/P1/P2 in its inspected sample.

## Interaction and semantic parity

Manual cloud-browser checks verified custom contribution preservation, whitespace validation, Undo and Keep original preserving unsaved drafts, independent review tabs, tailored/general focus, live typeface/spacing changes, theme toggle and expanded ATS FAQ.

#1930 parity is implemented directly without cherry-picking its commit: a starter suggestion cannot replace custom text; blank input does not silently reset the document; applied content is separate from dirty drafts; Undo/Keep original preserve dirty input; ATS text remains explicitly guidance. Browser contracts cover both desktop and mobile.

Inherited capability checks remain intact: shared MarketingCTA selects the available destination, disabled/unavailable services retain a public sample route, templates and billing remain gated, and root loading/reduced-motion/security protections are not removed.

## Historical verification before the 20:18 fidelity re-audit

- Locked dependency install: passed (Node 22, pnpm 10.10.0, frozen lockfile).
- Full repository ESLint: passed.
- TypeScript no-emit: passed.
- Full Vitest suite on final base: **2,936 passed across 296 files**, no failures (50.44 seconds). Earlier recorded trees passed 2,933 and then 2,934 tests before the base added retry regression coverage.
- New HTML/marketing-origin unit contracts: 6 passed.
- Inherited CTA/capability/billing unit contracts: 26 passed.
- Focused browser contracts: 26 passed, 2 intentional project skips.
- Full public-quality desktop/mobile suite before the final hero geometry revision: 43 passed, 3 intentional project skips. No failures. Final-geometry evidence case also passed (72 captures plus text-node overlap and narrow-gutter checks). Production-bundle rerun: **43 passed, 3 intentional project skips, 0 failures**, 2.4 minutes. That initial 72-image matrix used the first production-mode local run; the final recovery/c05 production run recaptures it and adds eight capability-state images.
- Final recovery/c05 production browser suite: **51 passed, 3 intentional project skips, 0 failures**, 3.0 minutes. It includes c05 OFF/ON, loading and error contracts, visual/source routing independent of compilation access, preserved sample controls and no compile POST. Eight additional Export-state screenshots accompany the recaptured 72-image matrix.
- Final exact-copy Export rerun: **8 passed**, 24.1 seconds; explicitly rejects stale/mixed ON/OFF/loading/error paragraph text. Test-file ESLint passed after tightening those assertions.
- Production build: **passed**, including lint/types, static generation and standalone artifact validation. Earlier attempts exposed concurrent-memory exit 137 and missing local HTTPS auth-origin metadata. The serial run used the existing CI/Playwright HTTPS auth-origin convention, without weakening passkey checks. A separate isolated runner encountered Google Fonts DNS; this was not hidden by font substitution. The successful build retained selected fonts and used the documented local-only Playwright test hook and synthetic service origins; it is not a deployment.

## Independent visual review scope

Confirmed on the final 10:50 UTC matrix: 1440 light/dark hero and versions, 1440 light full page, 768 dark full page, 320 light hero/review, 320 dark versions/footer, and 390 dark versions/source. The section reviewer additionally inspected all 16 hero-stage images at 768/1440 in both themes and the paired versions at every width/theme. This does not assert that a single reviewer individually inspected all 72 images, or establish numerical accessibility contrast, backend behavior, or production operation.

## Historical recovery/c05 integration review

The source conflict resolution retained the final base's failed-session retry and all four Export-copy states. The unreachable legacy `ReviewJourney.tsx` has no imports in the application source. The reachable hero uses shared `MarketingCTA` and c05-aware copy; compilation never gates editing itself. CSS, document geometry and fonts are unchanged.

The earlier production-mode rebuild used `z-qz33y9sNt76BvNsajEF`. Additional pixel inspection covers the updated desktop/tablet Export stages in both themes, desktop full-page spotcheck and all eight desktop/mobile availability-state captures. See the independent addendum for exact scope and results.

## Evidence

- `desktop-iteration-1.jpg`, `desktop-iteration-2.jpg`: supported cloud-browser full-page iterations.
- `comparison-iteration-1.jpg`: width-normalized reference versus first rendered iteration.
- `manual-dark-interactions.jpg`: actual cloud-browser dark theme after review/layout/FAQ interactions.
- `typeset-{320,390,768,1440}-{light,dark}-{full,hero,workflow,review,versions,source,footer}.png`: final production-mode responsive test evidence. Additional `hero-{write,review,tailor,export}` captures cover 768/1440 in both themes.
- `typeset-{desktop-chromium,mobile-chromium}-hero-export-{c05-off,c05-on,loading,error}.png`: explicit availability-state evidence.
- `visual-review.md`: independent section-by-section pixel inspection.

Live production backend workflows, actual AI results, real PDF compilation and Firefox/WebKit compatibility are outside these synthetic Chromium landing checks. Do not interpret this report as verification of those services.


## Selected-mockup fidelity re-audit (2026-10-18, 20:18–20:33 UTC)

The earlier scoped visual pass did not establish close mockup fidelity. Direct comparison identified avoidable drift in hero proportions, header action/brand scale, heading weight, lower-section grids, editor detail and closing imagery. This iteration corrects those issues:

- Restored a wider layered résumé hero with a preview caption and curved arrow; retained a measured blank annotation lane. Tablet annotations remain below the paper.
- Added the shared availability-aware header action and reference-scale brand.
- Compared regular and bold Tinos in the supported cloud browser; regular 400 editorial headings are closer to the reference, while résumé names remain bold.
- Corrected section-specific review/versions/source grids, long workflow connectors with fixed-size standard icon arrowheads, source line numbers and syntax color.
- Replaced the blank-paper still life with a generated printed illustrative résumé, navy notebook, pen and olive sprig; integrated it into the full-width closing band and restored the secondary example link.
- Matched paired-document density to a single role and four truthful bullets. Removed unnecessary earlier-role repetition and tightened desktop spacing without shrinking controls.
- New intermediate-width contract checks all four hero stages at 1101, 1180 and 1280px for annotation/text occlusion, action/tab collision and horizontal overflow. All 12 targeted browser contracts passed against the development preview.
- Responsive evidence refreshed at 20:33:33 UTC, 320/390/768/1440px, light/dark, plus tablet/desktop hero stages. Synthetic b10 availability is ON for reference-state screenshots; explicit OFF/error/loading contracts remain.

Remaining intentional differences: truthful feature availability and illustrative-sample labels replace unsupported promises/metrics; extra working controls and accessible Menu remain; generated still life is a faithful re-creation rather than the exact concept raster; mobile and dark themes are responsive adaptations because no selected mockups exist for them. Exact pixel identity is not claimed. Final production and independent visual results follow after verification.

### Production-only regression discovered and repaired

A manual production screenshot exposed a stale Next optimized-image cache for the reused stationery filename: the old blank-paper image placed the notebook behind closing text. This was a genuine visual blocker missed by development-only evidence. Renamed the asset to `typeset-still-life-printed.webp`, rebuilt, and verified the actual loaded production image is the new wide printed résumé. The screenshot test now requires the versioned URL and loaded image aspect ratio greater than 2.9. The supported cloud browser's refreshed 1180px full-page capture is `typeset-1180-production-full.png`; independent review confirms the image/cache and text-legibility defect is resolved. Canonical responsive production recapture follows.

## Final fidelity verification, 20:45 UTC

- Unified baseline: current main `6470eb032396224d07db602f4c57b4958bfe96fd`, with #1932 `ce0d915caa28b4258433519ff27582afa3f6dba4` dependencies included. #1930 remains unmerged; its custom-text/blank-validation/Undo/Keep-original/ATS behavior is directly covered.
- Rendered implementation: `2e3c7696`; final test head: `c4dcd55808d7956347a14622bcb22e17a628e5b8`. Runtime/source hash excluding tests: `4a16566e1851fab8d3a50d2cb8c5547609145d51ebfc5f5b0c11314eff793b12`; unchanged by the test-only follow-up.
- Production build: `TzhaFSVYpMX5dDc4W5Vq3`, successful compilation, lint/types, 44 static pages, standalone artifact validation. Selected typography retained; no generic-font substitution.
- Full ESLint and TypeScript no-emit: passed. Frozen dependency installation was already verified and dependency manifests/lockfile are unchanged by this fidelity pass.
- Full Vitest rerun: **2,936 passed / 296 files**, zero failures.
- Production public-quality + Typeset Studio Chromium desktop/mobile: **53 passed, 3 intentional project skips, zero failures**, 3.1 minutes. Loading/error layouts at1101px, all hero stages at1101/1180/1280px,320/390 closing-action separation, real versioned image geometry, custom-text preservation, blank validation and availability-conditioned destinations/copy are checked.
- Independent final production pixel review:1440 light full page,1440 dark footer,390 light/dark footer, and supported-browser1180 full page. This supplements the20:33 scoped matrix review recorded in visual-review.md. Correct printed image, phone action spacing and all reported blockers are resolved. This does not mean every screenshot was independently inspected.
- Generated compiler bookkeeping was restored and excluded from the commit. No publication, merge or deployment is asserted by these local checks.
