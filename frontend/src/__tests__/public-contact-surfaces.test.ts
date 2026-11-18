import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
    BILLING_EMAIL,
    CONTACT_DOMAIN,
    LEGAL_EMAIL,
    PRIVACY_EMAIL,
    SUPPORT_EMAIL,
    mailtoHref,
} from '@/lib/contact'

const frontendRoot = process.cwd()
const repoRoot = path.resolve(frontendRoot, '..')

function readFromFrontend(...segments: string[]): string {
    return fs.readFileSync(path.join(frontendRoot, ...segments), 'utf8')
}

/**
 * The public surface this workstream owns. Every one of these files is served
 * to users or copied into the published legal pages, so none may advertise an
 * address on a domain without mail routing.
 */
const publicSurfaceFiles = [
    path.join(repoRoot, 'legal', 'terms-of-service.md'),
    path.join(repoRoot, 'legal', 'privacy-policy.md'),
    path.join(frontendRoot, 'public', 'legal', 'terms-of-service.md'),
    path.join(frontendRoot, 'public', 'legal', 'privacy-policy.md'),
    path.join(frontendRoot, 'src', 'lib', 'contact.ts'),
    path.join(frontendRoot, 'src', 'lib', 'email.ts'),
    path.join(frontendRoot, 'src', 'app', 'accessibility', 'page.tsx'),
    path.join(frontendRoot, 'src', 'app', 'faq', 'page.tsx'),
    path.join(frontendRoot, 'src', 'components', 'marketing', 'LandingFooter.tsx'),
    path.join(frontendRoot, 'src', 'components', 'marketing', 'MarketingFooter.tsx'),
]

const terms = fs.readFileSync(publicSurfaceFiles[0], 'utf8')
const privacy = fs.readFileSync(publicSurfaceFiles[1], 'utf8')

describe('public contact surfaces', () => {
    it('does not publish an address on the parked .com domain', () => {
        for (const file of publicSurfaceFiles) {
            const source = fs.readFileSync(file, 'utf8')
            const label = path.relative(repoRoot, file)
            expect(source, label).not.toContain('latexy.com')
            expect(source, label).not.toContain('@latexy.com')
        }
    })

    it('keeps the source and published legal copies byte-identical', () => {
        const pairs = [
            ['legal/terms-of-service.md', 'public/legal/terms-of-service.md'],
            ['legal/privacy-policy.md', 'public/legal/privacy-policy.md'],
        ] as const

        for (const [source, published] of pairs) {
            const sourceBytes = fs.readFileSync(path.join(repoRoot, source))
            const publishedBytes = fs.readFileSync(path.join(frontendRoot, published))
            expect(publishedBytes.equals(sourceBytes), source).toBe(true)
        }
    })

    it('exports one source of truth on the intended contact domain', () => {
        expect(CONTACT_DOMAIN).toBe('latexy.xyz')
        expect(SUPPORT_EMAIL).toBe('support@latexy.xyz')
        expect(PRIVACY_EMAIL).toBe('privacy@latexy.xyz')
        expect(LEGAL_EMAIL).toBe('legal@latexy.xyz')
        expect(BILLING_EMAIL).toBe('billing@latexy.xyz')
        expect(mailtoHref(SUPPORT_EMAIL)).toBe('mailto:support@latexy.xyz')
        expect(mailtoHref(SUPPORT_EMAIL, 'Accessibility support')).toBe(
            'mailto:support@latexy.xyz?subject=Accessibility%20support'
        )
    })

    it('moves the transactional email fallback off the unresolvable domain', () => {
        const emailSource = readFromFrontend('src', 'lib', 'email.ts')
        expect(emailSource).toContain("const DEFAULT_FROM = 'Latexy <no-reply@latexy.xyz>'")
        expect(emailSource).not.toContain('latexy.app')
        expect(emailSource).toContain('process.env.EMAIL_FROM || DEFAULT_FROM')
    })

    it('uses the shared constants in the public contact surfaces', () => {
        for (const file of [
            'src/app/accessibility/page.tsx',
            'src/app/faq/page.tsx',
            'src/components/marketing/LandingFooter.tsx',
            'src/components/marketing/MarketingFooter.tsx',
        ]) {
            expect(readFromFrontend(...file.split('/')), file).toContain("from '@/lib/contact'")
        }
    })
})

describe('terms factual corrections', () => {
    it('describes the enforced guest and plan allowances', () => {
        expect(terms).toContain('Last Updated: November 18, 2026')
        expect(terms).toContain('3 compilations and 2 deep analyses')
        expect(terms).toContain('10 compilations per day')
        expect(terms).toContain('3 optimizations per month')
        expect(terms).toContain('25 AI assists per month')
        expect(terms).toContain('400 compilations')
        expect(terms).toContain('100 AI assists per month')
        expect(terms).toContain('monthly or annual')
        expect(terms).toContain('student, and team offers may be available')
    })

    it('does not retain the corrected trial, quota, or retention claims', () => {
        for (const claim of [
            '[Company Address]',
            'Trial usage resets every 24 hours',
            'Converting to paid plan removes all usage limitations',
            'retained for 30 days after cancellation',
            'not stored permanently',
        ]) {
            expect(terms, claim).not.toContain(claim)
        }
    })

    it('states the actual saved-document retention behavior', () => {
        expect(terms).toContain('Saved resumes are retained while your account is active')
        expect(terms).toContain('There is not currently a self-service account-deletion control')
    })
})

describe('privacy contact corrections', () => {
    it('routes privacy requests to the intended domain', () => {
        expect(privacy).toContain('privacy@latexy.xyz')
        expect(privacy).toContain('https://latexy.xyz')
        expect(privacy).not.toContain('@latexy.com')
    })
})
