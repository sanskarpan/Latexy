import { siteUrl } from '@/lib/site-url'

export function GET() {
    const origin = siteUrl()
    const body = `# Latexy

> A résumé builder with visual editing, optional LaTeX source editing, AI writing assistance, and PDF export.

## Product
- [Overview](${origin}/platform): Résumé editing, job tailoring, cover letters, interview preparation, and application tracking. Saved workspace features require an account.
- [Templates](${origin}/templates): Browse résumé and document layouts.
- [Try the editor](${origin}/try?mode=visual): Start with an editable sample. Drafts in this anonymous editor are saved in the current browser. PDF and AI usage can be limited.
- [Pricing](${origin}/pricing): Plan overview; billing displays current prices and limits.
- [Guides](${origin}/resources): Practical résumé writing and job tailoring guidance.
- [FAQ](${origin}/faq): Product questions and score limitations.
- [Developer tools](${origin}/developer): Advanced integrations and source-oriented workflows.

## Interpretation
Résumé and keyword scores are guidance based on document checks, not an employer's ATS score or a hiring prediction. Visual editing supports recognised text and preserves custom layout elements; PDF preview is the final layout reference. AI suggestions require review for factual accuracy.
`
    return new Response(body, {
        headers: {
            'Content-Type': 'text/plain; charset=utf-8',
            'Cache-Control': 'public, max-age=3600',
        },
    })
}
