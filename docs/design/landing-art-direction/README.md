# Landing review evidence

Actual browser screenshots captured after source commit `5bbf7fa80dd4f924c392fc0c75768f81e07a6715`.

- Source frontend tree: `de1c3ded008dd226dfb446322068e4563166e575`.
- Actual production-bundle renders from Linux CI run `38783439606`, artifact `11998571304`. These are not generated mockups or screenshots of the reference image.
- Anonymous HTTP fixtures supply product access; all sample documents are synthetic.
- Desktop: 1440 × 1000 CSS viewport, 1x density. Full-page images preserve the original screenshot. `hero-*.png` are the top 1000px cropped from those actual full-page screenshots.
- Mobile first screens: 320/390/430 × 844 CSS viewports at the Pixel 7 device density. Full mobile pages use the project's Pixel 7 viewport.
- `provenance.json` records original pixel dimensions and SHA-256 digests.
- Source/render comparisons and the section review are described in the root `design-qa.md` on this evidence branch.

The production frontend build, Vercel deployment, cross-browser quality and real compile/preview checks passed for this source commit. The quality report records 185 passed, 10 device-inapplicable skips, zero failed and zero flaky cases across Chromium, Firefox and WebKit desktop/phone projects. The downloaded artifact's SHA-256 was verified before extracting the screenshots. Review files are kept on a separate evidence branch; the tested frontend tree is unchanged.

## Desktop

![Actual light hero](hero-light.png)
![Actual dark hero](hero-dark.png)

## Phone

![Actual phone light](mobile-390-light.png)
![Actual phone dark](mobile-390-dark.png)
