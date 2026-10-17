import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import LandingPage, { metadata as homeMetadata } from '@/app/page'
import { metadata as platformMetadata } from '@/app/platform/page'
import { metadata as resourcesMetadata } from '@/app/resources/page'
import { metadata as faqMetadata } from '@/app/faq/page'
import { metadata as pricingMetadata } from '@/app/pricing/page'
import { metadata as templatesMetadata } from '@/app/templates/layout'
import { metadata as updatesMetadata } from '@/app/updates/page'
import { metadata as privacyMetadata } from '@/app/privacy/page'
import { metadata as termsMetadata } from '@/app/terms/page'
import { metadata as accessibilityMetadata } from '@/app/accessibility/page'
import sitemap from '@/app/sitemap'
import robots from '@/app/robots'
import { GET as llms } from '@/app/llms.txt/route'
import { siteUrl } from '@/lib/site-url'

// Next compiles localFont at build time; this test exercises metadata and HTML.
vi.mock('@/components/marketing/review-fonts', () => ({ reviewFonts: 'review-fonts' }))

afterEach(() => vi.unstubAllEnvs())

describe('marketing origin consistency', () => {
    it('describes the ATS feedback section in its overview link', () => {
        const html = renderToStaticMarkup(createElement(LandingPage))
        expect(html).toMatch(/href="#resume-feedback"[^>]*>[\s\S]*?Review your résumé[\s\S]*?Explore feedback[\s\S]*?<\/a>/)
        expect(html).toContain('id="resume-feedback"')
        expect(html).toContain('ATS feedback, with context')
    })

    it('keeps page canonicals, application schema, and discovery on the configured origin', async () => {
        const origin = 'https://resume.example.org'
        vi.stubEnv('NEXT_PUBLIC_APP_URL', `${origin}/`)
        const pages = [
            [homeMetadata, '/'],
            [platformMetadata, '/platform'],
            [resourcesMetadata, '/resources'],
            [faqMetadata, '/faq'],
            [pricingMetadata, '/pricing'],
            [templatesMetadata, '/templates'],
            [updatesMetadata, '/updates'],
            [privacyMetadata, '/privacy'],
            [termsMetadata, '/terms'],
            [accessibilityMetadata, '/accessibility'],
        ] as const
        for (const [metadata, path] of pages) {
            expect(new URL(String(metadata.alternates?.canonical), siteUrl()).href).toBe(
                `${origin}${path}`
            )
            expect(new URL(String(metadata.openGraph?.url), siteUrl()).href).toBe(
                `${origin}${path}`
            )
        }
        const html = renderToStaticMarkup(createElement(LandingPage))
        const schema = html.match(/<script type="application\/ld\+json">(.*?)<\/script>/)?.[1]
        expect(JSON.parse(schema || '{}').url).toBe(origin)
        const sitemapHasOrigin = (url: string) => new URL(url).origin === origin
        expect(sitemap().every(item => sitemapHasOrigin(item.url))).toBe(true)
        expect(sitemapHasOrigin(`${origin}.attacker.invalid/sitemap.xml`)).toBe(false)
        expect(robots().sitemap).toBe(`${origin}/sitemap.xml`)
        const text = await llms().text()
        expect(text).toContain(`${origin}/try?mode=visual`)
        expect(text).not.toContain('https://latexy.xyz')
    })

    it('gives public marketing routes distinct metadata and the existing social image', () => {
        const origin = 'https://resume.example.org'
        vi.stubEnv('NEXT_PUBLIC_APP_URL', origin)

        for (const metadata of [templatesMetadata, updatesMetadata, privacyMetadata, termsMetadata, accessibilityMetadata]) {
            expect(typeof metadata.title).toBe('string')
            expect(typeof metadata.description).toBe('string')
            expect((metadata.title as string).trim()).not.toBe('')
            expect((metadata.description as string).trim()).not.toBe('')
            expect(metadata.title).not.toBe(homeMetadata.title)
            expect(metadata.description).not.toBe(homeMetadata.description)
        }

        for (const metadata of [platformMetadata, resourcesMetadata, pricingMetadata, faqMetadata, templatesMetadata, updatesMetadata,
            privacyMetadata, termsMetadata, accessibilityMetadata]) {
            const ogImages = metadata.openGraph?.images
            const twitterImages = metadata.twitter?.images
            expect(Array.isArray(ogImages)).toBe(true)
            expect(Array.isArray(twitterImages)).toBe(true)
            const ogImage = (ogImages as { url: string; width: number; height: number; alt: string }[])[0]
            const twitterImage = (twitterImages as string[])[0]
            expect(new URL(ogImage.url, siteUrl()).href).toBe(`${origin}/opengraph-image`)
            expect(ogImage).toMatchObject({ width: 1200, height: 630, alt: expect.any(String) })
            expect(new URL(twitterImage, siteUrl()).href).toBe(`${origin}/opengraph-image`)
        }

        for (const metadata of [privacyMetadata, termsMetadata, accessibilityMetadata]) {
            expect(metadata.twitter?.title).toBe(metadata.title)
            expect(metadata.twitter?.description).toBe(metadata.description)
        }
    })
})
