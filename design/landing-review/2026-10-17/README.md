# Latexy landing refresh review

## Production baseline

Captured from `https://latexy.xyz` on 2026-10-17 before the change.

- [Production desktop](production-desktop.png)
- [Production mobile](production-mobile.png)

The desktop hero put the résumé gallery high on the right while the headline and actions sat much lower. On phone widths, the header, hero actions, layout picker, and résumé sample clipped horizontally.

## Refined direction

The implementation builds on the current `main` landing page, including its editable HTML résumé gallery and five interactive product chapters. It balances the copy and sample in the opening, uses a paper-and-ink palette, and presents an editable fictional résumé for Alex Morgan. The headline is “Write a résumé. Own every word.” Copy describes existing product capabilities: guided fields, LaTeX source editing, role-specific versions, and PDF export.

Typography now uses the bundled Bricolage Grotesque for display headings and Geist Sans for reading and interface text. The résumé sample retains its own specimen typography; code stays monospaced. No sound is activated by default.

The proposal images below were captured during the earlier layout iteration, before the final typography pass. They remain useful for reviewing layout and narrow-width wrapping, but **they are not final visual approval captures for the current font styling**.

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

## Browser and entitlement verification status

The earlier proposal captures used a disposable local preview with fictional résumé data, a temporary Times New Roman fallback for Tinos, and an entitlement fixture. Those temporary settings were removed. The exact locked frontend dependencies are now installed with pnpm 10.10.0. The current browser inventory for this execution environment is empty; Chrome and the in-app browser provider both report unavailable, so fresh final-font screenshots and interaction captures could not be taken here.

The local API is unavailable, so the real entitlement provider remains in its fail-closed state. The public `/platform` fallback stays visible. The added test exercises the actual `MarketingCTA` and `CapabilityGate`: the studio link remains hidden until all required grants are present, and disappears if a grant is removed. Existing tests continue to cover template and route gating. This verifies the enabled and denied states in tests; it is not a claim of an enabled-state browser capture.

## Checks

- Exact locked dependency install: passed; pnpm 10.10.0 and the repository hydration check succeeded.
- ESLint on changed TSX files: passed with zero warnings.
- Prettier on the changed landing CSS and page module: passed.
- Focused Vitest: 4 files, 35 tests passed.
- Local production-mode Next server: `/`, `/platform`, `/pricing`, `/resources`, `/login`, and `/try?mode=visual` returned HTTP 200. This is a route smoke check, not browser rendering.
- Production build: compilation, type checking, page-data collection, and all 44 static pages completed. Next then failed while packaging standalone traces because Windows denied dependency symlink creation (`EPERM`). The build used process-only `https://localhost:5180` auth URL values to satisfy production passkey URL validation; no project or production configuration was changed.

No preview fixture, font fallback, entitlement shim, secret, or production configuration change is included in the branch.
