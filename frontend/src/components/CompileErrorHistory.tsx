'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Clock, RefreshCw, Trophy, X } from 'lucide-react'
import Link from 'next/link'
import { apiClient, type ErrorHistorySummary } from '@/lib/api-client'

interface CompileErrorHistoryProps {
  onClose: () => void
}

function formatRelativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const days = Math.floor(diff / 86_400_000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 30) return `${days} days ago`
  const months = Math.floor(days / 30)
  if (months === 1) return '1 month ago'
  if (months < 12) return `${months} months ago`
  return `${Math.floor(months / 12)}y ago`
}

export default function CompileErrorHistory({ onClose }: CompileErrorHistoryProps) {
  const [summaries, setSummaries] = useState<ErrorHistorySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.getErrorHistory(50)
      setSummaries(data)
    } catch {
      setError('Failed to load error history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const toggle = (errorType: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(errorType)) next.delete(errorType)
      else next.add(errorType)
      return next
    })
  }

  const topError = summaries[0]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 shrink-0">
          <div className="flex items-center gap-2.5">
            <AlertCircle size={18} className="text-orange-400" />
            <h2 className="text-sm font-semibold text-white">Compile Error History</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 disabled:opacity-40 transition"
              title="Refresh"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 transition"
              aria-label="Close"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">

          {/* Most-common error banner */}
          {topError && topError.count > 1 && (
            <div className="mx-4 mt-4 flex items-start gap-3 rounded-xl border border-orange-500/20 bg-orange-500/[0.07] px-4 py-3">
              <Trophy size={16} className="mt-0.5 shrink-0 text-orange-400" />
              <div className="min-w-0">
                <p className="text-xs font-semibold text-orange-300">Most common mistake</p>
                <p className="mt-0.5 truncate text-sm font-mono text-orange-100">{topError.error_type}</p>
                <p className="mt-0.5 text-xs text-orange-400/70">
                  Encountered {topError.count} time{topError.count !== 1 ? 's' : ''}
                  {topError.resolved ? ' · resolved' : ' · still recurring'}
                </p>
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-16 text-sm text-zinc-500">
              <RefreshCw size={16} className="mr-2 animate-spin" />
              Loading…
            </div>
          )}

          {/* Error */}
          {!loading && error && (
            <div className="flex flex-col items-center gap-3 py-16 text-sm text-zinc-500">
              <AlertCircle size={24} className="text-red-400" />
              <span>{error}</span>
              <button
                onClick={load}
                className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white hover:bg-white/15 transition"
              >
                Retry
              </button>
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && summaries.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-20">
              <CheckCircle2 size={28} className="text-emerald-400" />
              <p className="text-sm font-medium text-zinc-300">No compile errors yet — great work!</p>
              <p className="text-xs text-zinc-500">Error patterns will appear here as you compile your resumes.</p>
            </div>
          )}

          {/* Error table */}
          {!loading && !error && summaries.length > 0 && (
            <table className="w-full text-sm mt-4">
              <thead>
                <tr className="border-b border-white/5 text-left">
                  <th className="px-5 pb-2 text-xs font-medium text-zinc-500 w-1/2">Error Type</th>
                  <th className="px-3 pb-2 text-xs font-medium text-zinc-500 text-center">Times</th>
                  <th className="px-3 pb-2 text-xs font-medium text-zinc-500">Last Seen</th>
                  <th className="px-3 pb-2 text-xs font-medium text-zinc-500 text-center">Status</th>
                </tr>
              </thead>
              <tbody>
                {summaries.map((s) => {
                  const isExpanded = expanded.has(s.error_type)
                  return (
                    <>
                      <tr
                        key={s.error_type}
                        className="group cursor-pointer border-b border-white/5 hover:bg-white/[0.03] transition"
                        onClick={() => toggle(s.error_type)}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="shrink-0 text-zinc-500">
                              {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                            </span>
                            <span className="font-mono text-xs text-orange-300 truncate max-w-[260px]" title={s.error_type}>
                              {s.error_type}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-3 text-center">
                          <span className="rounded-full bg-orange-500/20 px-2 py-0.5 text-xs font-semibold text-orange-300">
                            {s.count}×
                          </span>
                        </td>
                        <td className="px-3 py-3 text-xs text-zinc-400 whitespace-nowrap">
                          <span className="flex items-center gap-1.5">
                            <Clock size={11} className="shrink-0 text-zinc-600" />
                            {formatRelativeDate(s.last_seen)}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-center">
                          {s.resolved ? (
                            <span className="flex items-center justify-center gap-1 text-xs text-emerald-400">
                              <CheckCircle2 size={12} />
                              Resolved
                            </span>
                          ) : (
                            <span className="flex items-center justify-center gap-1 text-xs text-amber-400">
                              <AlertCircle size={12} />
                              Recurring
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* Expanded detail row */}
                      {isExpanded && (
                        <tr key={`${s.error_type}-detail`} className="border-b border-white/5 bg-white/[0.02]">
                          <td colSpan={4} className="px-6 py-3 space-y-2">
                            <div>
                              <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mb-1">Example output</p>
                              <code className="block rounded-md bg-black/50 px-3 py-2 font-mono text-xs text-orange-200 break-all">
                                {s.example_line || '(no details)'}
                              </code>
                            </div>
                            {s.last_resume_id && (
                              <div className="flex items-center gap-2 text-xs text-zinc-400">
                                <span className="shrink-0">Last in:</span>
                                <Link
                                  href={`/workspace/${s.last_resume_id}/edit`}
                                  className="text-violet-400 hover:text-violet-300 underline underline-offset-2 truncate"
                                  onClick={onClose}
                                >
                                  {s.last_resume_title ?? s.last_resume_id}
                                </Link>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
          )}

        </div>

        {/* Footer */}
        <div className="border-t border-white/10 px-6 py-3 shrink-0 flex items-center justify-between">
          <p className="text-xs text-zinc-600">
            {summaries.length > 0
              ? `${summaries.length} error type${summaries.length !== 1 ? 's' : ''} found`
              : 'No errors'}
          </p>
          <button
            onClick={onClose}
            className="rounded-lg bg-white/10 px-4 py-1.5 text-xs font-medium text-white hover:bg-white/15 transition"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  )
}
