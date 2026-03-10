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
  const color = score >= 80 ? 'bg-emerald-400' : score >= 60 ? 'bg-amber-400' : 'bg-rose-400'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-white/[0.05]">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`text-[11px] font-bold tabular-nums ${
        score >= 80 ? 'text-emerald-400' : score >= 60 ? 'text-amber-400' : 'text-rose-400'
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
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-white/[0.08] bg-[#111] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-orange-500/15">
              <TrendingUp size={14} className="text-orange-300" />
            </div>
            <span className="text-sm font-semibold text-zinc-100">Match to Job Description</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-600 transition hover:bg-white/[0.05] hover:text-zinc-200"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* JD input */}
          <div>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
              Job Description
            </label>
            <textarea
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              placeholder="Paste the full job description here (minimum 50 characters)…"
              rows={5}
              className="w-full resize-none rounded-xl border border-white/[0.06] bg-black/40 p-3 text-[12px] text-zinc-200 outline-none transition placeholder:text-zinc-700 focus:border-orange-300/30"
            />
            <p className="mt-1 text-[10px] text-zinc-700">
              {jobDescription.length} chars {jobDescription.length < 50 ? `(${50 - jobDescription.length} more needed)` : '✓'}
            </p>
          </div>

          <button
            onClick={handleMatch}
            disabled={jobDescription.trim().length < 50 || isLoading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-orange-300/20 py-2.5 text-sm font-semibold text-orange-200 ring-1 ring-orange-300/20 transition hover:bg-orange-300/30 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={13} className="animate-spin" /> Matching…</>
            ) : (
              <><Search size={13} /> Find Best Matches</>
            )}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-xl border border-rose-400/20 bg-rose-500/[0.07] px-4 py-3">
              <p className="text-[11px] text-rose-300">{error}</p>
            </div>
          )}

          {/* Results */}
          {results.length > 0 && !isLoading && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
                {results.length} resume{results.length !== 1 ? 's' : ''} ranked
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {results.map((result, i) => (
                  <div
                    key={result.resume_id}
                    className="rounded-xl border border-white/[0.06] bg-black/30 p-3 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-semibold text-zinc-600">#{i + 1}</span>
                        <span className="text-[11px] font-semibold text-zinc-200 truncate max-w-[200px]">
                          {result.resume_title}
                        </span>
                      </div>
                    </div>
                    <MatchBar score={result.similarity_score} />
                    {result.missing_keywords.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {result.missing_keywords.slice(0, 5).map((kw, j) => (
                          <span key={j} className="rounded-md bg-rose-500/[0.08] px-1.5 py-0.5 text-[9px] text-rose-400 ring-1 ring-rose-500/15">
                            -{kw}
                          </span>
                        ))}
                        {result.missing_keywords.length > 5 && (
                          <span className="text-[9px] text-zinc-700">+{result.missing_keywords.length - 5} more</span>
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
