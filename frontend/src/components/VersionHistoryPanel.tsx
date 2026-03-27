'use client'

import { useCallback, useEffect, useState } from 'react'
import { Bookmark, Clock, Sparkles, Trash2, GitCompareArrows } from 'lucide-react'
import { toast } from 'sonner'
import type { CheckpointEntry } from '@/lib/api-client'
import { apiClient } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Types                                                               //
// ------------------------------------------------------------------ //

interface VersionHistoryPanelProps {
  resumeId: string
  /** Called when user clicks "Restore" on an entry */
  onRestore: (latex: string) => void
  /** Called when exactly 2 entries are selected and "Compare" is clicked */
  onCompare: (a: CheckpointEntry, b: CheckpointEntry) => void
  /** Called when user clicks "Before/After" on an optimization entry */
  onBeforeAfter?: (original: string, optimized: string) => void
  /** Increment this to force a refresh (e.g. after creating a checkpoint) */
  refreshKey?: number
}

// ------------------------------------------------------------------ //
//  Helpers                                                             //
// ------------------------------------------------------------------ //

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const seconds = Math.floor((now - then) / 1000)

  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

function entryType(e: CheckpointEntry): 'manual' | 'auto' | 'optimization' {
  if (e.is_checkpoint && !e.is_auto_save) return 'manual'
  if (e.is_auto_save) return 'auto'
  return 'optimization'
}

const TYPE_META = {
  manual: {
    icon: Bookmark,
    label: 'Checkpoint',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/20',
    dot: 'bg-blue-400',
  },
  auto: {
    icon: Clock,
    label: 'Auto-save',
    color: 'text-zinc-400',
    bg: 'bg-zinc-500/10',
    border: 'border-zinc-500/20',
    dot: 'bg-zinc-500',
  },
  optimization: {
    icon: Sparkles,
    label: 'AI Optimization',
    color: 'text-orange-400',
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/20',
    dot: 'bg-orange-400',
  },
} as const

// ------------------------------------------------------------------ //
//  Component                                                           //
// ------------------------------------------------------------------ //

