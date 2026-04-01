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
      <div className="shrink-0 border-b border-white/[0.05] p-3">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbols..."
            className="w-full rounded-md border border-white/[0.06] bg-white/[0.03] py-1.5 pl-7 pr-3 text-xs text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-white/[0.12]"
          />
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex shrink-0 flex-wrap gap-1 border-b border-white/[0.05] px-3 py-2">
        <button
          onClick={() => setActiveCategory('all')}
          className={`rounded px-2 py-0.5 text-[10px] font-medium transition ${
            activeCategory === 'all'
              ? 'bg-orange-500/20 text-orange-300'
              : 'text-zinc-600 hover:text-zinc-300'
          }`}
        >
          All
        </button>
        {SYMBOL_CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setActiveCategory(cat.id)}
            className={`rounded px-2 py-0.5 text-[10px] font-medium transition ${
              activeCategory === cat.id
                ? 'bg-orange-500/20 text-orange-300'
                : 'text-zinc-600 hover:text-zinc-300'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Symbol grid */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <p className="py-8 text-center text-xs text-zinc-700">No symbols match your search.</p>
        ) : (
          <div className="grid grid-cols-8 gap-1">
            {filtered.map((sym) => (
              <button
                key={sym.command}
                onClick={() => onInsert(sym.command)}
                title={`${sym.command}${sym.package ? ` (${sym.package})` : ''}\n${sym.name}`}
                className="group relative flex aspect-square items-center justify-center rounded-md border border-white/[0.04] bg-white/[0.02] text-lg text-zinc-300 transition hover:border-orange-500/30 hover:bg-orange-500/10 hover:text-white"
              >
                <span className="select-none">{sym.unicode}</span>
                {/* Hover overlay with command */}
                <span className="pointer-events-none absolute inset-0 flex items-end justify-center rounded-md bg-black/80 pb-0.5 opacity-0 transition group-hover:opacity-100">
                  <span className="truncate px-0.5 font-mono text-[7px] text-orange-300">
                    {sym.command}
                  </span>
                </span>
                {/* Package indicator dot */}
                {sym.package && (
                  <span className="absolute right-0.5 top-0.5 h-1 w-1 rounded-full bg-violet-400/60" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-white/[0.05] px-3 py-1.5 text-[9px] text-zinc-700">
        {filtered.length} symbol{filtered.length !== 1 ? 's' : ''}
        {' · Click to insert · '}
        <span className="inline-block h-1 w-1 rounded-full bg-violet-400/60" /> = needs package
      </div>
    </div>
  )
}
