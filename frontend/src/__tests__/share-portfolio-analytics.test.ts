import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('public portfolio analytics transport', () => {
  const transport = read('../lib/analytics/portfolio.ts')

  it('sends nothing unless analytics consent was granted', () => {
    expect(transport).toContain("readAnalyticsConsent() === 'granted'")
    expect(transport).toContain('canCapturePortfolioAnalytics')
    expect(transport.indexOf('canCapturePortfolioAnalytics()')).toBeLessThan(
      transport.indexOf('postCapture('),
    )
  })

  it('posts only the consent attestation and allowlisted paths', () => {
    expect(transport).toContain("JSON.stringify({ analytics_consent: true })")
    expect(transport).toContain('/analytics/view')
    expect(transport).toContain('/analytics/contact')
    expect(transport).toContain("'/portfolio/analytics/claim-signup'")
    for (const forbidden of ['email:', 'message:', 'latex:', 'document:', 'user_agent:', 'ip_address:']) {
      expect(transport).not.toContain(forbidden)
    }
  })

  it('never fetches without a token for signup attribution', () => {
    expect(transport).toContain('if (!token) return false')
    expect(transport).toContain('Authorization: `Bearer ${token}`')
  })
})

describe('public portfolio analytics wiring', () => {
  it('mounts the view capture inside the no-capture portfolio page', () => {
    const page = read('../app/u/[username]/page.tsx')
    expect(page).toContain("import PortfolioAnalytics from '@/components/portfolio/PortfolioAnalytics'")
    expect(page).toContain('<PortfolioAnalytics username={username} />')
    expect(page).toContain('ph-no-capture')
  })

  it('records a contact only after the message is delivered', () => {
    const form = read('../app/u/[username]/ContactForm.tsx')
    const sendIndex = form.indexOf('apiClient.sendPortfolioContact')
    const recordIndex = form.indexOf('recordPortfolioContact(username)')
    expect(sendIndex).toBeGreaterThan(-1)
    expect(recordIndex).toBeGreaterThan(sendIndex)
  })

  it('claims portfolio signup attribution only with analytics consent', () => {
    const authSync = read('../components/AuthSync.tsx')
    expect(authSync).toContain("readAnalyticsConsent() === 'granted'")
    expect(authSync).toContain('claimPortfolioSignup(token)')
  })
})

describe('admin share and portfolio section', () => {
  const component = read('../components/admin/AdminSharePortfolio.tsx')
  const growth = read('../components/admin/AdminGrowth.tsx')
  const api = read('../lib/api-client.ts')

  it('is mounted in the dedicated growth section', () => {
    expect(growth).toContain("import AdminSharePortfolio from '@/components/admin/AdminSharePortfolio'")
    expect(growth).toContain('<AdminSharePortfolio />')
  })

  it('uses dedicated admin aggregate and drill-down endpoints', () => {
    expect(api).toContain('/admin/analytics/share-portfolio')
    expect(api).toContain('/admin/analytics/share-portfolio/resumes/')
    expect(api).toContain('/admin/analytics/share-portfolio/portfolios/')
    expect(component).toContain('getAdminSharePortfolio')
    expect(component).toContain('getAdminSharePortfolioResume')
    expect(component).toContain('getAdminSharePortfolioPortfolio')
  })

  it('explains suppression and the privacy boundary without viewer fields', () => {
    expect(component).toContain('Suppressed')
    expect(component).toContain('minimum cohort')
    expect(component).toContain('No raw IP')
    expect(component).toContain('country-only')
    for (const forbidden of ['viewer_key', 'session_id', 'user_agent', 'latex_content', 'share_token']) {
      expect(component).not.toContain(forbidden)
    }
  })
})
