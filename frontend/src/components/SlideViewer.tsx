'use client'

/** Canvas based viewer for compiled Beamer presentations. */

import { useCallback, useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react'
import dynamic from 'next/dynamic'
import { ChevronLeft, ChevronRight, Maximize2, Loader2, Presentation, RotateCw } from 'lucide-react'
import 'react-pdf/dist/Page/TextLayer.css'
import { loadPdfRenderer } from '@/lib/pdf-renderer-loader'
import {
  createSlidePreviewState,
  getSlidePageCount,
  slidePreviewReducer,
} from '@/lib/slide-preview-state'

const Document = dynamic(
  () => loadPdfRenderer().then((module) => module.PdfDocument),
  { ssr: false },
)
const Page = dynamic(
  () => loadPdfRenderer().then((module) => module.PdfPage),
  { ssr: false },
)

interface Props {
  pdfUrl: string | null
  isLoading?: boolean
  /** Slide count supplied by the compile response; PDF.js is authoritative after load. */
  slideCount?: number | null
}

function SlideDocument({ pdfUrl, slideCount }: { pdfUrl: string; slideCount?: number | null }) {
  const [state, dispatch] = useReducer(slidePreviewReducer, pdfUrl, createSlidePreviewState)
  const [containerWidth, setContainerWidth] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const pageCount = getSlidePageCount(state.pageCount, slideCount)
  const requestId = state.requestId

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const measure = () => setContainerWidth(Math.floor(container.getBoundingClientRect().width))
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }

    const observer = new ResizeObserver(measure)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  const navigate = useCallback((page: number) => {
    if (state.phase !== 'ready') return
    dispatch({ type: 'navigate', identity: pdfUrl, requestId, page })
  }, [pdfUrl, requestId, state.phase])

  const previous = useCallback(() => navigate(state.currentPage - 1), [navigate, state.currentPage])
  const next = useCallback(() => navigate(state.currentPage + 1), [navigate, state.currentPage])
  const retry = useCallback(() => {
    dispatch({ type: 'retry', identity: pdfUrl, requestId })
  }, [pdfUrl, requestId])
  const openFullscreen = useCallback(() => {
    window.open(pdfUrl, '_blank', 'noopener,noreferrer')
  }, [pdfUrl])

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault()
      previous()
    } else if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      event.preventDefault()
      next()
    } else if (event.key === 'Home') {
      event.preventDefault()
      navigate(1)
    } else if (event.key === 'End' && pageCount) {
      event.preventDefault()
      navigate(pageCount)
    }
  }, [navigate, next, pageCount, previous])

  return (
    <div
      className="flex h-full flex-col outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
      role="region"
      aria-label="Presentation preview"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div ref={containerRef} className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto bg-bg p-4">
        <Document
          key={`${pdfUrl}:${requestId}`}
          file={pdfUrl}
          loading={null}
          onLoadSuccess={({ numPages }) => dispatch({
            type: 'loaded', identity: pdfUrl, requestId, pageCount: numPages,
          })}
          onLoadError={() => dispatch({ type: 'failed', identity: pdfUrl, requestId })}
          onSourceError={() => dispatch({ type: 'failed', identity: pdfUrl, requestId })}
        >
          {state.phase === 'ready' && containerWidth > 32 && (
            <Page
              key={`${requestId}:${state.currentPage}`}
              pageNumber={state.currentPage}
              width={Math.max(1, containerWidth - 32)}
              renderTextLayer
              renderAnnotationLayer={false}
              onLoadError={() => dispatch({
                type: 'failed', identity: pdfUrl, requestId, page: state.currentPage,
              })}
              onRenderError={() => dispatch({
                type: 'failed', identity: pdfUrl, requestId, page: state.currentPage,
              })}
            />
          )}
        </Document>

        {state.phase === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-fg-3" role="status">
            <Loader2 size={28} className="animate-spin" />
            <p className="text-xs">Loading presentation…</p>
          </div>
        )}
        {state.phase === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-bg text-fg-3" role="alert">
            <Presentation size={28} />
            <p className="text-xs">The presentation preview could not be rendered.</p>
            <button
              onClick={retry}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2"
            >
              <RotateCw size={12} /> Retry preview
            </button>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-line bg-bg px-3 py-1.5">
        <button
          onClick={previous}
          disabled={state.currentPage <= 1 || state.phase !== 'ready'}
          className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="Previous slide"
        >
          <ChevronLeft size={14} />
        </button>

        <span aria-live="polite" className="tabular-nums text-[11px] text-fg-3">
          {pageCount ? <><span className="text-fg-2">{state.currentPage}</span><span className="mx-1">/</span>{pageCount}</> : state.currentPage}
          {pageCount && <span className="ml-2">{pageCount === 1 ? 'slide' : 'slides'}</span>}
        </span>

        <div className="flex items-center gap-1">
          <button
            onClick={next}
            disabled={!pageCount || state.currentPage >= pageCount || state.phase !== 'ready'}
            className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-30"
            aria-label="Next slide"
          >
            <ChevronRight size={14} />
          </button>
          <button
            onClick={openFullscreen}
            className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            aria-label="Open PDF in new tab"
            title="Open presentation PDF in a new tab"
          >
            <Maximize2 size={12} />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function SlideViewer({ pdfUrl, isLoading, slideCount }: Props) {
  if (isLoading) {
    return <div className="flex h-full flex-col items-center justify-center gap-3 text-fg-3"><Loader2 size={28} className="animate-spin" /><p className="text-xs">Compiling presentation…</p></div>
  }

  if (!pdfUrl) {
    return <div className="flex h-full flex-col items-center justify-center gap-3 text-fg-3"><Presentation size={32} /><p className="text-xs text-center leading-5">Click <span className="text-accent-strong">Compile</span> to preview your slides.</p></div>
  }

  return <SlideDocument key={pdfUrl} pdfUrl={pdfUrl} slideCount={slideCount} />
}
