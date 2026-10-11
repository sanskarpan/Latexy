type PdfRendererModule = typeof import('@/components/ReactPdfClient')

/** Deduplicate speculative and render-triggered loads, but allow failed chunks to retry. */
export function createSharedChunkLoader<T>(load: () => Promise<T>): () => Promise<T> {
  let current: Promise<T> | null = null
  return () => {
    if (current) return current

    const pending = Promise.resolve().then(load)
    current = pending
    void pending.catch(() => {
      if (current === pending) current = null
    })
    return pending
  }
}

/** Share the browser-only PDF renderer chunk between preloading and rendering. */
export const loadPdfRenderer = createSharedChunkLoader<PdfRendererModule>(
  () => import('@/components/ReactPdfClient'),
)
