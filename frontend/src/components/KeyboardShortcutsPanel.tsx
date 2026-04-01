'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Search, Keyboard } from 'lucide-react'
import { SHORTCUTS, CATEGORY_LABELS, CATEGORY_ORDER, type Shortcut } from '@/lib/editor-shortcuts'

interface KeyboardShortcutsPanelProps {
  isOpen: boolean
  onClose: () => void
}

export default function KeyboardShortcutsPanel({ isOpen, onClose }: KeyboardShortcutsPanelProps) {
  const [search, setSearch] = useState('')

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  // Reset search when opening
  useEffect(() => {
    if (isOpen) setSearch('')
  }, [isOpen])

  const filtered = useMemo(() => {
    if (!search.trim()) return SHORTCUTS
    const q = search.toLowerCase()
    return SHORTCUTS.filter(
      (s) =>
        s.description.toLowerCase().includes(q) ||
        s.keys.join(' ').toLowerCase().includes(q) ||
        CATEGORY_LABELS[s.category].toLowerCase().includes(q)
    )
  }, [search])

  const grouped = useMemo(() => {
    const map = new Map<Shortcut['category'], Shortcut[]>()
    for (const s of filtered) {
      const list = map.get(s.category) || []
      list.push(s)
      map.set(s.category, list)
    }
    return CATEGORY_ORDER
      .filter((cat) => map.has(cat))
      .map((cat) => ({ category: cat, label: CATEGORY_LABELS[cat], shortcuts: map.get(cat)! }))
  }, [filtered])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose()
    },
    [onClose]
  )

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-lg rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-orange-500/15">
              <Keyboard size={14} className="text-orange-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="border-b border-white/[0.06] px-5 py-2.5">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600" size={13} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search shortcuts..."
              autoFocus
              className="w-full rounded-lg border border-white/[0.06] bg-white/[0.03] py-1.5 pl-8 pr-3 text-sm text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-orange-400/30"
            />
          </div>
        </div>

        {/* Shortcuts list */}
        <div className="max-h-[420px] overflow-y-auto px-5 py-3">
          {grouped.length === 0 ? (
            <p className="py-8 text-center text-sm text-zinc-600">No shortcuts match your search</p>
          ) : (
            <div className="space-y-4">
              {grouped.map(({ category, label, shortcuts }) => (
                <div key={category}>
                  <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-600">
                    {label}
                  </p>
                  <div className="space-y-0.5">
                    {shortcuts.map((s) => (
                      <div
                        key={s.description}
                        className="flex items-center justify-between rounded-lg px-2 py-1.5 transition hover:bg-white/[0.03]"
                      >
                        <span className="text-[13px] text-zinc-400">{s.description}</span>
                        <div className="flex items-center gap-1">
                          {s.keys.map((key, i) => (
                            <kbd
                              key={i}
                              className="inline-flex min-w-[22px] items-center justify-center rounded-md border border-white/[0.08] bg-white/[0.04] px-1.5 py-0.5 text-[11px] font-medium text-zinc-400"
                            >
                              {key}
                            </kbd>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-white/[0.06] px-5 py-2.5">
          <p className="text-[10px] text-zinc-700">
            Press <kbd className="rounded border border-white/[0.08] bg-white/[0.04] px-1 py-0.5 text-[10px] text-zinc-500">Esc</kbd> to close
          </p>
        </div>
      </div>
    </div>
  )
}
