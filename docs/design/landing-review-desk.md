# Latexy — Review Desk

## Selected direction

User selected the second visual concept on 17 October 2026, with a change of typefaces and more direct, useful copy. The revised target preserves the asymmetric résumé and attached review, with the same composition recomposed for phone light and dark themes. The generated target is a design reference only. No generated image is used by the homepage hero.

## Composition

- Desktop: 1280px content measure; two columns, approximately 46/54; headline and actions on the left, live résumé with contextual review on the right.
- Phone: 20px side margins, compact headline, two adjacent actions, touch-sized workflow tabs, readable résumé excerpt and review below. Extra desktop history is omitted from the phone sample.
- Navigation: one theme control, with high contrast and opt-in interface sound in the menu. Public navigation remains usable while capabilities are unresolved.
- Supporting sections: a short next-steps overview; ATS guidance with an interactive sample report; sample application stages; an illustrative LaTeX source/PDF document; honest FAQs; a typographic closing and useful footer directory.
- Existing Baseline mark and semantic theme/contrast tokens are retained.

## Typography

The homepage now pairs Hubot Sans headlines with Mona Sans reading text. The display face uses a carefully chosen width and a strong, consistent weight without relying on italic slogans or excessive letter spacing. The serif inside the résumé and document is Tinos, used to demonstrate document typography, not as the marketing voice.

Fonts are self hosted and limited to this homepage/header/footer. Both new fonts are licensed under SIL OFL 1.1; their notices accompany the WOFF2 files. The UI subset covers Latin/extended Latin and common punctuation. Visual QA found that Windows WebKit rendered the variable fonts too thin despite the correct computed CSS weight. The shipped files are static instances: Hubot 600 at width 95, and Mona 400/500/600 at optical size 20. The four files total 130,288 bytes. They introduce no runtime font service request.

Sources:
- https://github.com/github/hubot-sans — geometric details and variable width for display typography.
- https://github.com/github/mona-sans — reading typography, optical sizing, variable weights, and OFL distribution.
- Fontshare's Cabinet Grotesk and Switzer were also considered; the final choice uses an open font licence suitable for this public repository.

## Copy and search

The title identifies the product: Resume Builder, ATS Feedback & LaTeX Studio. The visible introduction states the actual task: build without code, review structure, tailor for a role, export a PDF. Supporting headings answer distinct needs rather than repeating search terms. Canonical, social metadata, SoftwareApplication schema, Search Console ownership verification and FAQ schema are preserved. FAQ structured data uses the same answers visible on the page.

No claims about hiring outcomes, ATS compatibility guarantees, compile timings, customer counts or testimonials are invented. Guest use is limited; saved work and the guided builder require an account, and plan/capability restrictions remain enforced. The public fallback is retained.

Research:
- https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- https://developers.google.com/search/docs/appearance/ai-features

Google's guidance prioritises helpful, descriptive text, readable page content and accurate structured data. It specifies no separate markup requirement for its AI search features. This redesign does not promise rankings or add speculative GEO/AEO files.

## Components and motion

The stage selection is adapted from Manu Arora's free Aceternity Tabs interaction, using the existing framer-motion runtime. Radix provides keyboard activation, roving focus, panel relationships and inactive-panel handling. The free source's stacked hidden cards and fixed large gap are not retained. No paid page source is used.

- Reference: https://ui.aceternity.com/components/tabs
- CLI/source research: https://ui.aceternity.com/docs/cli
- Page art-direction references: Folio, Parley and Kestrel public previews at https://ui.aceternity.com/pages

The hero is real text and controls. No WebGL dependency, image, canvas, API call or storage is required by the sample. Review actions update the résumé and can be undone. Editing and layout changes preserve sample text; revisiting resets the sample. Tailoring is labelled illustrative. Export opens the existing capability-gated studio rather than pretending to create a PDF. No package upgrade, Tailwind migration or duplicate animation runtime is needed.

Motion is limited to selected-state transitions, panel entry and short section reveals. Reduced motion disables those effects. Sound remains off until explicitly enabled through the menu.

## Verification

See design-qa.md for the visual comparison and final verification status. Browser tests replace obsolete gallery/old-workbench checks with contracts for the approved review desk; existing navigation, capability, sound, privacy and studio tests remain in place. No unrelated product logic or release/deployment hold is changed.
