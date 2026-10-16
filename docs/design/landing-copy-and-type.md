# Homepage copy and typography

## Purpose

Explain what Latexy does before asking someone to start. The homepage leads with
résumé building, then demonstrates feedback, tailoring, application tracking,
and the broader LaTeX studio. Each section describes the interaction beside it.

## Editorial choices

- Replace “Your next chapter, well written” with “Turn your experience into a
  résumé.” Name the product category directly above the headline.
- Describe familiar fields and source editing as two ways to write. Avoid making
  the page read as though coding is required.
- Explain ATS feedback as guidance. Do not promise compatibility with every ATS,
  an interview, or a hiring outcome.
- Explain tailoring as reviewing suggestions against real experience. Do not
  imply that missing skills should be invented.
- Explain the tracker through saved, applied, and interview stages, with the
  résumé version and cover letter attached to each application.
- Name the supported compilers when explaining papers and reports. Do not imply
  that the product only creates résumés.
- State guest usage limits and account requirements plainly in the visible FAQ.

These claims correspond to the existing builder, analysis, tailoring, application
and compiler demonstrations in `LandingExperience.tsx`, and the existing studio
entry points. No application functionality or entitlement behavior changes here.

## Type and mobile composition

Use the already bundled, self-hosted Geist Sans for homepage display headings and
body copy. Remove the mixed compressed grotesque/italic headline treatment.
Document samples keep their own distinct template typography; the logo is unchanged.
Scope the changes to the homepage rather than replacing application typography.

Use a medium display weight, less compressed tracking, balanced heading wraps,
and 16px explanatory text with generous line spacing. Keep headings flush left.
Numbered feature labels orient readers on a long phone page without adding a
second navigation bar.

On phones, put layout selection before the sample, show adjacent paper edges to
communicate alternative layouts, and keep one readable HTML document in front.
The full sample remains expandable. The existing focused editor/report views
preserve edits rather than stacking entire desktop workspaces.

## Search and answer usefulness

Keep a descriptive title, canonical URL, and product description. Use the same
title in search/social metadata, rather than a slogan that omits the category.
FAQ structured data is generated from the same questions and answers that people
can expand on the page. Add a direct answer about non-résumé LaTeX documents.

There is no special “AI SEO” schema, hidden answer text, keyword repetition, or
promise of search/AI placement. Useful visible content and accurate metadata are
the basis for this work.

## Research consulted — 16 October 2026

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
  — the same SEO foundations apply to AI features; no additional special schema
  or AI-specific text file is required.
- [Google: Creating helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content)
  — prioritize useful explanations and descriptive headings over search-first prose.
- [USWDS: Typography](https://designsystem.digital.gov/components/typography/)
  — legibility depends on size, measure, hierarchy and spacing, not only font choice.
- [W3C: Understanding text spacing](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html)
  — content must tolerate user spacing adjustments without losing functionality.
- [Practical Typography: Typography in ten minutes](https://practicaltypography.com/typography-in-ten-minutes.html)
  — make deliberate choices about body font, line spacing and line length.

Research informs these choices; it does not establish that a particular typeface
or headline will improve conversion or rankings. That requires real usage data.
