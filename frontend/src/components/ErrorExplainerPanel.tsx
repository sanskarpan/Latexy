'use client'

import { useEffect } from 'react'
import { Loader2, X } from 'lucide-react'
import type { ExplainErrorResponse } from '@/lib/api-client'

interface ErrorExplainerPanelProps {
  isOpen: boolean
  isLoading: boolean
  data: ExplainErrorResponse | null
  errorLine: number | null
  onClose: () => void
  onApplyFix: () => void
}

export default function ErrorExplainerPanel({
  isOpen,
  isLoading,
  data,
  errorLine,
  onClose,
  onApplyFix,
}: ErrorExplainerPanelProps) {
  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  return (
    <div
      aria-hidden={!isOpen}
      className="overflow-hidden border-t border-line transition-all duration-200"
      style={{ height: isOpen ? '13rem' : 0 }}
    >
      <div className="flex h-[13rem] flex-col bg-bg">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-2">
          <div className="flex items-center gap-2">
            {errorLine != null && (
              <span className="rounded-[var(--radius-md)] bg-err/15 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-err ring-1 ring-err/20">
                Line {errorLine}
              </span>
            )}
            {data && (
              <span
                className={`rounded-[var(--radius-md)] px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                  data.source === 'llm'
                    ? 'bg-accent-soft text-accent-strong ring-accent'
                    : 'bg-warn/15 text-warn ring-warn/20'
                }`}
              >
                {data.source === 'llm' ? 'AI' : 'Pattern'}
                {data.cached && ' (cached)'}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close error explanation"
            disabled={!isOpen}
            className="rounded-[var(--radius-md)] p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex h-full items-center justify-center gap-2 text-fg-3">
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">Analyzing error...</span>
            </div>
          )}

          {!isLoading && data && (
            <div className="flex h-full gap-4 p-4">
              {/* Left: explanation + fix */}
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">Explanation</p>
                  <p className="mt-1 text-xs leading-relaxed text-fg-2">{data.explanation}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">Suggested Fix</p>
                  <p className="mt-1 text-xs leading-relaxed text-fg-2">{data.suggested_fix}</p>
                </div>
              </div>

              {/* Right: corrected code + apply button */}
              {data.corrected_code && (
                <div className="flex w-64 shrink-0 flex-col gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">Corrected Code</p>
                  <pre className="flex-1 overflow-auto rounded-[var(--radius-md)] border border-line bg-surface-2 p-2 text-[11px] text-fg-2">
                    {data.corrected_code}
                  </pre>
                  <button
                    onClick={onApplyFix}
                    disabled={!isOpen}
                    className="rounded-[var(--radius-md)] bg-ok/20 py-1.5 text-[11px] font-semibold text-ok ring-1 ring-ok/30 transition hover:bg-ok/30"
                  >
                    Apply Fix
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
