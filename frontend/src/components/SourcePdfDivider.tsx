'use client'

import { ArrowLeft, ArrowRight } from 'lucide-react'

export interface PdfSelectionLocation {
  page: number
  x: number
  y: number
  line: number
}

interface SourcePdfDividerProps {
  sourceLine: number | null
  pdfSelection: PdfSelectionLocation | null
  pdfReady: boolean
  onSourceToPdf: () => void
  onPdfToSource: () => void
}

/**
 * The two explicit SyncTeX actions live on the editor/preview divider. A
 * normal click only records a selection; these buttons are the only actions
 * that move between panes, which keeps caret movement and PDF browsing local.
 */
export default function SourcePdfDivider({
  sourceLine,
  pdfSelection,
  pdfReady,
  onSourceToPdf,
  onPdfToSource,
}: SourcePdfDividerProps) {
  const sourceAvailable = sourceLine !== null && Number.isInteger(sourceLine) && sourceLine > 0 && pdfReady
  const pdfAvailable = pdfReady && pdfSelection !== null && Number.isInteger(pdfSelection.line) && pdfSelection.line > 0

  return (
    <div
      className="absolute left-1/2 top-1/2 z-30 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1 rounded-full border border-line bg-surface/95 p-0.5 shadow-[var(--shadow-2)]"
      aria-label="Source and PDF synchronization"
      onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        aria-label={sourceAvailable ? `Show source line ${sourceLine} in PDF` : 'Show the selected source line in PDF'}
        title={sourceAvailable ? `Source line ${sourceLine} → PDF` : 'Select a source line and wait for SyncTeX'}
        disabled={!sourceAvailable}
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => { event.stopPropagation(); onSourceToPdf() }}
        className="grid h-6 w-6 place-items-center rounded-full text-fg-3 transition hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-35"
      >
        <ArrowRight size={13} aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label={pdfAvailable ? `Show source line ${pdfSelection.line}` : 'Select a PDF location mapped to source'}
        title={pdfAvailable ? `PDF line ${pdfSelection.line} → source` : 'Select a mapped PDF location'}
        disabled={!pdfAvailable}
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => { event.stopPropagation(); onPdfToSource() }}
        className="grid h-6 w-6 place-items-center rounded-full text-fg-3 transition hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-35"
      >
        <ArrowLeft size={13} aria-hidden="true" />
      </button>
    </div>
  )
}
