import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

describe('original PDF attachment identity before effect cleanup', () => {
  afterEach(() => { vi.resetModules(); vi.doUnmock('react'); vi.doUnmock('@/lib/api-client'); vi.doUnmock('@/components/PDFPreview') })

  async function render(ownerId: string, resumeId: string) {
    // Model an open attachment's state carried into the very first render
    // after navigation/account change, before any effect cleanup can run.
    const states = [
      { identity: 'previous-owner:previous-resume', receipt: { import_id: 'private-original' } },
      true, 'blob:previous-private-original', false, null,
    ]
    vi.doMock('react', async (importOriginal) => ({
      ...await importOriginal<typeof import('react')>(),
      useState: () => [states.shift(), vi.fn()],
    }))
    vi.doMock('@/lib/api-client', () => ({ apiClient: { getAuthToken: () => 'current-account-token' } }))
    vi.doMock('@/components/PDFPreview', () => ({ default: ({ pdfUrl }: { pdfUrl: string }) => createElement('div', {}, pdfUrl) }))
    const { default: ResumeOriginalPdf } = await import('@/components/ResumeOriginalPdf')
    return renderToStaticMarkup(createElement(ResumeOriginalPdf, { ownerId, resumeId }))
  }

  it('hides the old owner attachment and blob immediately after account changes', async () => {
    expect(await render('current-owner', 'previous-resume')).toBe('')
  })
  it('hides the old resume attachment and blob immediately after navigation', async () => {
    expect(await render('previous-owner', 'current-resume')).toBe('')
  })
  it('keeps the current owner attachment available without waiting for an effect', async () => {
    const html = await render('previous-owner', 'previous-resume')
    expect(html).toContain('Original uploaded PDF')
    expect(html).toContain('blob:previous-private-original')
  })
})
