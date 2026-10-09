'use client'

import { useEntitlements } from '@/contexts/EntitlementsContext'
import CapabilityGate from '@/components/CapabilityGate'

import { useState, useCallback, useRef, useEffect, useMemo, type MutableRefObject } from 'react'
import dynamic from 'next/dynamic'
import { AlertTriangle, FileText, Download, Share2, ZoomIn, ZoomOut, MousePointer, Moon, Printer, Sun, Flame } from 'lucide-react'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import { createSynctexRequestGuard, parseSynctex, synctexHasMappableSource, synctexReverse, synctexForward, type SynctexData } from '@/lib/synctex-parser'
import { computePageHeatmap, heatmapColor } from '@/lib/heatmap-generator'
import { apiClient } from '@/lib/api-client'

// PDF.js 5 requires browser DOMMatrix at module evaluation time. Keep the
// renderer behind a client-only boundary so Next can still prerender every page
// that includes the preview.
const Document = dynamic(
  () => import('@/components/ReactPdfClient').then((module) => module.PdfDocument),
  { ssr: false },
)
const Page = dynamic(
  () => import('@/components/ReactPdfClient').then((module) => module.PdfPage),
  { ssr: false },
)

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
  /** Optional selected PDF coordinate for a divider/side-panel action. */
  onPdfSelectionChange?: (selection: PdfSyncSelection | null) => void
  /** Reports whether a nonempty, current-job SyncTeX map is usable. */
  onSyncReadyChange?: (ready: boolean) => void
  /** When set, scroll PDF to show this source line */
  syncFromLine?: number | null
  /** Changes when the same source line should be requested again. */
  syncFromRequestId?: string | number | null
  /** Main source filename from the compile settings, when known. */
  sourceFileName?: string
  /** LaTeX source for color-dependency analysis in print preview mode (Feature 89B) */
  latexContent?: string
  /** Called when user clicks a warning line number to jump to editor line (Feature 89B) */
  onJumpToLine?: (line: number) => void
  /** Share the current PDF, with the caller responsible for a download fallback. */
  onShare?: () => void | Promise<void>
  /** Marks a preview loaded from the owner-scoped offline PDF cache. */
  isOfflinePreview?: boolean
  /** Persistent cache/recovery error (toasts are intentionally insufficient). */
  offlineError?: string | null
  onRetryOffline?: () => void
}

interface PageDimensions {
  naturalWidth: number
  naturalHeight: number
}

