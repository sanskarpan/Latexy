import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const landingSource = readFileSync(
    fileURLToPath(new URL('../app/page.tsx', import.meta.url)),
    'utf8'
)
const entrySource = readFileSync(
    fileURLToPath(new URL('../components/marketing/MarketingSections.tsx', import.meta.url)),
    'utf8'
)
const footerSource = readFileSync(
    fileURLToPath(new URL('../components/marketing/MarketingFooter.tsx', import.meta.url)),
    'utf8'
)
const pricingSource = readFileSync(
    fileURLToPath(new URL('../app/pricing/page.tsx', import.meta.url)),
    'utf8'
)

describe('homepage compile claims', () => {
    it('describes previews without promising an uncertified end-to-end duration', () => {
        expect(landingSource).toContain('Professional PDF output')
        expect(landingSource).not.toMatch(/sub[\s-]?second/i)
        expect(landingSource).not.toMatch(/compiled\s+\d+(?:\.\d+)?\s*(?:ms|s)\b/i)
    })

    it('retains the existing entry point and public ownership verification', () => {
        expect(landingSource).toContain('<MarketingCTA label="Try the studio" />')
        expect(entrySource).toContain("label = 'Build my résumé'")
        expect(entrySource).toContain("href = '/try?mode=visual'")
        expect(entrySource).toContain('<CapabilityGate feature="a09">')
        expect(entrySource).toContain('<CapabilityGate feature="b01">')
        expect(entrySource).toContain('<CapabilityGate feature="c01">')
        expect(footerSource).toContain(
            '<CapabilityGate feature="a09"><CapabilityGate feature="b01"><CapabilityGate feature="c01">'
        )
        expect(pricingSource).toContain(
            '<CapabilityGate feature="a09"><CapabilityGate feature="b01"><CapabilityGate feature="c01">'
        )
        expect(pricingSource).toContain('<CapabilityGate feature="i01">')
        expect(pricingSource).toContain('href="/billing"')
        expect(landingSource).toContain("google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs'")
    })
})
