'use client'

import { useEffect, useRef, useState } from 'react'
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
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [flipUp, setFlipUp] = useState(false)

  // Decide flip direction whenever the panel opens
  useEffect(() => {
    if (!isOpen || !triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom
    const spaceAbove = rect.top
    setFlipUp(spaceBelow < 360 && spaceAbove > spaceBelow)
  }, [isOpen])

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

  // Close on Escape without capturing — other overlay dismiss flows remain unaffected
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  return (
    <div ref={panelRef} className="absolute right-3 top-2 z-50">
      <button
        ref={triggerRef}
        onClick={onToggle}
        title="LaTeX search presets (⌘⇧H)"
        className={`flex items-center gap-1 rounded-[var(--radius-md)] border px-2 py-1 text-[11px] font-medium transition ${
          isOpen
            ? 'border-accent bg-accent-soft text-accent-strong'
            : 'border-line bg-surface text-fg-3 hover:border-line-2 hover:text-fg-2'
        }`}
      >
        <Search size={11} />
        <span className="hidden sm:inline">LaTeX Presets</span>
        <ChevronDown size={10} className={`transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className={`absolute right-0 flex max-h-[min(24rem,calc(100vh-6rem))] w-[min(18rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-[var(--radius-md)] border border-line bg-surface shadow-[var(--shadow-2)] ${
          flipUp ? 'bottom-full mb-1' : 'top-full mt-1'
        }`}>
          <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              LaTeX Patterns
            </span>
            <button onClick={onClose} className="text-fg-3 transition hover:text-fg-2">
              <X size={12} />
            </button>
          </div>
          <div className="overflow-y-auto py-1">
            {presets.map((preset) => (
              <button
                key={preset.label}
                onClick={() => { onPresetSelect(preset); onClose() }}
                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left transition hover:bg-surface-2"
              >
                <span className="text-xs text-fg">{preset.label}</span>
                {preset.description && (
                  <span className="text-[10px] text-fg-3">{preset.description}</span>
                )}
                <code className="mt-0.5 truncate rounded bg-surface-2 px-1.5 py-0.5 text-[9px] font-mono text-accent-strong">
                  {preset.pattern}
                </code>
              </button>
            ))}
          </div>
          <div className="shrink-0 border-t border-line px-3 py-1.5">
            <p className="text-[9px] text-fg-3">Tip: use capture groups (…) for replace-all</p>
          </div>
        </div>
      )}
    </div>
  )
}
