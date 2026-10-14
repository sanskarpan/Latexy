# Actual landing-page screenshots

These are actual browser renders copied unchanged from the CI artifact.

- Captured source: `2e77fe739cf99ea808acc2e94a0841055ba7a6a7`
- Frontend tree: `d01ba777b9aa7efb92b677ffb0034528824dd9cb`
- [Capture workflow](https://github.com/sanskarpan/Latexy/actions/runs/38551530713)
- Desktop: 1440 x 1000 CSS viewport, full page, Chromium at scale 1.
- Mobile: Playwright Pixel 7 profile, 412 CSS pixels wide, full page.
- Both themes use the actual mode control. Fonts and visible images load before capture; animations are disabled for inspection.
- Focused footer captures show the Footer.design-inspired revision and the approved brand signature.
- CI uses isolated anonymous-session and allowed-feature fixtures; these do not claim live production backend contact.

`capture.json` records artifact provenance, dimensions and hashes. The publication commit must preserve the captured frontend tree.