export default function VersionHistoryPanel({
  resumeId,
  onRestore,
  onCompare,
  onBeforeAfter,
  refreshKey = 0,
}: VersionHistoryPanelProps) {
  const [entries, setEntries] = useState<CheckpointEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [restoringId, setRestoringId] = useState<string | null>(null)
  const [beforeAfterId, setBeforeAfterId] = useState<string | null>(null)

  // Fetch entries
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiClient
      .listCheckpoints(resumeId, 50)
      .then((data) => {
        if (!cancelled) setEntries(data)
      })
      .catch(() => {
        if (!cancelled) toast.error('Failed to load version history')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [resumeId, refreshKey])

  // Toggle selection (max 2)
  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        if (next.size >= 2) {
          // Remove oldest selection
          const first = next.values().next().value
          if (first !== undefined) next.delete(first)
        }
        next.add(id)
      }
      return next
    })
  }, [])

  // Restore handler — fetches content without mutating the DB
  const handleRestore = useCallback(
    async (entry: CheckpointEntry) => {
      setRestoringId(entry.id)
      try {
        const result = await apiClient.getCheckpointContent(resumeId, entry.id)
        onRestore(result.optimized_latex)
        toast.success('Version restored')
      } catch {
        toast.error('Failed to restore version')
      } finally {
        setRestoringId(null)
      }
    },
    [resumeId, onRestore]
  )

  // Delete handler
  const handleDelete = useCallback(
    async (entry: CheckpointEntry) => {
      try {
        await apiClient.deleteCheckpoint(resumeId, entry.id)
        setEntries((prev) => prev.filter((e) => e.id !== entry.id))
        setSelected((prev) => {
          const next = new Set(prev)
          next.delete(entry.id)
          return next
        })
        toast.success('Checkpoint deleted')
      } catch {
        toast.error('Failed to delete checkpoint')
      }
    },
    [resumeId]
  )

  // Before/After handler for optimization entries
  const handleBeforeAfter = useCallback(
    async (entry: CheckpointEntry) => {
      if (!onBeforeAfter) return
      setBeforeAfterId(entry.id)
      try {
        const result = await apiClient.getCheckpointContent(resumeId, entry.id)
        onBeforeAfter(result.original_latex, result.optimized_latex)
      } catch {
        toast.error('Failed to load optimization diff')
      } finally {
        setBeforeAfterId(null)
      }
    },
    [resumeId, onBeforeAfter]
  )

  // Compare handler
  const handleCompare = useCallback(() => {
    const ids = Array.from(selected)
    if (ids.length !== 2) return
    const a = entries.find((e) => e.id === ids[0])
    const b = entries.find((e) => e.id === ids[1])
    if (!a || !b) return
    // Ensure a is older than b
    const aTime = new Date(a.created_at).getTime()
    const bTime = new Date(b.created_at).getTime()
    if (aTime <= bTime) {
      onCompare(a, b)
    } else {
      onCompare(b, a)
    }
  }, [selected, entries, onCompare])

  if (loading) {
    return (
      <div className="space-y-3 p-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-white/5" />
        ))}
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1.5 py-8 text-center">
        <Clock size={20} className="text-zinc-600" />
        <p className="text-xs text-zinc-600">No version history yet</p>
        <p className="text-[10px] text-zinc-700">
          Checkpoints are created when you compile or save manually.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {/* Compare button */}
      {selected.size === 2 && (
        <div className="sticky top-0 z-10 border-b border-white/5 bg-zinc-950/90 px-3 py-2 backdrop-blur-sm">
          <button
            onClick={handleCompare}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-orange-300/25 bg-orange-300/10 py-1.5 text-xs font-medium text-orange-200 transition hover:bg-orange-300/20"
          >
            <GitCompareArrows size={13} />
            Compare Selected
          </button>
        </div>
      )}

      {/* Timeline */}
      <div className="relative px-3 py-2">
        {/* Vertical line */}
        <div className="absolute bottom-0 left-[26px] top-0 w-px bg-white/5" />

        {entries.map((entry) => {
          const type = entryType(entry)
          const meta = TYPE_META[type]
          const Icon = meta.icon
          const isSelected = selected.has(entry.id)

          return (
            <div key={entry.id} className="relative mb-2 flex gap-3 pl-5">
              {/* Timeline dot */}
              <div
                className={`absolute left-[1px] top-3 z-10 h-2 w-2 rounded-full ring-2 ring-zinc-950 ${meta.dot}`}
              />

              {/* Card */}
              <div
                role="button"
                tabIndex={0}
                onClick={() => toggleSelect(entry.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSelect(entry.id) } }}
                className={`flex w-full cursor-pointer flex-col gap-1 rounded-lg border p-2.5 text-left transition ${
                  isSelected
                    ? 'border-orange-300/30 bg-orange-300/5'
                    : 'border-white/5 bg-white/[0.02] hover:border-white/10 hover:bg-white/[0.04]'
                }`}
              >
                {/* Top row: type badge + time */}
                <div className="flex items-center justify-between">
                  <span
                    className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${meta.bg} ${meta.color} ${meta.border}`}
                  >
                    <Icon size={10} />
                    {meta.label}
                  </span>
                  <span className="text-[10px] text-zinc-600">
                    {relativeTime(entry.created_at)}
                  </span>
                </div>

                {/* Label */}
                <p className="truncate text-xs text-zinc-300">
                  {entry.checkpoint_label ??
                    (type === 'optimization'
                      ? `AI Optimization${entry.optimization_level ? ` — ${entry.optimization_level}` : ''}`
                      : type === 'auto'
                        ? 'Auto-save'
                        : 'Checkpoint')}
                </p>

                {/* Bottom row: scores + actions */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {entry.ats_score != null && (
                      <span
                        className={`text-[10px] font-medium ${
                          entry.ats_score >= 80
                            ? 'text-emerald-400'
                            : entry.ats_score >= 60
                              ? 'text-amber-400'
                              : 'text-rose-400'
                        }`}
                      >
                        ATS {Math.round(entry.ats_score)}
                      </span>
                    )}
                    {entry.changes_count > 0 && (
                      <span className="text-[10px] text-zinc-600">
                        {entry.changes_count} changes
                      </span>
                    )}
                  </div>

                  <div
                    className="flex items-center gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {type === 'optimization' && onBeforeAfter && (
                      <button
                        onClick={() => handleBeforeAfter(entry)}
                        disabled={beforeAfterId === entry.id}
                        className="rounded px-1.5 py-0.5 text-[10px] text-orange-400/70 transition hover:bg-orange-500/10 hover:text-orange-300 disabled:opacity-40"
                      >
                        {beforeAfterId === entry.id ? '…' : 'Before/After'}
                      </button>
                    )}
                    <button
                      onClick={() => handleRestore(entry)}
                      disabled={restoringId === entry.id}
                      className="rounded px-1.5 py-0.5 text-[10px] text-zinc-500 transition hover:bg-white/5 hover:text-zinc-300 disabled:opacity-40"
                    >
                      {restoringId === entry.id ? '…' : 'Restore'}
                    </button>
                    {entry.is_checkpoint && !entry.is_auto_save && (
                      <button
                        onClick={() => handleDelete(entry)}
                        className="rounded p-0.5 text-zinc-600 transition hover:bg-red-500/10 hover:text-red-400"
                        title="Delete checkpoint"
                      >
                        <Trash2 size={11} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
