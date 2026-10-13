# Actual landing-page screenshots

These files are actual browser renders of the committed application, copied unchanged from the CI artifact.

- Captured source: `acc6c07f0ed3f706e832560040047b23597f6da7`
- Frontend tree: `3f47e634e3aea80e41a7aafd4e0d9a41c2c87a18`
- [Capture workflow](https://github.com/sanskarpan/Latexy/actions/runs/38476370222)
- Desktop: 1440 x 1000 CSS viewport, full page, Chromium at device scale 1.
- Mobile: Playwright Pixel 7 profile (412 CSS pixels wide), full page.
- Both themes use the page's real mode control. Fonts and visible images load before capture; animation is disabled for inspection.
- Captures include the final gallery alignment and builder date/list corrections.
- The case uses isolated anonymous-session/allowed-feature fixtures. These screenshots do not claim that production backend services were contacted.

`capture.json` records the source, artifact digest, image dimensions and hashes. The screenshot publication commit leaves the captured frontend tree unchanged.
