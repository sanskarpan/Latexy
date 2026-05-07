'use client'

/**
 * SlideViewer — Feature 86
 * A lightweight slide viewer for compiled Beamer presentations.
 * Uses <iframe> just like PDFPreview but adds prev/next slide navigation
 * and a slide-count badge. We avoid react-pdf to keep bundle size small
 * and to stay consistent with the existing PDFPreview pattern.
 */

import { useState, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Maximize2, Loader2, Presentation } from 'lucide-react'

interface Props {
  pdfUrl: string | null
  isLoading?: boolean
  /** Total slide count returned by the backend (page_count for Beamer). */
  slideCount?: number | null
}

export default function SlideViewer({ pdfUrl, isLoading, slideCount }: Props) {
  const [currentSlide, setCurrentSlide] = useState(1)
  const total = slideCount ?? null

  // Reset to slide 1 whenever the PDF changes (new compilation)
  useEffect(() => {
    setCurrentSlide(1)
  }, [pdfUrl])

  const prevSlide = useCallback(() => {
    setCurrentSlide(s => Math.max(1, s - 1))
  }, [])

  const nextSlide = useCallback(() => {
    setCurrentSlide(s => (total ? Math.min(total, s + 1) : s + 1))
  }, [total])

  const openFullscreen = useCallback(() => {
    if (pdfUrl) window.open(pdfUrl, '_blank')
  }, [pdfUrl])

  // Build the PDF URL with a page anchor so the browser jumps to that slide
  const pagedUrl = pdfUrl ? `${pdfUrl}#page=${currentSlide}` : null

  // ── Empty / loading states ────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-zinc-600">
        <Loader2 size={28} className="animate-spin" />
        <p className="text-xs">Compiling presentation…</p>
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-zinc-700">
        <Presentation size={32} />
        <p className="text-xs text-center leading-5">
          Click <span className="text-orange-300">Compile</span> to preview your slides.
        </p>
      </div>
    )
  }

  // ── Main viewer ───────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col">
      {/* Slide iframe */}
      <div className="relative min-h-0 flex-1">
        <iframe
          key={pagedUrl}
          src={pagedUrl ?? ''}
          className="h-full w-full border-0 bg-zinc-950"
          title={`Slide ${currentSlide}`}
        />
      </div>

      {/* Navigation bar */}
      <div className="flex shrink-0 items-center justify-between border-t border-white/[0.06] bg-[#0a0a0a] px-3 py-1.5">
        {/* Prev */}
        <button
          onClick={prevSlide}
          disabled={currentSlide <= 1}
          className="flex h-6 w-6 items-center justify-center rounded text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="Previous slide"
        >
          <ChevronLeft size={14} />
        </button>

        {/* Slide counter */}
        <span className="tabular-nums text-[11px] text-zinc-500">
          {total ? (
            <>
              <span className="text-zinc-300">{currentSlide}</span>
              <span className="mx-1 text-zinc-700">/</span>
              <span>{total}</span>
            </>
          ) : (
            <span className="text-zinc-300">{currentSlide}</span>
          )}
          {total && (
            <span className="ml-2 text-zinc-700">
              {total === 1 ? 'slide' : 'slides'}
            </span>
          )}
        </span>

        <div className="flex items-center gap-1">
          {/* Next */}
          <button
            onClick={nextSlide}
            disabled={!!total && currentSlide >= total}
            className="flex h-6 w-6 items-center justify-center rounded text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30"
            aria-label="Next slide"
          >
            <ChevronRight size={14} />
          </button>

          {/* Open in new tab */}
          <button
            onClick={openFullscreen}
            className="flex h-6 w-6 items-center justify-center rounded text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
            aria-label="Open PDF in new tab"
          >
            <Maximize2 size={12} />
          </button>
        </div>
      </div>
    </div>
  )
}
