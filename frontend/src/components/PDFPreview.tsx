'use client'

import { useState, useCallback, useRef, useEffect, useMemo, type MutableRefObject } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { AlertTriangle, FileText, Download, ZoomIn, ZoomOut, MousePointer, Moon, Printer, Sun } from 'lucide-react'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import { parseSynctex, synctexReverse, synctexForward, type SynctexData } from '@/lib/synctex-parser'
import { computePageHeatmap, heatmapColor } from '@/lib/heatmap-generator'

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`

// ── Color usage analysis (Feature 89B) ───────────────────────────────────────
import { analyzeColorUsage, type ColorWarning } from '@/lib/print-preview'
// ─────────────────────────────────────────────────────────────────────────────

interface PDFPreviewProps {
  pdfUrl: string | null
  isLoading: boolean
  onDownload?: () => void
  /** Job ID used to fetch synctex data for bidirectional sync */
  jobId?: string | null
  /** Called when user Ctrl+clicks a position in the PDF → give back source line */
  onSyncToSource?: (line: number) => void
  /** When set, scroll PDF to show this source line */
  syncFromLine?: number | null
  /** LaTeX source for color-dependency analysis in print preview mode (Feature 89B) */
  latexContent?: string
  /** Called when user clicks a warning line number to jump to editor line (Feature 89B) */
  onJumpToLine?: (line: number) => void
}

interface PageDimensions {
  naturalWidth: number
  naturalHeight: number
}

// ── Heatmap canvas overlay ────────────────────────────────────────────────────

function HeatmapCanvas({
  pageIndex,
  pageWidth,
  pageDimsRef,
}: {
  pageIndex: number
  pageWidth: number
  pageDimsRef: MutableRefObject<Record<number, PageDimensions>>
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const pageNum = pageIndex + 1
    const dims = pageDimsRef.current[pageNum]
    const aspectRatio = dims ? dims.naturalHeight / dims.naturalWidth : 11 / 8.5
    const height = Math.floor(pageWidth * aspectRatio)

    canvas.width = pageWidth
    canvas.height = height
    ctx.clearRect(0, 0, pageWidth, height)

    const regions = computePageHeatmap(pageIndex)
    for (const region of regions) {
      const y = (region.yPercent / 100) * height
      const h = (region.heightPercent / 100) * height
      ctx.fillStyle = heatmapColor(region.intensity)
      ctx.fillRect(0, y, pageWidth, h)
      // Region label
      const fontSize = Math.max(9, Math.floor(pageWidth * 0.022))
      ctx.font = `${fontSize}px system-ui, sans-serif`
      ctx.fillStyle = 'rgba(255,255,255,0.5)'
      ctx.fillText(region.label, 8, y + h / 2 + fontSize * 0.35)
    }
  }, [pageIndex, pageWidth, pageDimsRef])

  return (
    <canvas
      ref={canvasRef}
      style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', zIndex: 5 }}
    />
  )
}

export default function PDFPreview({
  pdfUrl,
  isLoading,
  onDownload,
  jobId,
  onSyncToSource,
  syncFromLine,
  latexContent,
  onJumpToLine,
}: PDFPreviewProps) {
  const [numPages, setNumPages] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [renderError, setRenderError] = useState(false)
  const [synctexReady, setSynctexReady] = useState(false)
  const [syncHint, setSyncHint] = useState(false)
  const [containerWidth, setContainerWidth] = useState(0)
  const [darkPdf, setDarkPdf] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_pdf_dark') === '1'
  })
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [printPreview, setPrintPreview] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_print_preview') === '1'
  })

  const togglePrintPreview = () => {
    setPrintPreview((prev) => {
      const next = !prev
      localStorage.setItem('latexy_print_preview', next ? '1' : '0')
      return next
    })
  }

  // Color warnings — only computed when print preview is active
  const colorWarnings = useMemo<ColorWarning[]>(() => {
    if (!printPreview || !latexContent) return []
    return analyzeColorUsage(latexContent)
  }, [printPreview, latexContent])

  const toggleDarkPdf = () => {
    setDarkPdf((prev) => {
      const next = !prev
      localStorage.setItem('latexy_pdf_dark', next ? '1' : '0')
      return next
    })
  }

  const synctexDataRef = useRef<SynctexData | null>(null)
  const pageDimsRef = useRef<Record<number, PageDimensions>>({})
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const containerRef = useRef<HTMLDivElement>(null)
  const prevJobIdRef = useRef<string | null>(null)

  const handleZoomIn = () => setZoom((p) => Math.min(+(p + 0.15).toFixed(2), 3))
  const handleZoomOut = () => setZoom((p) => Math.max(+(p - 0.15).toFixed(2), 0.4))

  // Measure container width so pages never overflow the panel
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      if (w > 0) setContainerWidth(w)
    })
    ro.observe(el)
    // Initial measurement
    setContainerWidth(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [])

  // Base width = container minus horizontal padding (24px each side)
  const baseWidth = containerWidth > 0 ? Math.max(200, containerWidth - 48) : 520
  const pageWidth = Math.floor(baseWidth * zoom)

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setRenderError(false)
  }, [])

  // Fetch and parse synctex when jobId changes.
  // prevJobIdRef is component-instance-scoped (via useRef), so it resets to null on
  // every fresh mount — meaning a remounted component with the same jobId will still
  // trigger a fresh fetch. This is intentional: stale synctex data is cleared on unmount.
  useEffect(() => {
    if (!jobId || jobId === prevJobIdRef.current) return
    prevJobIdRef.current = jobId
    setSynctexReady(false)
    synctexDataRef.current = null

    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030'
    fetch(`${apiBase}/download/${encodeURIComponent(jobId)}/synctex`)
      .then((r) => {
        if (!r.ok) return null
        return r.text()
      })
      .then((text) => {
        if (!text) return
        synctexDataRef.current = parseSynctex(text)
        setSynctexReady(true)
      })
      .catch(() => {
        // SyncTeX not available — silent failure
      })
  }, [jobId])

  // Forward sync: source line → scroll PDF to the matching page
  useEffect(() => {
    if (!syncFromLine || !synctexDataRef.current) return
    const block = synctexForward(synctexDataRef.current, syncFromLine)
    if (!block) return

    const pageEl = pageRefs.current[block.page]
    if (!pageEl) return

    pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' })

    // Flash overlay on the block
    const dims = pageDimsRef.current[block.page]
    if (!dims) return
    const scale = pageWidth / dims.naturalWidth
    flashOverlay(pageEl, {
      left: block.x * scale,
      top: (dims.naturalHeight - block.y - block.height) * scale,
      width: Math.max(block.width * scale, 40),
      height: Math.max(block.height * scale, 8),
    })
  }, [syncFromLine, pageWidth])

  function flashOverlay(
    pageEl: HTMLElement,
    rect: { left: number; top: number; width: number; height: number }
  ) {
    const div = document.createElement('div')
    div.style.cssText = `
      position:absolute;
      left:${rect.left}px;
      top:${rect.top}px;
      width:${rect.width}px;
      height:${rect.height}px;
      background:rgba(245,158,11,0.35);
      border:1px solid rgba(245,158,11,0.7);
      border-radius:2px;
      pointer-events:none;
      z-index:10;
      transition:opacity 1.5s ease;
    `
    pageEl.style.position = 'relative'
    pageEl.appendChild(div)
    requestAnimationFrame(() => {
      setTimeout(() => { div.style.opacity = '0' }, 400)
      setTimeout(() => { pageEl.removeChild(div) }, 2000)
    })
  }

  // Handle PDF click for reverse sync (Ctrl+click → find source line)
  const handlePageClick = useCallback(
    (
      e: React.MouseEvent<HTMLDivElement>,
      pageNumber: number
    ) => {
      if (!synctexDataRef.current || !onSyncToSource) return
      if (!e.ctrlKey && !e.metaKey) return

      const dims = pageDimsRef.current[pageNumber]
      if (!dims) return

      const rect = e.currentTarget.getBoundingClientRect()
      const canvasX = e.clientX - rect.left
      const canvasY = e.clientY - rect.top

      const scale = pageWidth / dims.naturalWidth
      // Convert canvas coords → PDF coords (origin: bottom-left)
      const pdfX = canvasX / scale
      const pdfY = dims.naturalHeight - canvasY / scale

      const result = synctexReverse(synctexDataRef.current, pageNumber, pdfX, pdfY)
      if (result) {
        onSyncToSource(result.line)
        setSyncHint(true)
        setTimeout(() => setSyncHint(false), 2000)
      }
    },
    [onSyncToSource, pageWidth]
  )

  const storePagDims = useCallback((pageNumber: number, page: any) => {
    if (!page) return
    const vp = page.getViewport({ scale: 1 })
    pageDimsRef.current[pageNumber] = {
      naturalWidth: vp.width,
      naturalHeight: vp.height,
    }
  }, [])

  if (isLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-[#1a1a1a]">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-white/10 border-t-orange-400" />
        <p className="text-xs text-zinc-600">Compiling…</p>
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-[#1a1a1a]">
        <FileText className="h-9 w-9 text-zinc-800" />
        <p className="text-xs text-zinc-700">No preview yet</p>
        <p className="text-[10px] text-zinc-800">Compile your LaTeX to see the PDF</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-[#1a1a1a]">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] bg-[#111] px-2 py-1">
        {/* Zoom */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleZoomOut}
            disabled={zoom <= 0.4}
            aria-label="Zoom out"
            title="Zoom out"
            className="rounded p-1 text-zinc-500 transition hover:bg-white/10 hover:text-zinc-200 disabled:opacity-30"
          >
            <ZoomOut size={13} />
          </button>
          <span className="min-w-[3rem] text-center text-[11px] tabular-nums text-zinc-500">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={handleZoomIn}
            disabled={zoom >= 3}
            aria-label="Zoom in"
            title="Zoom in"
            className="rounded p-1 text-zinc-500 transition hover:bg-white/10 hover:text-zinc-200 disabled:opacity-30"
          >
            <ZoomIn size={13} />
          </button>
        </div>

        {/* SyncTeX indicator */}
        {synctexReady && (
          <div
            className={`flex items-center gap-1 text-[10px] transition ${
              syncHint ? 'text-amber-400' : 'text-zinc-700'
            }`}
            title="SyncTeX enabled — Ctrl+click PDF to jump to source"
          >
            <MousePointer size={11} />
            {syncHint ? 'Jumping to source…' : 'Ctrl+click to sync'}
          </div>
        )}

        {/* Heatmap + Dark preview + Download */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setShowHeatmap((p) => !p)}
            title="Shows predicted areas recruiters focus on (based on eye-tracking research)"
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-white/10 ${
              showHeatmap ? 'text-orange-300' : 'text-zinc-600 hover:text-zinc-200'
            }`}
          >
            🔥 Heatmap
          </button>
          <button
            onClick={toggleDarkPdf}
            aria-label={darkPdf ? 'Light PDF preview' : 'Dark PDF preview'}
            title={darkPdf ? 'Switch to light preview' : 'Switch to dark preview'}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-white/10 ${
              darkPdf ? 'text-orange-300' : 'text-zinc-600 hover:text-zinc-200'
            }`}
          >
            {darkPdf ? <Sun size={12} /> : <Moon size={12} />}
          </button>
          <button
            onClick={togglePrintPreview}
            aria-label={printPreview ? 'Exit print preview' : 'B&W print preview'}
            title={printPreview ? 'Exit B&W print preview' : 'Preview as B&W printed page'}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-white/10 ${
              printPreview ? 'text-amber-300' : 'text-zinc-600 hover:text-zinc-200'
            }`}
          >
            <Printer size={12} />
            {printPreview ? 'B&W' : 'Print'}
          </button>
          {onDownload && (
            <button
              onClick={onDownload}
              className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-zinc-600 transition hover:bg-white/10 hover:text-zinc-200"
            >
              <Download size={12} />
              PDF
            </button>
          )}
        </div>
      </div>

      {/* Print preview banner */}
      {printPreview && (
        <div className="flex shrink-0 items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-1.5">
          <Printer size={12} className="shrink-0 text-amber-400" />
          <span className="text-[11px] text-amber-300">
            Print Preview — showing how this looks on a B&W printer
          </span>
        </div>
      )}

      {/* Pages */}
      <div
        ref={containerRef}
        className="flex-1 overflow-auto"
        style={{
          background: darkPdf ? '#1e1e1e' : '#2a2a2a',
        }}
      >
        {renderError ? (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <FileText className="h-9 w-9 text-zinc-700" />
            <p className="text-xs text-zinc-600">Failed to render PDF</p>
            {onDownload && (
              <button onClick={onDownload} className="text-[11px] text-orange-400 hover:underline">
                Download to view
              </button>
            )}
          </div>
        ) : (
          <Document
            file={pdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={() => setRenderError(true)}
            loading={
              <div className="flex h-32 items-center justify-center">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/10 border-t-orange-400" />
              </div>
            }
            className="flex flex-col items-center gap-5 py-6"
          >
            {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
              <div
                key={pageNum}
                ref={(el) => { pageRefs.current[pageNum] = el }}
                className="shadow-[0_4px_24px_rgba(0,0,0,0.5)] select-text"
                style={{ lineHeight: 0, position: 'relative' }}
                onClick={(e) => handlePageClick(e, pageNum)}
              >
                {/* Dark + print preview filters wrap Page only so HeatmapCanvas colours are unaffected */}
                <div style={{
                  ...(darkPdf ? { filter: 'invert(1) hue-rotate(180deg)', background: '#fff' } : undefined),
                  ...(printPreview ? { filter: (darkPdf ? 'invert(1) hue-rotate(180deg) ' : '') + 'grayscale(1) contrast(1.05)' } : undefined),
                }}>
                  <Page
                    pageNumber={pageNum}
                    width={pageWidth}
                    renderTextLayer
                    renderAnnotationLayer
                    onRenderSuccess={(page) => storePagDims(pageNum, page)}
                  />
                </div>
                {showHeatmap && (
                  <HeatmapCanvas
                    pageIndex={pageNum - 1}
                    pageWidth={pageWidth}
                    pageDimsRef={pageDimsRef}
                  />
                )}
              </div>
            ))}
          </Document>
        )}

        {/* Color-dependency warnings (Feature 89B) */}
        {printPreview && colorWarnings.length > 0 && (
          <div className="shrink-0 border-t border-amber-500/20 bg-[#111] px-4 py-3">
            <div className="mb-2 flex items-center gap-2">
              <AlertTriangle size={13} className="text-amber-400" />
              <span className="text-[11px] font-semibold text-amber-300">
                Color-dependent elements detected — these may become invisible or lose meaning in grayscale print:
              </span>
            </div>
            <ul className="space-y-1">
              {colorWarnings.map((w, i) => (
                <li key={i} className="flex items-baseline gap-2 text-[11px]">
                  <button
                    onClick={() => onJumpToLine?.(w.line)}
                    className="shrink-0 rounded bg-amber-500/20 px-1.5 py-0.5 font-mono text-[10px] text-amber-400 hover:bg-amber-500/30 transition"
                    title={`Jump to line ${w.line} in editor`}
                  >
                    L{w.line}
                  </button>
                  <code className="font-mono text-amber-200">{w.command}</code>
                  <span className="truncate text-zinc-500" title={w.context}>{w.context}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
