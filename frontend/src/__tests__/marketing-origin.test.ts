import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import LandingPage, { metadata as homeMetadata } from '@/app/page'
import { metadata as platformMetadata } from '@/app/platform/page'
import { metadata as resourcesMetadata } from '@/app/resources/page'
import { metadata as faqMetadata } from '@/app/faq/page'
import { metadata as pricingMetadata } from '@/app/pricing/page'
import sitemap from '@/app/sitemap'
import robots from '@/app/robots'
import { GET as llms } from '@/app/llms.txt/route'
import { siteUrl } from '@/lib/site-url'

afterEach(() => vi.unstubAllEnvs())

describe('marketing origin consistency', () => {
    it('keeps page canonicals, application schema, and discovery on the configured origin', async () => {
        const origin = 'https://resume.example.org'
        vi.stubEnv('NEXT_PUBLIC_APP_URL', `${origin}/`)
        const pages = [
            [homeMetadata, '/'],
            [platformMetadata, '/platform'],
            [resourcesMetadata, '/resources'],
            [faqMetadata, '/faq'],
            [pricingMetadata, '/pricing'],
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
        expect(sitemap().every(item => item.url.startsWith(origin))).toBe(true)
        expect(robots().sitemap).toBe(`${origin}/sitemap.xml`)
        const text = await llms().text()
        expect(text).toContain(`${origin}/try?mode=visual`)
        expect(text).not.toContain('https://latexy.xyz')
    })
})
