import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'

vi.mock('next/dynamic', () => ({ default: () => () => createElement('div', { 'data-pdf-renderer': true }) }))
import PDFPreview from '../components/PDFPreview'

describe('PDF preview during replacement builds', () => {
  test('keeps a previous artifact visible and disables sharing and downloads', () => {
    const html = renderToStaticMarkup(createElement(PDFPreview, {
      pdfUrl: 'blob:previous', isLoading: true, onShare: () => {}, onDownload: () => {},
    }))
    expect(html).toContain('data-pdf-renderer')
    expect(html).toContain('showing the previous version')
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[^]*?Share/)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[^]*?PDF/)
  })
  test('shows an initial loading state without an artifact', () => {
    const html = renderToStaticMarkup(createElement(PDFPreview, { pdfUrl: null, isLoading: true }))
    expect(html).toContain('Compiling')
    expect(html).not.toContain('data-pdf-renderer')
  })
  test('reenables export after replacement finishes', () => {
    const html = renderToStaticMarkup(createElement(PDFPreview, {
      pdfUrl: 'blob:new', isLoading: false, onShare: () => {}, onDownload: () => {},
    }))
    expect(html).not.toContain('showing the previous version')
    expect(html).toContain('data-pdf-renderer')
  })
})
