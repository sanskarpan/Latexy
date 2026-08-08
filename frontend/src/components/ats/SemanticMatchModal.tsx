'use client'

import { useState, useCallback } from 'react'
import { X, Search, Loader2, TrendingUp } from 'lucide-react'
import type { SemanticMatchResult } from '@/lib/api-client'

interface SemanticMatchModalProps {
  isOpen: boolean
  onClose: () => void
  onMatch: (jobDescription: string) => Promise<void>
  results: SemanticMatchResult[]
  isLoading: boolean
  error: string | null
}

function MatchBar({ score }: { score: number }) {
  const color = score >= 80 ? 'bg-ok' : score >= 60 ? 'bg-warn' : 'bg-err'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-surface-2">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`text-[11px] font-bold tabular-nums ${
        score >= 80 ? 'text-ok' : score >= 60 ? 'text-warn' : 'text-err'
      }`}>{score.toFixed(0)}%</span>
    </div>
  )
}

export default function SemanticMatchModal({
  isOpen,
  onClose,
  onMatch,
  results,
  isLoading,
  error,
}: SemanticMatchModalProps) {
  const [jobDescription, setJobDescription] = useState('')

  const handleMatch = useCallback(async () => {
    if (jobDescription.trim().length < 50) return
    await onMatch(jobDescription)
  }, [jobDescription, onMatch])

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-[var(--overlay)]"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Match to Job Description"
        className="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)]"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <TrendingUp size={14} className="text-accent-strong" />
            </div>
            <span className="text-sm font-semibold text-fg">Match to Job Description</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* JD input */}
          <div>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
              Job Description
            </label>
            <textarea
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              placeholder="Paste the full job description here (minimum 50 characters)…"
              rows={5}
              className="w-full resize-none rounded-[var(--radius-md)] border border-line bg-bg p-3 text-[12px] text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
            />
            <p className="mt-1 text-[10px] text-fg-3">
              {jobDescription.length} chars {jobDescription.length < 50 ? `(${50 - jobDescription.length} more needed)` : '✓'}
            </p>
          </div>

          <button
            onClick={handleMatch}
            disabled={jobDescription.trim().length < 50 || isLoading}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent-soft py-2.5 text-sm font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={13} className="animate-spin" /> Matching…</>
            ) : (
              <><Search size={13} /> Find Best Matches</>
            )}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.07] px-4 py-3">
              <p className="text-[11px] text-err">{error}</p>
            </div>
          )}

          {/* Results */}
          {results.length > 0 && !isLoading && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
                {results.length} resume{results.length !== 1 ? 's' : ''} ranked
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {results.map((result, i) => (
                  <div
                    key={result.resume_id}
                    className="rounded-[var(--radius-md)] border border-line bg-bg p-3 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-semibold text-fg-3">#{i + 1}</span>
                        <span className="text-[11px] font-semibold text-fg truncate max-w-[200px]">
                          {result.resume_title}
                        </span>
                      </div>
                    </div>
                    <MatchBar score={result.similarity_score ?? 0} />
                    {result.missing_keywords.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {result.missing_keywords.slice(0, 5).map((kw, j) => (
                          <span key={j} className="rounded-[var(--radius-md)] bg-err/[0.08] px-1.5 py-0.5 text-[9px] text-err ring-1 ring-err/15">
                            -{kw}
                          </span>
                        ))}
                        {result.missing_keywords.length > 5 && (
                          <span className="text-[9px] text-fg-3">+{result.missing_keywords.length - 5} more</span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
