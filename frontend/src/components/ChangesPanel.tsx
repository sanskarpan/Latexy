'use client'

import { useMemo } from 'react'
import { GitMerge, Check, X } from 'lucide-react'
import type { TrackedChange } from '@/lib/yjs-track-changes'

interface ChangesPanelProps {
  changes: TrackedChange[]
  onAccept: (id: string) => void
  onReject: (id: string) => void
  onAcceptAll: () => void
  onRejectAll: () => void
}

function relativeTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  return `${Math.floor(diff / 3_600_000)}h ago`
}

export default function ChangesPanel({
  changes,
  onAccept,
  onReject,
  onAcceptAll,
  onRejectAll,
}: ChangesPanelProps) {
  const pending = changes.filter((c) => !c.resolved)

  const grouped = useMemo(() => {
    const map = new Map<string, TrackedChange[]>()
    for (const c of pending) {
      const list = map.get(c.userId) ?? []
      list.push(c)
      map.set(c.userId, list)
    }
    return map
  }, [pending])

  const insertions = pending.filter((c) => c.type === 'insertion').length
  const deletions = pending.filter((c) => c.type === 'deletion').length

  if (pending.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <GitMerge size={28} className="text-zinc-700" />
        <p className="text-sm text-zinc-500">No pending changes</p>
        <p className="text-xs text-zinc-600">
          Changes from collaborators will appear here
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
        <div className="flex items-center gap-2">
          {insertions > 0 && (
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
              +{insertions}
            </span>
          )}
          {deletions > 0 && (
            <span className="rounded bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
              −{deletions}
            </span>
          )}
          <span className="text-[11px] text-zinc-500">pending</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={onAcceptAll}
            className="rounded px-2 py-1 text-[10px] font-medium text-emerald-400 ring-1 ring-emerald-500/20 transition hover:bg-emerald-500/10"
          >
            Accept all
          </button>
          <button
            onClick={onRejectAll}
            className="rounded px-2 py-1 text-[10px] font-medium text-rose-400 ring-1 ring-rose-500/20 transition hover:bg-rose-500/10"
          >
            Reject all
          </button>
        </div>
      </div>

      {/* Change list */}
      <div className="flex-1 overflow-y-auto">
        {Array.from(grouped.entries()).map(([userId, userChanges]) => {
          const first = userChanges[0]
          return (
            <div key={userId} className="border-b border-white/[0.04]">
              {/* User header */}
              <div className="flex items-center gap-2 px-4 py-2">
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
                  style={{ backgroundColor: first.userColor }}
                >
                  {first.userName.slice(0, 1).toUpperCase()}
                </span>
                <span className="text-[11px] font-medium text-zinc-300">{first.userName}</span>
                <span className="ml-auto text-[10px] text-zinc-600">
                  {userChanges.length} change{userChanges.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Changes for this user */}
              {userChanges.map((c) => (
                <div
                  key={c.id}
                  className="group flex items-start gap-3 px-4 py-2.5 transition hover:bg-white/[0.02]"
                >
                  {/* Type badge */}
                  <span
                    className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] font-bold ${
                      c.type === 'insertion'
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : 'bg-rose-500/15 text-rose-300'
                    }`}
                  >
                    {c.type === 'insertion' ? '+' : '−'}
                  </span>

                  {/* Content */}
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[10px] text-zinc-400">
                      {c.text.slice(0, 60)}{c.text.length > 60 ? '…' : ''}
                    </p>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[9px] text-zinc-500">
                        L{c.range.startLineNumber}
                      </span>
                      <span className="text-[9px] text-zinc-600">{relativeTime(c.timestamp)}</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      onClick={() => onAccept(c.id)}
                      title="Accept"
                      className="rounded p-1 text-emerald-400 transition hover:bg-emerald-500/15"
                    >
                      <Check size={12} />
                    </button>
                    <button
                      onClick={() => onReject(c.id)}
                      title="Reject"
                      className="rounded p-1 text-rose-400 transition hover:bg-rose-500/15"
                    >
                      <X size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