export interface PdfSyncSelection {
  page: number
  x: number
  y: number
  line: number
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
  onPdfSelectionChange,
  onSyncReadyChange,
  syncFromLine,
  syncFromRequestId,
  sourceFileName,
  latexContent,
  onJumpToLine,
  onShare,
  isOfflinePreview = false,
  offlineError,
  onRetryOffline,
}: PDFPreviewProps) {
  const { can } = useEntitlements()
  const syncAllowed = can('c10')
  const inspectionAllowed = can('c11')
  const [numPages, setNumPages] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [currentPage, setCurrentPage] = useState(1)
  const [renderError, setRenderError] = useState(false)
  const [synctexReady, setSynctexReady] = useState(false)
  const [syncHint, setSyncHint] = useState(false)
  const [containerWidth, setContainerWidth] = useState(0)
  const [darkPdfPreference, setDarkPdf] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_pdf_dark') === '1'
  })
  const [showHeatmapPreference, setShowHeatmap] = useState(false)
  const [printPreviewPreference, setPrintPreview] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_print_preview') === '1'
  })

  const darkPdf = inspectionAllowed && darkPdfPreference
  const showHeatmap = inspectionAllowed && showHeatmapPreference
  const printPreview = inspectionAllowed && printPreviewPreference

  const togglePrintPreview = () => {
    if (!inspectionAllowed) return
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
    if (!inspectionAllowed) return
    setDarkPdf((prev) => {
      const next = !prev
      localStorage.setItem('latexy_pdf_dark', next ? '1' : '0')
      return next
    })
  }

  const synctexDataRef = useRef<SynctexData | null>(null)
  const synctexTextRef = useRef<string | null>(null)
  const synctexRequestGuardRef = useRef(createSynctexRequestGuard())
  const pageDimsRef = useRef<Record<number, PageDimensions>>({})
  const [pageDimsVersion, setPageDimsVersion] = useState(0)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [containerNode, setContainerNode] = useState<HTMLDivElement | null>(null)
  const setContainerElement = useCallback((node: HTMLDivElement | null) => {
    if (containerRef.current === node) return
    containerRef.current = node
    setContainerNode(node)
  }, [])
  const syncHintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const flashTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())
  const flashAnimationFramesRef = useRef<Set<number>>(new Set())
  const flashOverlaysRef = useRef<Set<HTMLDivElement>>(new Set())
  const selectionCallbackRef = useRef(onPdfSelectionChange)
  selectionCallbackRef.current = onPdfSelectionChange

  // react-pdf may finish loading a previous PDF after the props have already
  // advanced to a new compile.  Keep a render-time identity so those callbacks
  // cannot republish dimensions, errors, or overlays into the new document.
  const pdfIdentityKey = `${jobId ?? ''}\u0000${pdfUrl ?? ''}\u0000${sourceFileName ?? ''}`
  const pdfIdentityRef = useRef<{ key: string; generation: number; jobId: string | null; pdfUrl: string | null; sourceFileName?: string } | null>(null)
  if (pdfIdentityRef.current?.key !== pdfIdentityKey) {
    pdfIdentityRef.current = {
      key: pdfIdentityKey,
      generation: (pdfIdentityRef.current?.generation ?? 0) + 1,
      jobId: jobId ?? null,
      pdfUrl: pdfUrl ?? null,
      sourceFileName,
    }
    pageDimsRef.current = {}
    pageRefs.current = {}
    synctexDataRef.current = null
    synctexTextRef.current = null
  }
  const renderGeneration = pdfIdentityRef.current!.generation

  const isCurrentPdfIdentity = useCallback((generation: number) => {
    const identity = pdfIdentityRef.current
    return identity?.generation === generation &&
      identity.jobId === (jobId ?? null) &&
      identity.pdfUrl === (pdfUrl ?? null) &&
      identity.sourceFileName === sourceFileName
  }, [jobId, pdfUrl, sourceFileName])

  const clearFlashOverlays = useCallback(() => {
    flashAnimationFramesRef.current.forEach((frame) => cancelAnimationFrame(frame))
    flashAnimationFramesRef.current.clear()
    flashTimersRef.current.forEach((timer) => clearTimeout(timer))
    flashTimersRef.current.clear()
    flashOverlaysRef.current.forEach((overlay) => overlay.remove())
    flashOverlaysRef.current.clear()
  }, [])

  const handleZoomIn = () => setZoom((p) => Math.min(+(p + 0.15).toFixed(2), 3))
  const handleZoomOut = () => setZoom((p) => Math.max(+(p - 0.15).toFixed(2), 0.4))
  // Container width already tracks the panel's available width, so 100% zoom
  // is "fit to width" — reset and fit-width are the same target state.
  const handleResetZoom = () => setZoom(1)

  // Measure container width so pages never overflow the panel
  useEffect(() => {
    const el = containerNode
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      if (w > 0) setContainerWidth(w)
    })
    ro.observe(el)
    // Initial measurement
    setContainerWidth(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [containerNode])

  // Ctrl/Cmd + scroll (or trackpad pinch, which browsers report as a ctrl-flagged
  // wheel event) zooms the preview instead of scrolling the page.
  useEffect(() => {
    const el = containerNode
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      setZoom((p) => {
        const next = e.deltaY < 0 ? p + 0.08 : p - 0.08
        return Math.min(3, Math.max(0.4, +next.toFixed(2)))
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [containerNode])

  // Keyboard zoom shortcuts: Cmd/Ctrl +/- to step, Cmd/Ctrl+0 to reset to 100%/fit.
  // Skipped while typing in an input/textarea/contenteditable (e.g. the LaTeX editor).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      if (e.key === '+' || e.key === '=') {
        e.preventDefault()
        setZoom((p) => Math.min(+(p + 0.15).toFixed(2), 3))
      } else if (e.key === '-') {
        e.preventDefault()
        setZoom((p) => Math.max(+(p - 0.15).toFixed(2), 0.4))
      } else if (e.key === '0') {
        e.preventDefault()
        setZoom(1)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Track which page is most in view while scrolling, for the "Page X of N" indicator.
  useEffect(() => {
    if (numPages <= 1) {
      setCurrentPage(1)
      return
    }
    const root = containerRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        let best: { page: number; ratio: number } | null = null
        for (const entry of entries) {
          const pageAttr = (entry.target as HTMLElement).dataset.pageNumber
          if (!pageAttr) continue
          if (!best || entry.intersectionRatio > best.ratio) {
            best = { page: Number(pageAttr), ratio: entry.intersectionRatio }
          }
        }
        if (best && best.ratio > 0) setCurrentPage(best.page)
      },
      { root, threshold: [0.25, 0.5, 0.75, 1] }
    )
    Object.values(pageRefs.current).forEach((el) => { if (el) observer.observe(el) })
    return () => observer.disconnect()
  }, [containerNode, numPages])

  // Base width = container minus horizontal padding (24px each side)
  const baseWidth = containerWidth > 0 ? Math.max(200, containerWidth - 48) : 520
  const pageWidth = Math.floor(baseWidth * zoom)

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }, expectedGeneration: number) => {
    if (!isCurrentPdfIdentity(expectedGeneration)) return
    setNumPages(numPages)
    setRenderError(false)
  }, [isCurrentPdfIdentity])

  const parseCurrentSynctex = useCallback((text: string, expectedGeneration = renderGeneration) => {
    if (!isCurrentPdfIdentity(expectedGeneration)) return
    const pageHeights = Object.fromEntries(
      Object.entries(pageDimsRef.current).map(([page, dimensions]) => [Number(page), dimensions.naturalHeight]),
    )
    const parsed = parseSynctex(text, pageHeights)
    synctexTextRef.current = text
    synctexDataRef.current = parsed
    const hasMeasuredPages = Object.keys(parsed.pageBlocks).length > 0 &&
      Object.keys(parsed.pageBlocks).every((page) => Boolean(pageDimsRef.current[Number(page)]))
    setSynctexReady(synctexHasMappableSource(parsed, sourceFileName) && hasMeasuredPages)
  }, [isCurrentPdfIdentity, renderGeneration, sourceFileName])

  useEffect(() => {
    onSyncReadyChange?.(synctexReady)
  }, [onSyncReadyChange, synctexReady])

  // A new compile or source selection invalidates the parent's remembered PDF
  // selection immediately, including before a replacement PDF has measured.
  useEffect(() => {
    selectionCallbackRef.current?.(null)
    if (syncHintTimerRef.current !== null) {
      clearTimeout(syncHintTimerRef.current)
      syncHintTimerRef.current = null
    }
    setSyncHint(false)
    clearFlashOverlays()
  }, [clearFlashOverlays, jobId, pdfUrl, sourceFileName])

  // Fetch and parse synctex when jobId changes.
  useEffect(() => {
    const guard = synctexRequestGuardRef.current
    pageDimsRef.current = {}
    pageRefs.current = {}
    setPageDimsVersion(0)
    setSynctexReady(false)
    setRenderError(false)
    synctexDataRef.current = null
    synctexTextRef.current = null
    if (!syncAllowed || !jobId) {
      guard.reset()
      return
    }

    const token = guard.begin(jobId)
    const controller = new AbortController()
    apiClient.downloadSynctex(jobId, controller.signal)
      .then((text) => {
        if (!guard.isCurrent(token) || !text) return
        parseCurrentSynctex(text)
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        // SyncTeX not available — silent failure
      })
    return () => {
      controller.abort()
      guard.invalidate(token)
    }
  }, [syncAllowed, jobId, pdfUrl, sourceFileName, parseCurrentSynctex])

  // Forward sync: source line → scroll PDF to the matching page
  useEffect(() => {
    if (!syncAllowed || !syncFromLine || !synctexReady || !synctexDataRef.current) return
    const block = synctexForward(synctexDataRef.current, syncFromLine, sourceFileName)
    if (!block) return

    const pageEl = pageRefs.current[block.page]
    if (!pageEl) return

    pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' })

    // Flash overlay on the block
    const dims = pageDimsRef.current[block.page]
    if (!dims) return
    const pageRect = pageEl.getBoundingClientRect()
    const scaleX = pageRect.width / dims.naturalWidth
    const scaleY = pageRect.height / dims.naturalHeight
    if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY) || scaleX <= 0 || scaleY <= 0) return
    flashOverlay(pageEl, {
      left: block.x * scaleX,
      top: (dims.naturalHeight - block.y - block.height) * scaleY,
      width: Math.max(block.width * scaleX, 40),
      height: Math.max(block.height * scaleY, 8),
    })
  }, [syncAllowed, pageDimsVersion, sourceFileName, syncFromLine, syncFromRequestId, synctexReady])

  function flashOverlay(
    pageEl: HTMLElement,
    rect: { left: number; top: number; width: number; height: number }
  ) {
    const div = document.createElement('div')
    div.dataset.synctexHighlight = 'true'
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
    flashOverlaysRef.current.add(div)
    const frame = requestAnimationFrame(() => {
      flashAnimationFramesRef.current.delete(frame)
      if (!pageEl.contains(div)) return
      const t1 = setTimeout(() => { div.style.opacity = '0' }, 400)
      const t2 = setTimeout(() => {
        if (pageEl.contains(div)) pageEl.removeChild(div)
        flashOverlaysRef.current.delete(div)
        flashTimersRef.current.delete(t1)
        flashTimersRef.current.delete(t2)
      }, 2000)
      flashTimersRef.current.add(t1)
      flashTimersRef.current.add(t2)
    })
    flashAnimationFramesRef.current.add(frame)
  }

  const resolvePdfLocation = useCallback((e: React.MouseEvent<HTMLDivElement>, pageNumber: number) => {
    if (!syncAllowed) return null
    const dims = pageDimsRef.current[pageNumber]
    if (!dims || !synctexDataRef.current) return null
    const rect = e.currentTarget.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0 || e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) return null
    const scaleX = rect.width / dims.naturalWidth
    const scaleY = rect.height / dims.naturalHeight
    if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY) || scaleX <= 0 || scaleY <= 0) return null
    const pdfX = (e.clientX - rect.left) / scaleX
    const pdfY = dims.naturalHeight - (e.clientY - rect.top) / scaleY
    const result = synctexReverse(synctexDataRef.current, pageNumber, pdfX, pdfY, sourceFileName)
    return { pdfX, pdfY, result }
  }, [syncAllowed, sourceFileName])

  // A regular click only records the selected PDF location. It never scrolls
  // or navigates; Ctrl/Cmd-click retains the explicit source-jump action.
  const handlePageClick = useCallback((e: React.MouseEvent<HTMLDivElement>, pageNumber: number) => {
    const location = resolvePdfLocation(e, pageNumber)
    if (!location || !location.result) {
      onPdfSelectionChange?.(null)
      return
    }
    onPdfSelectionChange?.({ page: pageNumber, x: location.pdfX, y: location.pdfY, line: location.result.line })
    if ((!e.ctrlKey && !e.metaKey) || !location.result || !onSyncToSource) return
    onSyncToSource(location.result.line)
    setSyncHint(true)
    if (syncHintTimerRef.current !== null) clearTimeout(syncHintTimerRef.current)
    syncHintTimerRef.current = setTimeout(() => setSyncHint(false), 2000)
  }, [onPdfSelectionChange, onSyncToSource, resolvePdfLocation])

  // Double-click mirrors the conventional PDF viewer source-jump action even
  // without a modifier; it still requires a real parsed mapping.
  const handlePageDoubleClick = useCallback((e: React.MouseEvent<HTMLDivElement>, pageNumber: number) => {
    const location = resolvePdfLocation(e, pageNumber)
    if (!location?.result || !onSyncToSource) return
    onSyncToSource(location.result.line)
    setSyncHint(true)
    if (syncHintTimerRef.current !== null) clearTimeout(syncHintTimerRef.current)
    syncHintTimerRef.current = setTimeout(() => setSyncHint(false), 2000)
  }, [onSyncToSource, resolvePdfLocation])

  // Clear all pending timers on unmount
  useEffect(() => () => {
    if (syncHintTimerRef.current !== null) clearTimeout(syncHintTimerRef.current)
    clearFlashOverlays()
  }, [clearFlashOverlays])

  const storePagDims = useCallback((pageNumber: number, page: any, expectedGeneration: number) => {
    if (!isCurrentPdfIdentity(expectedGeneration)) return
    if (!page) return
    const vp = page.getViewport({ scale: 1 })
    pageDimsRef.current[pageNumber] = {
      naturalWidth: vp.width,
      naturalHeight: vp.height,
    }
    setPageDimsVersion((version) => version + 1)
    if (synctexTextRef.current) parseCurrentSynctex(synctexTextRef.current, expectedGeneration)
  }, [isCurrentPdfIdentity, parseCurrentSynctex])

  if (isLoading && !pdfUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 bg-surface-2 px-6">
        {/* a page materializing */}
        <div className="h-44 w-[8.5rem] animate-pulse rounded-[3px] border border-line bg-surface shadow-sm" />
        <p className="flex items-center gap-2 font-ui text-xs text-fg-3">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" />
          Compiling…
        </p>
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-5 bg-surface-2 px-6">
        {offlineError && (
          <div role="alert" className="flex max-w-sm items-center gap-2 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            <AlertTriangle size={14} className="shrink-0" />
            <span className="flex-1">{offlineError}</span>
            {onRetryOffline && <button type="button" onClick={onRetryOffline} className="shrink-0 font-semibold underline">Retry</button>}
          </div>
        )}
        {/* faux page silhouette so the empty pane reads as "a page goes here" */}
        <div className="relative">
          <div className="h-44 w-[8.5rem] rounded-[3px] border border-line bg-surface shadow-sm">
            <div className="space-y-1.5 p-3.5">
              <div className="h-1.5 w-2/3 rounded-full bg-fg/15" />
              <div className="h-1 w-full rounded-full bg-fg/[0.07]" />
              <div className="h-1 w-4/5 rounded-full bg-fg/[0.07]" />
              <div className="mt-3 h-1.5 w-1/2 rounded-full bg-accent/25" />
              <div className="h-1 w-full rounded-full bg-fg/[0.07]" />
              <div className="h-1 w-11/12 rounded-full bg-fg/[0.07]" />
              <div className="h-1 w-3/4 rounded-full bg-fg/[0.07]" />
            </div>
          </div>
          <span className="absolute -bottom-2 -right-2 grid h-7 w-7 place-items-center rounded-full border border-line bg-surface text-fg-3 shadow-sm">
            <FileText size={13} />
          </span>
        </div>
        <div className="text-center">
          <p className="font-ui text-sm font-medium text-fg-2">Your PDF will appear here</p>
          <p className="mt-1 font-ui text-xs text-fg-3">Compile to render a live preview</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between border-b border-line bg-surface px-2 py-1">
        {/* Zoom */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleZoomOut}
            disabled={zoom <= 0.4}
            aria-label="Zoom out"
            title="Zoom out (Ctrl/Cmd -)"
            className="rounded p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-30"
          >
            <ZoomOut size={13} />
          </button>
          <button
            onClick={handleResetZoom}
            disabled={zoom === 1}
            aria-label="Reset zoom to 100%"
            title="Reset to 100% (Ctrl/Cmd 0)"
            className="min-w-[3rem] rounded px-1 py-1 text-center text-[12px] tabular-nums text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:cursor-default disabled:hover:bg-transparent disabled:hover:text-fg-3"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            onClick={handleZoomIn}
            disabled={zoom >= 3}
            aria-label="Zoom in"
            title="Zoom in (Ctrl/Cmd +)"
            className="rounded p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-30"
          >
            <ZoomIn size={13} />
          </button>
          <button
            onClick={handleResetZoom}
            disabled={zoom === 1}
            aria-label="Fit to width"
            title="Fit to width (Ctrl/Cmd 0)"
            className="ml-0.5 rounded px-1.5 py-1 font-ui text-[11px] text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-30"
          >
            Fit
          </button>
          {numPages > 1 && (
            <span className="ml-1.5 whitespace-nowrap font-ui text-[11px] tabular-nums text-fg-3">
              Page {currentPage} of {numPages}
            </span>
          )}
        </div>

        {/* SyncTeX indicator */}
        {synctexReady && (
          <div
            className={`flex items-center gap-1 text-[10px] transition ${
              syncHint ? 'text-warn' : 'text-fg-3'
            }`}
            title="SyncTeX enabled — Ctrl+click PDF to jump to source"
          >
            <MousePointer size={11} />
            {syncHint ? 'Jumping to source…' : 'Ctrl+click to sync'}
          </div>
        )}

        {/* Heatmap + Dark preview + Download */}
        <div className="flex items-center gap-0.5">
          <CapabilityGate feature="c11"><button
            onClick={() => setShowHeatmap((p) => !p)}
            title="Shows predicted areas recruiters focus on (based on eye-tracking research)"
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-surface-2 ${
              showHeatmap ? 'text-accent-strong' : 'text-fg-3 hover:text-fg'
            }`}
          >
            <Flame size={12} /> Heatmap
          </button></CapabilityGate>
          <CapabilityGate feature="c11"><button
            onClick={toggleDarkPdf}
            aria-label={darkPdf ? 'Light PDF preview' : 'Dark PDF preview'}
            title={darkPdf ? 'Switch to light preview' : 'Switch to dark preview'}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-surface-2 ${
              darkPdf ? 'text-accent-strong' : 'text-fg-3 hover:text-fg'
            }`}
          >
            {darkPdf ? <Sun size={12} /> : <Moon size={12} />}
          </button></CapabilityGate>
          <CapabilityGate feature="c11"><button
            onClick={togglePrintPreview}
            aria-label={printPreview ? 'Exit print preview' : 'B&W print preview'}
            title={printPreview ? 'Exit B&W print preview' : 'Preview as B&W printed page'}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] transition hover:bg-surface-2 ${
              printPreview ? 'text-warn' : 'text-fg-3 hover:text-fg'
            }`}
          >
            <Printer size={12} />
            {printPreview ? 'B&W' : 'Print'}
          </button></CapabilityGate>
          {isOfflinePreview && (
            <span className="px-2 py-1 text-[10px] font-medium text-warn" aria-label="Offline saved PDF">Offline saved PDF</span>
          )}
          {onShare && (
            <button
              type="button"
              onClick={() => void onShare()}
              className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            >
              <Share2 size={12} />
              Share
            </button>
          )}
          {onDownload && (
            <button
              onClick={onDownload}
              className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            >
              <Download size={12} />
              PDF
            </button>
          )}
        </div>
      </div>

      {/* Print preview banner */}
      {printPreview && (
        <div className="flex shrink-0 items-center gap-2 border-b border-warn/30 bg-warn/10 px-3 py-1.5">
          <Printer size={12} className="shrink-0 text-warn" />
          <span className="text-[11px] text-warn">
            Print Preview — showing how this looks on a B&W printer
          </span>
        </div>
      )}

      {/* Pages */}
      <div
        ref={setContainerElement}
        className="flex-1 overflow-auto"
        style={{
          background: darkPdf ? 'var(--bg)' : 'var(--surface-2)',
        }}
      >
        {offlineError && (
          <div role="alert" className="flex items-center gap-2 border-b border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            <AlertTriangle size={14} className="shrink-0" />
            <span className="flex-1">{offlineError}</span>
            {onRetryOffline && <button type="button" onClick={onRetryOffline} className="shrink-0 font-semibold underline">Retry</button>}
          </div>
        )}
        {renderError ? (
          <div role="alert" className="flex h-full flex-col items-center justify-center gap-2">
            <FileText className="h-9 w-9 text-fg-3" />
            <p className="text-xs text-fg-3">Failed to render PDF</p>
            {onRetryOffline && (
              <button type="button" onClick={onRetryOffline} className="text-[11px] text-accent-strong hover:underline">
                Retry
              </button>
            )}
            {onDownload && (
              <button onClick={onDownload} className="text-[11px] text-accent-strong hover:underline">
                Download to view
              </button>
            )}
          </div>
        ) : (
          <Document
            key={`${pdfUrl}:${jobId ?? 'no-job'}:${sourceFileName ?? 'main'}:${renderGeneration}`}
            file={pdfUrl}
            onLoadSuccess={(result) => onDocumentLoadSuccess(result, renderGeneration)}
            onLoadError={() => {
              if (isCurrentPdfIdentity(renderGeneration)) setRenderError(true)
            }}
            loading={
              <div className="flex h-32 items-center justify-center">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-accent" />
              </div>
            }
            className="flex min-w-max flex-col items-center gap-5 px-4 py-6"
          >
            {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
              <div
                key={pageNum}
                ref={(el) => {
                  if (isCurrentPdfIdentity(renderGeneration)) pageRefs.current[pageNum] = el
                }}
                data-page-number={pageNum}
                className="shadow-[var(--shadow-2)] select-text"
                style={{ lineHeight: 0, position: 'relative' }}
                // On macOS Control-click produces a context-menu event rather
                // than click. Handle modifier navigation on pointer-down so
                // both Control and Command work across operating systems.
                onMouseDown={(e) => {
                  if (e.button === 0 && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    handlePageClick(e, pageNum)
                  }
                }}
                onClick={(e) => {
                  if (!e.ctrlKey && !e.metaKey) handlePageClick(e, pageNum)
                }}
                onContextMenu={(e) => {
                  if (e.ctrlKey) e.preventDefault()
                }}
                onDoubleClick={(e) => handlePageDoubleClick(e, pageNum)}
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
                    onRenderSuccess={(page) => storePagDims(pageNum, page, renderGeneration)}
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
          <div className="shrink-0 border-t border-warn/20 bg-surface px-4 py-3">
            <div className="mb-2 flex items-center gap-2">
              <AlertTriangle size={13} className="text-warn" />
              <span className="text-[11px] font-semibold text-warn">
                Color-dependent elements detected — these may become invisible or lose meaning in grayscale print:
              </span>
            </div>
            <ul className="space-y-1">
              {colorWarnings.map((w, i) => (
                <li key={i} className="flex items-baseline gap-2 text-[11px]">
                  <button
                    onClick={() => onJumpToLine?.(w.line)}
                    className="shrink-0 rounded bg-warn/20 px-1.5 py-0.5 font-mono text-[10px] text-warn hover:bg-warn/30 transition"
                    title={`Jump to line ${w.line} in editor`}
                  >
                    L{w.line}
                  </button>
                  <code className="font-mono text-warn">{w.command}</code>
                  <span className="truncate text-fg-3" title={w.context}>{w.context}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
