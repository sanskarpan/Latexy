import { afterEach, describe, expect, it, vi } from 'vitest'

describe('PDF renderer preload hook', () => {
  afterEach(() => { vi.resetModules(); vi.doUnmock('react'); vi.doUnmock('@/lib/pdf-renderer-loader') })

  it('starts the browser chunk request from the preview pane mount, before any artifact is supplied', async () => {
    let mountedEffect: (() => void | (() => void)) | undefined
    const loadPdfRenderer = vi.fn(() => Promise.resolve({ PdfDocument: 'Document', PdfPage: 'Page' }))
    vi.doMock('react', () => ({ useEffect: (effect: () => void | (() => void)) => { mountedEffect = effect } }))
    vi.doMock('@/lib/pdf-renderer-loader', () => ({ loadPdfRenderer }))

    const { usePreloadPdfRenderer } = await import('@/hooks/usePreloadPdfRenderer')
    usePreloadPdfRenderer()
    expect(loadPdfRenderer).not.toHaveBeenCalled()

    mountedEffect?.()
    expect(loadPdfRenderer).toHaveBeenCalledOnce()
  })
})
