'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { diffRenderedPixels, type RenderedDiffResult } from '@/lib/rendered-pdf-diff'

interface PdfPage {
  getViewport(options: { scale: number }): { width: number; height: number }
  render(options: { canvas: HTMLCanvasElement; canvasContext: CanvasRenderingContext2D; viewport: unknown }): { promise: Promise<void> }
}

interface PdfDocument {
  numPages: number
  getPage(pageNumber: number): Promise<PdfPage>
  destroy(): Promise<void>
}

function RenderedDiffPage({ before, after, pageNumber }: {
  before: PdfDocument
  after: PdfDocument
  pageNumber: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [stats, setStats] = useState<Omit<RenderedDiffResult, 'pixels'> | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    const render = async () => {
      setError(false)
      const beforePage = pageNumber <= before.numPages ? await before.getPage(pageNumber) : null
      const afterPage = pageNumber <= after.numPages ? await after.getPage(pageNumber) : null
      const reference = afterPage ?? beforePage
      if (!reference) return

      const referenceViewport = reference.getViewport({ scale: 1.35 })
      const width = Math.ceil(referenceViewport.width)
      const height = Math.ceil(referenceViewport.height)
      const makePageCanvas = () => {
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const context = canvas.getContext('2d', { willReadFrequently: true })
        if (!context) throw new Error('Canvas rendering is unavailable')
        context.fillStyle = '#ffffff'
        context.fillRect(0, 0, width, height)
        return { canvas, context }
      }
      const beforeRaster = makePageCanvas()
      const afterRaster = makePageCanvas()

      const renderPage = async (page: PdfPage | null, target: ReturnType<typeof makePageCanvas>) => {
        if (!page) return
        const natural = page.getViewport({ scale: 1 })
        const scale = Math.min(width / natural.width, height / natural.height)
        const viewport = page.getViewport({ scale })
        await page.render({ canvas: target.canvas, canvasContext: target.context, viewport }).promise
      }
      await Promise.all([
        renderPage(beforePage, beforeRaster),
        renderPage(afterPage, afterRaster),
      ])
      if (cancelled) return

      const beforeData = beforeRaster.context.getImageData(0, 0, width, height)
      const afterData = afterRaster.context.getImageData(0, 0, width, height)
      const result = diffRenderedPixels(beforeData.data, afterData.data)
      const output = canvasRef.current
      const outputContext = output?.getContext('2d')
      if (!output || !outputContext) throw new Error('Canvas rendering is unavailable')
      output.width = width
      output.height = height
      const image = outputContext.createImageData(width, height)
      image.data.set(result.pixels)
      outputContext.putImageData(image, 0, 0)
      setStats({
        changedPixels: result.changedPixels,
        addedPixels: result.addedPixels,
        removedPixels: result.removedPixels,
        modifiedPixels: result.modifiedPixels,
      })
    }

    void render().catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [after, before, pageNumber])

  const totalPixels = (canvasRef.current?.width ?? 0) * (canvasRef.current?.height ?? 0)
  const changedPercent = stats && totalPixels > 0
    ? ((stats.changedPixels / totalPixels) * 100).toFixed(2)
    : null

  return (
    <section className="mx-auto w-full max-w-4xl rounded-[var(--radius-md)] border border-line bg-surface p-3" aria-label={`Rendered diff page ${pageNumber}`}>
      <div className="mb-2 flex items-center justify-between text-[11px] text-fg-3">
        <span>Page {pageNumber}</span>
        {stats && <span>{stats.changedPixels.toLocaleString()} changed pixels{changedPercent ? ` · ${changedPercent}%` : ''}</span>}
      </div>
      {error ? (
        <div className="flex min-h-40 items-center justify-center gap-2 text-xs text-err"><AlertTriangle size={14} /> Could not render this page diff</div>
      ) : (
        <canvas ref={canvasRef} className="h-auto w-full bg-white" aria-label={`Visual pixel differences for page ${pageNumber}`} />
      )}
    </section>
  )
}

export default function RenderedPdfDiff({ beforeUrl, afterUrl }: { beforeUrl: string; afterUrl: string }) {
  const [documents, setDocuments] = useState<{ before: PdfDocument; after: PdfDocument } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let loaded: { before: PdfDocument; after: PdfDocument } | null = null
    const load = async () => {
      setDocuments(null)
      setError(null)
      const { PdfJs } = await import('@/components/ReactPdfClient')
      const [before, after] = await Promise.all([
        PdfJs.getDocument(beforeUrl).promise,
        PdfJs.getDocument(afterUrl).promise,
      ]) as [PdfDocument, PdfDocument]
      loaded = { before, after }
      if (!cancelled) setDocuments(loaded)
    }
    void load().catch(() => { if (!cancelled) setError('Could not load one of the rendered PDFs') })
    return () => {
      cancelled = true
      if (loaded) {
        void loaded.before.destroy()
        void loaded.after.destroy()
      }
    }
  }, [afterUrl, beforeUrl])

  if (error) return <div className="flex h-full items-center justify-center gap-2 text-sm text-err"><AlertTriangle size={16} /> {error}</div>
  if (!documents) return <div className="flex h-full items-center justify-center gap-2 text-sm text-fg-3"><Loader2 size={16} className="animate-spin" /> Rendering PDF differences…</div>

  const pageCount = Math.max(documents.before.numPages, documents.after.numPages)
  return (
    <div className="h-full overflow-auto bg-surface-2 p-4">
      <div className="mx-auto mb-3 flex max-w-4xl flex-wrap items-center gap-4 rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-[11px] text-fg-2">
        <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-ok" />Added ink</span>
        <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-err" />Removed ink</span>
        <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-warn" />Changed color/detail</span>
        {documents.before.numPages !== documents.after.numPages && (
          <span className="ml-auto text-warn">Page count changed: {documents.before.numPages} → {documents.after.numPages}</span>
        )}
      </div>
      <div className="space-y-4">
        {Array.from({ length: pageCount }, (_, index) => (
          <RenderedDiffPage key={index + 1} before={documents.before} after={documents.after} pageNumber={index + 1} />
        ))}
      </div>
    </div>
  )
}
