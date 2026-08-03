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
      role="dialog"
      aria-modal="true"
      aria-labelledby="keyboard-shortcuts-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-lg rounded-[var(--radius-md)] border border-line bg-bg shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Keyboard size={14} className="text-accent-strong" />
            </div>
            <h2 id="keyboard-shortcuts-title" className="text-sm font-semibold text-fg">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close keyboard shortcuts"
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="border-b border-line px-5 py-2.5">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3" size={13} />
            <input
              type="text"
              aria-label="Search keyboard shortcuts"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search shortcuts..."
              autoFocus
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 py-1.5 pl-8 pr-3 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-accent"
            />
          </div>
        </div>

        {/* Shortcuts list */}
        <div className="max-h-[420px] overflow-y-auto px-5 py-3">
          {grouped.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-3">No shortcuts match your search</p>
          ) : (
            <div className="space-y-4">
              {grouped.map(({ category, label, shortcuts }) => (
                <div key={category}>
                  <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-fg-3">
                    {label}
                  </p>
                  <div className="space-y-0.5">
                    {shortcuts.map((s) => (
                      <div
                        key={s.description}
                        className="flex items-center justify-between rounded-[var(--radius-md)] px-2 py-1.5 transition hover:bg-surface-2"
                      >
                        <span className="text-[13px] text-fg-2">{s.description}</span>
                        <div className="flex items-center gap-1">
                          {s.keys.map((key, i) => (
                            <kbd
                              key={i}
                              className="inline-flex min-w-[22px] items-center justify-center rounded-[var(--radius-md)] border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-fg-2"
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
        <div className="border-t border-line px-5 py-2.5">
          <p className="text-[10px] text-fg-3">
            Press <kbd className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-1 py-0.5 text-[10px] text-fg-3">Esc</kbd> to close
          </p>
        </div>
      </div>
    </div>
  )
}
