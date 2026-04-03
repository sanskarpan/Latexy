'use client'

import { useMemo } from 'react'
import { Check, X, CheckCheck, XCircle, GitMerge, Trash2, Plus } from 'lucide-react'
import type { TrackedChange } from '@/lib/yjs-track-changes'

// ── Helpers ────────────────────────────────────────────────────────────────

function relativeTime(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000)
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function truncate(text: string, max = 60): string {
  return text.length > max ? text.slice(0, max) + '…' : text
}

// ── Avatar ─────────────────────────────────────────────────────────────────

function Avatar({
  name,
  color,
  size = 20,
}: {
  name: string
  color: string
  size?: number
}) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-bold uppercase text-white"
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        fontSize: size * 0.45,
      }}
    >
      {(name || '?')[0]}
    </div>
  )
}

// ── Change row ─────────────────────────────────────────────────────────────

function ChangeRow({
  change,
  onAccept,
  onReject,
}: {
  change: TrackedChange
  onAccept: (id: string) => void
  onReject: (id: string) => void
}) {
  const isInsert = change.type === 'insertion'

  return (
    <div className="group flex items-start gap-2.5 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2.5 transition hover:bg-white/[0.04]">
      {/* User avatar */}
      <Avatar name={change.userName} color={change.userColor} size={20} />

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold text-zinc-300">
            {change.userName}
          </span>
          <span
            className={`flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
              isInsert
                ? 'bg-emerald-500/15 text-emerald-400'
                : 'bg-red-500/15 text-red-400'
            }`}
          >
            {isInsert ? <Plus size={8} /> : <Trash2 size={8} />}
            {isInsert ? 'added' : 'deleted'}
          </span>
          <span className="ml-auto shrink-0 text-[9px] text-zinc-700">
            {relativeTime(change.timestamp)}
          </span>
        </div>

        {/* Change preview */}
        <p
          className={`mt-1 rounded px-1.5 py-0.5 font-mono text-[10px] leading-relaxed ${
            isInsert
              ? 'bg-emerald-500/10 text-emerald-300'
              : 'bg-red-500/10 text-red-400 line-through'
          }`}
        >
          {truncate(change.text || '(empty)')}
        </p>

        {/* Line badge */}
        <p className="mt-0.5 text-[9px] text-zinc-700">
          Line {change.range.startLineNumber}
          {change.range.startLineNumber !== change.range.endLineNumber
            ? `–${change.range.endLineNumber}`
            : ''}
        </p>
      </div>

      {/* Accept / Reject buttons */}
      <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={() => onAccept(change.id)}
          title="Accept change"
          className="flex h-5 w-5 items-center justify-center rounded text-zinc-600 transition hover:bg-emerald-500/20 hover:text-emerald-400"
        >
          <Check size={10} />
        </button>
        <button
          onClick={() => onReject(change.id)}
          title="Reject change"
          className="flex h-5 w-5 items-center justify-center rounded text-zinc-600 transition hover:bg-red-500/15 hover:text-red-400"
        >
          <X size={10} />
        </button>
      </div>
    </div>
  )
}

// ── Props ──────────────────────────────────────────────────────────────────

interface ChangesPanelProps {
  changes: TrackedChange[]
  onAccept: (id: string) => void
  onReject: (id: string) => void
  onAcceptAll: () => void
  onRejectAll: () => void
}

// ── Component ──────────────────────────────────────────────────────────────

export default function ChangesPanel({
  changes,
  onAccept,
  onReject,
  onAcceptAll,
  onRejectAll,
}: ChangesPanelProps) {
  // Group by user
  const grouped = useMemo(() => {
    const groups = new Map<string, { userName: string; userColor: string; changes: TrackedChange[] }>()
    for (const c of changes) {
      const key = c.userId
      if (!groups.has(key)) {
        groups.set(key, { userName: c.userName, userColor: c.userColor, changes: [] })
      }
      groups.get(key)!.changes.push(c)
    }
    return [...groups.values()]
  }, [changes])

  // ── Empty state ──────────────────────────────────────────────────────────

  if (changes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/[0.04]">
          <GitMerge size={18} className="text-zinc-700" />
        </div>
        <div>
          <p className="text-[12px] font-medium text-zinc-500">No pending changes</p>
          <p className="mt-1 text-[10px] text-zinc-700">
            Collaborator edits will appear here for review.
          </p>
        </div>
      </div>
    )
  }

  // ── Batch action header ──────────────────────────────────────────────────

  const insertCount = changes.filter((c) => c.type === 'insertion').length
  const deleteCount = changes.filter((c) => c.type === 'deletion').length

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.05] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
            {changes.length} pending
          </span>
          <div className="flex gap-1">
            {insertCount > 0 && (
              <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-bold text-emerald-400">
                +{insertCount}
              </span>
            )}
            {deleteCount > 0 && (
              <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[9px] font-bold text-red-400">
                −{deleteCount}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={onAcceptAll}
            className="flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-1 text-[10px] font-semibold text-emerald-400 ring-1 ring-emerald-500/20 transition hover:bg-emerald-500/25"
            title="Accept all changes"
          >
            <CheckCheck size={10} />
            Accept all
          </button>
          <button
            onClick={onRejectAll}
            className="flex items-center gap-1 rounded-md bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-400 ring-1 ring-red-500/20 transition hover:bg-red-500/20"
            title="Reject all changes"
          >
            <XCircle size={10} />
            Reject all
          </button>
        </div>
      </div>

      {/* Change list */}
      <div className="flex-1 overflow-y-auto p-3">
        {grouped.map((group) => (
          <div key={group.userName} className="mb-4">
            {/* Group header */}
            <div className="mb-1.5 flex items-center gap-1.5">
              <Avatar name={group.userName} color={group.userColor} size={14} />
              <span className="text-[10px] font-semibold text-zinc-500">
                {group.userName}
              </span>
              <span className="text-[10px] text-zinc-700">
                · {group.changes.length} change{group.changes.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Individual changes */}
            <div className="space-y-1.5">
              {group.changes.map((change) => (
                <ChangeRow
                  key={change.id}
                  change={change}
                  onAccept={onAccept}
                  onReject={onReject}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
