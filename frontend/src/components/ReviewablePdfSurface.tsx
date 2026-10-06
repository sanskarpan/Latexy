'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import type { ReviewCommentResponse } from '@/lib/api-client'

const Document = dynamic(
  () => import('@/components/ReactPdfClient').then((module) => module.PdfDocument),
  { ssr: false },
)
const Page = dynamic(
  () => import('@/components/ReactPdfClient').then((module) => module.PdfPage),
  { ssr: false },
)

export interface ReviewDocumentAnchor {
  page_number: number
  x: number
  y: number
}

interface ReviewablePdfSurfaceProps {
  pdfUrl: string
  comments: ReviewCommentResponse[]
  selectedAnchor: ReviewDocumentAnchor | null
  selectedCommentId?: string | null
  onAnchorSelect: (anchor: ReviewDocumentAnchor) => void
  onCommentSelect?: (comment: ReviewCommentResponse) => void
}

function clamp(value: number) {
  return Math.max(0, Math.min(1, value))
}

/**
 * The review PDF is deliberately separate from the normal editor preview.
 * It is mounted only when the server has granted the live review capability,
 * so an ordinary public share never downloads a client-side PDF renderer.
 */
export default function ReviewablePdfSurface({
  pdfUrl,
  comments,
  selectedAnchor,
  selectedCommentId,
  onAnchorSelect,
  onCommentSelect,
}: ReviewablePdfSurfaceProps) {
  const [numPages, setNumPages] = useState(0)
  const [pageWidth, setPageWidth] = useState(640)
  const [renderError, setRenderError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const resize = () => {
      const width = element.getBoundingClientRect().width
      if (width > 0) setPageWidth(Math.max(220, Math.min(760, Math.floor(width - 24))))
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const selectAtPoint = useCallback((pageNumber: number, event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    onAnchorSelect({
      page_number: pageNumber,
      x: clamp((event.clientX - rect.left) / rect.width),
      y: clamp((event.clientY - rect.top) / rect.height),
    })
  }, [onAnchorSelect])

  const selectAtCenter = useCallback((pageNumber: number) => {
    onAnchorSelect({ page_number: pageNumber, x: 0.5, y: 0.5 })
  }, [onAnchorSelect])

  const markerComments = comments.filter((comment) => (
    comment.page_number !== null && comment.x !== null && comment.y !== null
  ))

  return (
    <section ref={containerRef} aria-label="Review document" className="min-h-0 overflow-auto bg-surface-2 p-3">
      <Document
        file={pdfUrl}
        loading={<div role="status" className="py-10 text-center text-xs text-fg-3">Loading review document…</div>}
        error={<div role="alert" className="py-10 text-center text-xs text-err">The review document could not be loaded.</div>}
        onLoadSuccess={({ numPages: loadedPages }: { numPages: number }) => {
          setNumPages(loadedPages)
          setRenderError(null)
        }}
        onLoadError={() => setRenderError('The review document could not be loaded.')}
      >
        {renderError ? (
          <div role="alert" className="py-10 text-center text-xs text-err">{renderError}</div>
        ) : Array.from({ length: numPages }, (_, index) => {
          const pageNumber = index + 1
          const pageComments = markerComments.filter((comment) => comment.page_number === pageNumber)
          const pageAnchor = selectedAnchor?.page_number === pageNumber ? selectedAnchor : null
          return (
            <div
              key={pageNumber}
              data-testid="review-pdf-page"
              data-page-number={pageNumber}
              role="group"
              tabIndex={0}
              aria-label={`Page ${pageNumber}. Click to place a review comment anchor.`}
              className="relative mx-auto mb-4 w-fit max-w-full cursor-crosshair rounded-sm shadow-md outline-none focus-visible:ring-2 focus-visible:ring-accent"
              onClick={(event) => selectAtPoint(pageNumber, event)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  selectAtCenter(pageNumber)
                }
              }}
            >
              <Page pageNumber={pageNumber} width={pageWidth} renderTextLayer={false} renderAnnotationLayer={false} />
              {pageComments.map((comment) => (
                <button
                  key={comment.id}
                  type="button"
                  data-testid="review-comment-marker"
                  aria-label={`${comment.resolved ? 'Resolved' : 'Unresolved'} comment by ${comment.reviewer_label}`}
                  title={`${comment.resolved ? 'Resolved' : 'Unresolved'} comment by ${comment.reviewer_label}`}
                  className={`absolute z-10 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${comment.resolved ? 'bg-ok/80' : 'bg-accent'} ${comment.id === selectedCommentId ? 'ring-2 ring-warn' : ''}`}
                  style={{ left: `${clamp(comment.x ?? 0) * 100}%`, top: `${clamp(comment.y ?? 0) * 100}%` }}
                  onClick={(event) => {
                    event.stopPropagation()
                    onCommentSelect?.(comment)
                  }}
                >
                  <span className="sr-only">{comment.content}</span>
                </button>
              ))}
              {pageAnchor && (
                <span
                  data-testid="review-selected-anchor"
                  aria-label="New review comment anchor"
                  className="pointer-events-none absolute z-20 h-6 w-6 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-warn shadow-lg ring-2 ring-warn/40"
                  style={{ left: `${pageAnchor.x * 100}%`, top: `${pageAnchor.y * 100}%` }}
                />
              )}
            </div>
          )
        })}
      </Document>
      {numPages > 0 && (
        <p className="mx-auto max-w-xl pb-2 text-center text-[11px] text-fg-3">
          Click or focus a page and press Enter to place a sticky feedback anchor. Existing dots open their comment.
        </p>
      )}
    </section>
  )
}
