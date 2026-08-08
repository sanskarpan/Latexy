'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { LATEX_SYMBOLS, SYMBOL_CATEGORIES, type SymbolCategory } from '@/lib/latex-symbols'

interface SymbolPaletteProps {
  onInsert: (command: string) => void
}

export default function SymbolPalette({ onInsert }: SymbolPaletteProps) {
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState<SymbolCategory | 'all'>('all')

  const filtered = useMemo(() => {
    let syms = LATEX_SYMBOLS
    if (activeCategory !== 'all') {
      syms = syms.filter((s) => s.category === activeCategory)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      syms = syms.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.command.toLowerCase().includes(q) ||
          s.unicode.includes(q),
      )
    }
    return syms
  }, [search, activeCategory])

  return (
    <div className="flex h-full flex-col">
      {/* Search */}
      <div className="shrink-0 border-b border-line p-3">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbols..."
            className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 py-1.5 pl-7 pr-3 text-xs text-fg outline-none placeholder:text-fg-3 focus:border-line-2"
          />
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex shrink-0 flex-wrap gap-1 border-b border-line px-3 py-2">
        <button
          onClick={() => setActiveCategory('all')}
          className={`rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-medium transition ${
            activeCategory === 'all'
              ? 'bg-accent-soft text-accent-strong'
              : 'text-fg-3 hover:text-fg-2'
          }`}
        >
          All
        </button>
        {SYMBOL_CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setActiveCategory(cat.id)}
            className={`rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-medium transition ${
              activeCategory === cat.id
                ? 'bg-accent-soft text-accent-strong'
                : 'text-fg-3 hover:text-fg-2'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Symbol grid */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <p className="py-8 text-center text-xs text-fg-3">No symbols match your search.</p>
        ) : (
          <div className="grid grid-cols-8 gap-1">
            {filtered.map((sym) => (
              <button
                key={sym.command}
                onClick={() => onInsert(sym.command)}
                title={`${sym.command}${sym.package ? ` (${sym.package})` : ''}\n${sym.name}`}
                className="group relative flex aspect-square items-center justify-center rounded-[var(--radius-md)] border border-line bg-surface-2 text-lg text-fg-2 transition hover:border-accent hover:bg-accent-soft hover:text-fg"
              >
                <span className="select-none">{sym.unicode}</span>
                {/* Hover overlay with command */}
                <span className="pointer-events-none absolute inset-0 flex items-end justify-center rounded-[var(--radius-md)] bg-[var(--overlay)] pb-0.5 opacity-0 transition group-hover:opacity-100">
                  <span className="truncate px-0.5 font-mono text-[7px] text-accent-strong">
                    {sym.command}
                  </span>
                </span>
                {/* Package indicator dot */}
                {sym.package && (
                  <span className="absolute right-0.5 top-0.5 h-1 w-1 rounded-full bg-accent" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-line px-3 py-1.5 text-[9px] text-fg-3">
        {filtered.length} symbol{filtered.length !== 1 ? 's' : ''}
        {' · Click to insert · '}
        <span className="inline-block h-1 w-1 rounded-full bg-accent" /> = needs package
      </div>
    </div>
  )
}
