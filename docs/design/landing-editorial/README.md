# Landing-page browser evidence

Actual production-bundle renders captured after source commit `bd989cdf2ee653aa748e2617e685dab24fecadaa` in [CI run 38955373292](https://github.com/sanskarpan/Latexy/actions/runs/38955373292).

- Frontend tree: `f9cc96f30f5f01162619fc2cb5c325daaa627a73`. The evidence branch preserves this exact tree.
- Screenshot artifact: `12072050312`. Every source PNG was checked against the hash in the CI capture manifest before publication.
- Desktop: 1440 × 1000 CSS viewport at scale 1. Hero images are exact viewport crops of full-page PNGs.
- Phone first screens: 320, 390 and 430 CSS pixels wide, 844 CSS pixels high, scale 2.625. Full phone pages use Playwright's Pixel 7 profile.
- Other PNGs are unchanged test attachments. Capture provenance records dimensions, hashes and any crop.
- Anonymous-session and controlled-feature fixtures establish the committed UI, without claiming live backend availability.
- The phone contract verifies actual painted heading pixels after light/dark switching, alongside input, layout, keyboard and reduced-motion behavior.

The product hero is selectable HTML. No document screenshot is embedded in the page.
