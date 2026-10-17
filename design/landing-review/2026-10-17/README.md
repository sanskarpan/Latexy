# Latexy landing refresh review

## Production baseline

Captured from `https://latexy.xyz` on 2026-10-17 before the change.

- [Production desktop](production-desktop.png)
- [Production mobile](production-mobile.png)

The desktop hero put the résumé gallery high on the right while the headline and actions sat much lower, leaving a large blank area. At phone width, the header, hero buttons, layout selector, and résumé sample were clipped horizontally.

## Refined direction

The change builds on the current `main` landing page, including its editable HTML résumé gallery and five interactive product chapters. It keeps the paper-and-ink palette, brings the copy and sample into a balanced two-column opening, and uses the bundled Geist Sans for the headline. The new headline is “Write a résumé. Own every word.” The supporting copy describes guided fields, LaTeX source editing, role-specific versions, and PDF export.

- [Desktop opening, light](proposal-desktop-light.png)
- [Desktop opening, dark](proposal-desktop-dark.png)
- [Full page, desktop light](full-desktop-light.png)
- [Full page, desktop dark](full-desktop-dark.png)
- [Full page, phone 390px light](proposal-mobile-light.png)
- [Full page, phone 390px dark](proposal-mobile-dark.png)
- [Full page, phone 320px light](proposal-mobile-320.png)
- [Phone first screen, light](proposal-mobile-light-first-screen.png)
- [Phone first screen, dark](proposal-mobile-dark-first-screen.png)
- [Phone first screen, 320px](proposal-mobile-320-first-screen.png)

## Browser evidence

Captured with the installed Chrome 155 against a disposable local preview based on current `main` plus this change. The preview used fictional Alex Morgan sample data. Its temporary `CapabilityGate` fixture rendered the entitled state so the `Try the studio` link and templates link could be reviewed; repository gate code was not changed. The shared install is missing the pinned `@fontsource/tinos` package, so the disposable preview used local Times New Roman as a Tinos fallback. Neither fixture, the font fallback, nor preview configuration is part of the branch.

At 1440px, 390px, and 320px, the document width matched the viewport width. Chrome reported no page errors. In each viewport, selecting Modern moved that layout into the preview and editing the sample name changed the document heading to “Jordan Lee”. The primary hero link targets `/try?mode=visual`.

The local preview returned HTTP 200 for `/platform`, `/resources`, `/pricing`, and `/login`. `/try?mode=visual` returned HTTP 500 because `pdfjs-dist/build/pdf.worker.min.mjs` is missing from the shared install (`ReactPdfClient.tsx` → `pdf-renderer-loader.ts` → `PDFPreview.tsx` → `/try`). That route is unchanged by this redesign.

## Checks

- Target ESLint: passed with zero warnings.
- Prettier: passed for all changed TypeScript and CSS files.
- Focused Vitest: 3 files, 7 tests passed with a temporary alias for the missing Tinos CSS files. The default runner cannot load `marketing-origin.test.ts` because the pinned font package is absent from the shared install; the shim only resolves those CSS imports.
- Production build: blocked before compilation by the shared install's Next hydration backport check: `react-dom-client.development.js` is reported as `patched` when the validator expects the checked-in renderer state. `pnpm run build` also stalled in this environment; direct `next build` confirmed the validator error.

No preview fixture, generated cache, dependency shim, or production configuration change is included in the branch.
