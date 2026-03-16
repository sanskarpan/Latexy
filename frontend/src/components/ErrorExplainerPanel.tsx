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
      className="overflow-hidden border-t border-white/[0.08] transition-all duration-200"
      style={{ height: isOpen ? '13rem' : 0 }}
    >
      <div className="flex h-[13rem] flex-col bg-[#0c0c10]">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-4 py-2">
          <div className="flex items-center gap-2">
            {errorLine != null && (
              <span className="rounded-md bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-rose-400 ring-1 ring-rose-500/20">
                Line {errorLine}
              </span>
            )}
            {data && (
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${
                  data.source === 'llm'
                    ? 'bg-violet-500/15 text-violet-300 ring-violet-400/20'
                    : 'bg-amber-500/15 text-amber-300 ring-amber-400/20'
                }`}
              >
                {data.source === 'llm' ? 'AI' : 'Pattern'}
                {data.cached && ' (cached)'}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex h-full items-center justify-center gap-2 text-zinc-500">
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">Analyzing error...</span>
            </div>
          )}

          {!isLoading && data && (
            <div className="flex h-full gap-4 p-4">
              {/* Left: explanation + fix */}
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">Explanation</p>
                  <p className="mt-1 text-xs leading-relaxed text-zinc-300">{data.explanation}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">Suggested Fix</p>
                  <p className="mt-1 text-xs leading-relaxed text-zinc-400">{data.suggested_fix}</p>
                </div>
              </div>

              {/* Right: corrected code + apply button */}
              {data.corrected_code && (
                <div className="flex w-64 shrink-0 flex-col gap-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">Corrected Code</p>
                  <pre className="flex-1 overflow-auto rounded-lg border border-white/[0.06] bg-black/40 p-2 text-[11px] text-zinc-300">
                    {data.corrected_code}
                  </pre>
                  <button
                    onClick={onApplyFix}
                    className="rounded-lg bg-emerald-500/20 py-1.5 text-[11px] font-semibold text-emerald-300 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30"
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
