# Typeset Studio design QA

## Source and implementation evidence

- Source visual truth: Library file `libfile_a2989417412c8191b02eaeb6b9e0b15d` (`latexy-typeset-studio-concept.png`). Local source path: unavailable.
- Materialization: the official Library helper successfully reached the signed transfer, then failed on Windows at `os.setxattr` with `AttributeError: module 'os' has no attribute 'setxattr'`. It did not install a metadata-preserving local file.
- Implementation screenshot path: `C:\Users\Sansk\Documents\Codex\2026-10-18\task-2\evidence\cta-20261018\` (local browser evidence, outside the repository). No image-dependent redesign was made on this executor.
- Browser viewports: desktop 1440 × 900 and mobile 390 × 844, each with reduced motion. The selected reference dimensions and density normalization remain unavailable.
- Full-view and focused-region comparison evidence: unavailable.
- Fonts/typography, spacing/layout, colors/tokens, image quality, and copy/content fidelity: visual comparison blocked.

## Independent availability repair

- Marketing CTA now distinguishes pending, failed (with Retry), denied, visual, and source-only states from effective entitlements and session identity. Public copy describes PDF generation as conditional on availability.
- Homepage, platform, FAQ, and resources copy no longer promise an immediately available studio sample when the relevant capability is denied. The platform, FAQ, and resources pages link to the interactive illustrative homepage sample.
- The existing backend admission and saved-document creation gates were not modified.
- Locked dependency installation: `pnpm install --frozen-lockfile` succeeded with the project-pinned pnpm 10.10.0. The Next hydration integrity postinstall check passed.
- Final-head checks after that installation: full frontend TypeScript (`tsc --noEmit`) passed; full frontend ESLint (`--max-warnings=0`) passed; four targeted Vitest files passed (28 tests).
- Direct Playwright Chromium check passed at both viewports: denied CTA and fallback route, platform sample link and destination, visual editor route, source-only route, failed entitlement request followed by Retry, no horizontal overflow, and no uncaught page errors. Full-page screenshots were saved for each state in the local evidence directory above.
- The repository's Playwright quality wrapper could not run on this Windows executor because `playwright-server.mjs` failed with `EPERM` while creating a symlink. The direct browser check does not replace the complete repository browser suite.

## Open findings

- [P1] Selected Typeset Studio composition cannot be implemented or assessed before the exact PNG is readable and visually inspected on this executor.
- [P2] The pricing page still has a separate free-tier guest CTA gate requiring `b01`; this was not changed in the narrow repair and should be reconciled when the full landing redesign is reviewed.

The current homepage and platform CTA states were visually inspected at desktop and mobile sizes. A selected-concept comparison, visual redesign iteration, and reference before/after screenshots remain blocked on this executor.

final result: blocked
