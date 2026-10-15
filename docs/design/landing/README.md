# Actual landing-page screenshots

These are actual browser renders copied unchanged from the CI artifact.

- Captured source: `5f6803960196da3241a202842dff71698695d6af`
- Frontend tree: `de0ad31803e95da12c305c1e4b7c0cab0977ff9f`
- [Capture workflow](https://github.com/sanskarpan/Latexy/actions/runs/38694684031)
- Desktop: 1440 x 1000 CSS viewport, full page, Chromium at scale 1.
- Mobile: Playwright Pixel 7 profile, 412 CSS pixels wide, full page.
- Both themes use the actual mode control. Fonts and visible images load before capture; animations are disabled for inspection.
- Focused hero captures show the real HTML document scene. Narrow captures verify all three native layouts without WebGL. Footer captures preserve the approved brand signature.
- CI uses isolated anonymous-session and allowed-feature fixtures; these do not claim live production backend contact.

`capture.json` records artifact provenance, dimensions and hashes. The publication commit must preserve the captured frontend tree.
