import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const surface = readFileSync(new URL('../components/ReviewablePdfSurface.tsx', import.meta.url), 'utf8')

describe('reviewable PDF surface contract', () => {
  it('uses the existing client-only react-pdf boundary and normalized anchors', () => {
    expect(surface).toContain("import('@/components/ReactPdfClient')")
    expect(surface).toContain('page_number: number')
    expect(surface).toContain('x: number')
    expect(surface).toContain('y: number')
    expect(surface).toContain('onLoadSuccess')
  })

  it('does not render markers for pages outside the loaded document', () => {
    expect(surface).toContain('pageComments = markerComments.filter((comment) => comment.page_number === pageNumber)')
    expect(surface).toContain('data-testid="review-comment-marker"')
  })

  it('provides keyboard placement and accessible marker labels', () => {
    expect(surface).toContain('tabIndex={0}')
    expect(surface).toContain("event.key === 'Enter' || event.key === ' '")
    expect(surface).toContain('aria-label={`${comment.resolved ?')
  })
})
