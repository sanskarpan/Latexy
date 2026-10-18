# Typeset Studio design QA

## Source and implementation evidence

- Source visual truth: Library file `libfile_a2989417412c8191b02eaeb6b9e0b15d` (`latexy-typeset-studio-concept.png`). Local source path: unavailable.
- Materialization: the official Library helper successfully reached the signed transfer, then failed on Windows at `os.setxattr` with `AttributeError: module 'os' has no attribute 'setxattr'`. It did not install a metadata-preserving local file.
- Implementation screenshot path: none. No image-dependent redesign was made.
- Viewport, source and implementation pixel dimensions, CSS size, density normalization, and interaction state: unavailable because neither required local visual artifact could be captured.
- Full-view and focused-region comparison evidence: unavailable.
- Fonts/typography, spacing/layout, colors/tokens, image quality, and copy/content fidelity: visual comparison blocked.

## Independent availability repair

- Marketing CTA now distinguishes pending, failed (with Retry), denied, visual, and source-only states from effective entitlements and session identity. Public copy describes PDF generation as conditional on availability.
- Homepage, platform, FAQ, and resources copy no longer promise an immediately available studio sample when the relevant capability is denied. The platform, FAQ, and resources pages link to the interactive illustrative homepage sample.
- The existing backend admission and saved-document creation gates were not modified.
- Focused unit tests: 23 passed after the CTA change. Scoped ESLint: passed. Broader marketing unit run: 26 passed, one suite blocked by a missing `@fontsource/tinos` package in the existing dependency tree.
- Full TypeScript check: six errors in untouched auth/OIDC files with the existing dependency tree. No changed-file diagnostics were reported.
- Browser capture and interaction test: blocked by the existing Next hydration integrity guard, which rejected the reused dependency installation (`react-dom-client.development.js, patched`).

## Open findings

- [P1] Selected Typeset Studio composition cannot be implemented or assessed before the exact PNG is readable and visually inspected on this executor.
- [P1] CTA and copy changes have no browser evidence because the local Next runtime cannot start with the available dependencies.
- [P2] The pricing page still has a separate free-tier guest CTA gate requiring `b01`; this was not changed in the narrow repair and should be reconciled when the full landing redesign is reviewed.

No visual QA iteration or before/after screenshots are available.

final result: blocked
