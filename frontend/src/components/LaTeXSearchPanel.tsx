'use client'

import { useEffect, useRef } from 'react'
import { ChevronDown, Search, X } from 'lucide-react'
import type { LatexSearchPreset } from '@/data/latex-search-presets'

interface Props {
  presets: LatexSearchPreset[]
  onPresetSelect: (preset: LatexSearchPreset) => void
  isOpen: boolean
  onToggle: () => void
  onClose: () => void
}

export default function LaTeXSearchPanel({ presets, onPresetSelect, isOpen, onToggle, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, onClose])

  // Close on Escape (only when open — don't swallow Monaco's own Escape)
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
    }
    window.addEventListener('keydown', handler, { capture: true })
    return () => window.removeEventListener('keydown', handler, { capture: true })
  }, [isOpen, onClose])

  return (
    <div ref={panelRef} className="absolute right-3 top-2 z-30">
      <button
        onClick={onToggle}
        title="LaTeX search presets (⌘⇧H)"
        className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition ${
          isOpen
            ? 'border-orange-400/30 bg-orange-400/15 text-orange-300'
            : 'border-white/10 bg-black/40 text-zinc-500 hover:border-white/20 hover:text-zinc-300'
        }`}
      >
        <Search size={11} />
        <span>LaTeX Presets</span>
        <ChevronDown size={10} className={`transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-1 w-72 overflow-hidden rounded-lg border border-white/10 bg-zinc-900 shadow-2xl">
          <div className="flex items-center justify-between border-b border-white/5 px-3 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              LaTeX Patterns
            </span>
            <button onClick={onClose} className="text-zinc-600 transition hover:text-zinc-400">
              <X size={12} />
            </button>
          </div>
          <div className="py-1">
            {presets.map((preset) => (
              <button
                key={preset.label}
                onClick={() => { onPresetSelect(preset); onClose() }}
                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left transition hover:bg-white/5"
              >
                <span className="text-xs text-zinc-200">{preset.label}</span>
                {preset.description && (
                  <span className="text-[10px] text-zinc-600">{preset.description}</span>
                )}
                <code className="mt-0.5 truncate rounded bg-white/5 px-1.5 py-0.5 text-[9px] font-mono text-orange-300/70">
                  {preset.pattern}
                </code>
              </button>
            ))}
          </div>
          <div className="border-t border-white/5 px-3 py-1.5">
            <p className="text-[9px] text-zinc-700">Tip: use capture groups (…) for replace-all</p>
          </div>
        </div>
      )}
    </div>
  )
}
