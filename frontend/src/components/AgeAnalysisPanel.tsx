'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, Loader2, Star, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type AgeEntry } from '@/lib/api-client'

interface AgeAnalysisPanelProps {
  isOpen: boolean
  onClose: () => void
  getLatex: () => string
  onJumpToLine?: (line: number) => void
}

export default function AgeAnalysisPanel({
  isOpen,
  onClose,
  getLatex,
  onJumpToLine,
}: AgeAnalysisPanelProps) {
  const [entries, setEntries] = useState<AgeEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  const [previewOpen, setPreviewOpen] = useState(true)

  // Reset on open
  useEffect(() => {
    if (!isOpen) return
    setEntries(null)
    setDismissed(new Set())
    setPreviewOpen(true)
  }, [isOpen])

  const handleAnalyze = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    setLoading(true)
    setEntries(null)
    setDismissed(new Set())
    try {
      const result = await apiClient.ageAnalysis(latex)
      setEntries(result.entries)
      if (result.entries.length === 0) {
        toast.info('No dated experience entries found')
      } else if (!result.has_old_entries) {
        toast.success('All entries are recent — no action needed')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }, [getLatex])

  const handleDismiss = (line: number) => {
    setDismissed((prev) => new Set([...prev, line]))
  }

  if (!isOpen) return null

  const visibleEntries = entries?.filter((e) => !dismissed.has(e.line)) ?? []
  const oldCount = visibleEntries.filter((e) => e.is_old).length

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-lg rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-amber-500/15">
              <Clock size={13} className="text-amber-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Resume Age Analysis</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <p className="text-[12px] text-zinc-500">
            Flags experience entries older than 10 years. Prestigious institutions are exempt.
          </p>

          {/* Analyze button */}
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> Analyzing…</>
            ) : (
              'Analyze Experience Dates'
            )}
          </button>

          {/* Results */}
          {entries !== null && (
            <>
              {visibleEntries.length === 0 ? (
                <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3 text-center">
                  <p className="text-[12px] text-zinc-500">
                    {entries.length === 0 ? 'No dated entries found' : 'All flagged entries dismissed'}
                  </p>
                </div>
              ) : (
                <div className="rounded-lg border border-white/[0.06] bg-black/20">
                  <button
                    onClick={() => setPreviewOpen((o) => !o)}
                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
                  >
                    <span>
                      {visibleEntries.length} entr{visibleEntries.length !== 1 ? 'ies' : 'y'}
                      {oldCount > 0 && (
                        <span className="ml-2 rounded-md bg-amber-500/15 px-1.5 py-0.5 text-amber-300">
                          {oldCount} to review
                        </span>
                      )}
                    </span>
                    {previewOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>

                  {previewOpen && (
                    <div className="max-h-72 divide-y divide-white/[0.04] overflow-y-auto">
                      {visibleEntries.map((entry) => (
                        <div
                          key={`${entry.line}-${entry.start_year}`}
                          className={`px-3 py-2.5 ${entry.is_old ? 'bg-amber-500/[0.04]' : ''}`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-1.5 min-w-0">
                              {entry.is_prestigious ? (
                                <Star size={11} className="shrink-0 text-sky-400" />
                              ) : entry.is_old ? (
                                <AlertTriangle size={11} className="shrink-0 text-amber-400" />
                              ) : (
                                <CheckCircle2 size={11} className="shrink-0 text-emerald-400" />
                              )}
                              <span className="truncate text-[12px] font-medium text-zinc-200">
                                {entry.company_or_institution}
                              </span>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                              {onJumpToLine && (
                                <button
                                  onClick={() => onJumpToLine(entry.line)}
                                  className="rounded px-1.5 py-0.5 text-[10px] text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
                                >
                                  L{entry.line}
                                </button>
                              )}
                              <button
                                onClick={() => handleDismiss(entry.line)}
                                className="rounded px-1.5 py-0.5 text-[10px] text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-400"
                              >
                                Dismiss
                              </button>
                            </div>
                          </div>
                          <div className="mt-0.5 flex items-center gap-2 pl-5">
                            <span className="text-[11px] text-zinc-500">
                              {entry.start_year}
                              {entry.end_year ? ` – ${entry.end_year}` : ' – Present'}
                            </span>
                            <span className={`text-[10px] ${entry.is_old ? 'text-amber-400/80' : 'text-zinc-600'}`}>
                              {entry.years_ago}y ago
                            </span>
                            {entry.is_prestigious && (
                              <span className="text-[10px] text-sky-400/80">Prestigious</span>
                            )}
                          </div>
                          {entry.is_old && (
                            <p className="mt-1 pl-5 text-[10px] leading-relaxed text-zinc-600">
                              {entry.recommendation}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
