import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('external navigation isolation', () => {
  it('severs the opener for billing tabs before asynchronous navigation', () => {
    const source = readSource('../app/billing/page.tsx')

    expect(source).toContain("window.open(destination, '_blank', 'noopener,noreferrer')")
    expect(source).toContain('checkoutTab.opener = null')
    expect(source).toContain('previewTab.opener = null')
    expect(source).toContain("destination.protocol === 'http:' || destination.protocol === 'https:'")
  })

  it('opens generated portfolios and slide PDFs without an opener', () => {
    const workspace = readSource('../app/workspace/page.tsx')
    const slides = readSource('../components/SlideViewer.tsx')

    expect(workspace).toContain("window.open(result.portfolio_url, '_blank', 'noopener,noreferrer')")
    expect(slides).toContain("window.open(pdfUrl, '_blank', 'noopener,noreferrer')")
  })
})
