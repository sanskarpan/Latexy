import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import SourcePdfDivider from '@/components/SourcePdfDivider'

describe('SourcePdfDivider', () => {
  it('exposes disabled actions until both sync locations are ready', () => {
    const markup = renderToStaticMarkup(
      React.createElement(SourcePdfDivider, {
        sourceLine: 12,
        pdfSelection: null,
        pdfReady: false,
        onSourceToPdf: vi.fn(),
        onPdfToSource: vi.fn(),
      }),
    )

    expect(markup).toContain('aria-label="Show the selected source line in PDF"')
    expect(markup).toContain('aria-label="Select a PDF location mapped to source"')
    expect((markup.match(/disabled=""/g) ?? []).length).toBe(2)
  })

  it('renders actionable labels once both locations are available', () => {
    const markup = renderToStaticMarkup(
      React.createElement(SourcePdfDivider, {
        sourceLine: 12,
        pdfSelection: { page: 2, x: 30, y: 40, line: 27 },
        pdfReady: true,
        onSourceToPdf: vi.fn(),
        onPdfToSource: vi.fn(),
      }),
    )

    expect(markup).toContain('aria-label="Show source line 12 in PDF"')
    expect(markup).toContain('aria-label="Show source line 27"')
    expect(markup).not.toContain('disabled=""')
  })

  it('does not enable a remembered PDF selection after mapping becomes unavailable', () => {
    const markup = renderToStaticMarkup(React.createElement(SourcePdfDivider, {
      sourceLine: 12,
      pdfSelection: { page: 1, x: 170, y: 650, line: 3 },
      pdfReady: false,
      onSourceToPdf: vi.fn(),
      onPdfToSource: vi.fn(),
    }))
    expect((markup.match(/disabled=""/g) ?? []).length).toBe(2)
  })
})
