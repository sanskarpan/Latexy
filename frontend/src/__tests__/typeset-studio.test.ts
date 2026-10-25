import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SampleDocument, TypesetReview, TypesetSource, TypesetVersions, TypesetWorkflow } from '@/components/marketing/TypesetStudio'

describe('Typeset Studio public HTML', () => {
    it('renders every workflow destination and readable sample content without client effects', () => {
        const workflow = renderToStaticMarkup(createElement(TypesetWorkflow))
        for (const destination of ['landing-title', 'resume-feedback', 'tailor-application', 'source-to-pdf']) {
            expect(workflow).toContain(`href="#${destination}"`)
        }
        const html = renderToStaticMarkup(createElement(SampleDocument))
        expect(html).toContain('aria-label="Illustrative general résumé"')
        expect(html).toContain('Alex Morgan')
        expect(html).toContain('Led the redesign of the onboarding experience')
        expect(html).not.toMatch(/<(img|canvas)\b/)
    })

    it('keeps ATS, AI, and PDF limitations beside the demonstrations', () => {
        const review = renderToStaticMarkup(createElement(TypesetReview))
        expect(review).toContain('ATS feedback is guidance, not a hiring prediction.')
        expect(review).toContain('Illustrative sample. No AI is running here.')
        expect(review).toContain('Worked with engineering to ship the checkout flow.')
        const source = renderToStaticMarkup(createElement(TypesetSource))
        expect(source).toContain('This is a live HTML layout sample.')
        expect(source).toContain('PDF generation happens in the studio when compilation is enabled.')
        expect(source).toContain('aria-label="Illustrative LaTeX source"')
        expect(source).not.toMatch(/<(img|canvas)\b/)
    })

    it('renders distinct general and research versions using the same sample identity', () => {
        const html = renderToStaticMarkup(createElement(TypesetVersions))
        expect(html).toContain('aria-label="Illustrative general résumé"')
        expect(html).toContain('aria-label="Illustrative tailored résumé"')
        expect(html).toContain('Conducted interviews to understand user needs')
        expect(html.match(/<h3>Alex Morgan<\/h3>/g)).toHaveLength(2)
        expect(html).toContain('Illustrative versions, using the same experience.')
    })

    it('supports independent typeface, spacing, and compact sample rendering', () => {
        const html = renderToStaticMarkup(createElement(SampleDocument, { serif: false, relaxed: true, compact: true }))
        expect(html).toContain('ts-document-sans')
        expect(html).toContain('ts-document-relaxed')
        expect(html).toContain('ts-document-compact')
        expect(html.match(/<li>/g)).toHaveLength(2)
        const defaultHtml = renderToStaticMarkup(createElement(SampleDocument))
        expect(defaultHtml).not.toContain('ts-document-sans')
        expect(defaultHtml).not.toContain('ts-document-relaxed')
        expect(defaultHtml.match(/<li>/g)).toHaveLength(4)
    })
})
