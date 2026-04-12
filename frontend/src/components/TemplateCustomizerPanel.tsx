'use client'

/**
 * TemplateCustomizerPanel — Feature 63
 *
 * Provides a dark-themed panel for fine-grained layout control:
 *   - Margin slider (0.5in – 1.25in, step 0.05)
 *   - Font size picker (10pt / 11pt / 12pt)
 *   - Section spacing picker (Compact / Normal / Spacious)
 *   - Auto-compile toggle (persisted to localStorage)
 *   - Reset to Defaults (restores latex at mount time)
 *
 * Integration note for edit/page.tsx:
 *   1. Add 'layout' to the RightTab union type.
 *   2. Import this component.
 *   3. Add a tab button (e.g. with SlidersHorizontal icon from lucide-react).
 *   4. Render inside the tab content switch:
 *        {activeRightTab === 'layout' && (
 *          <TemplateCustomizerPanel
 *            currentLatex={latexContent}
 *            onPreambleChange={(newLatex) => setLatexContent(newLatex)}
 *            onTriggerCompile={handleCompile}
 *          />
 *        )}
 */

import { useEffect, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import {
  extractRawMarginFromPreamble,
  extractFontSizeFromPreamble,
  extractSectionSpacingFromPreamble,
  setGeometryMargin,
  setDocumentClassFontSize,
  setSectionVspacing,
  type SectionSpacingMode,
} from '@/lib/latex-preamble'

/** Parse a string like "11pt" into the numeric value 11. Falls back to 11. */
function parseFontSizePt(raw: '10pt' | '11pt' | '12pt'): 10 | 11 | 12 {
  const n = parseInt(raw, 10)
  if (n === 10 || n === 11 || n === 12) return n
  return 11
}

const AUTO_COMPILE_KEY = 'latexy_customizer_autocompile'

// ─── Props ───────────────────────────────────────────────────────────────────

interface TemplateCustomizerPanelProps {
  currentLatex: string
  onPreambleChange: (newLatex: string) => void
  onTriggerCompile?: () => void
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function TemplateCustomizerPanel({
  currentLatex,
  onPreambleChange,
  onTriggerCompile,
}: TemplateCustomizerPanelProps) {
  // Keep a ref to the latest latex so event handlers never close over stale values
  const latexRef = useRef(currentLatex)
  useEffect(() => {
    latexRef.current = currentLatex
  }, [currentLatex])

  const compileTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Capture latex at mount time for "Reset to Defaults"
  const [originalLatex] = useState(currentLatex)

  // ── Derived initial state from preamble ────────────────────────────────────
  const [marginIn, setMarginIn] = useState<number>(() =>
    extractRawMarginFromPreamble(currentLatex)
  )
  const [fontSize, setFontSize] = useState<10 | 11 | 12>(() =>
    parseFontSizePt(extractFontSizeFromPreamble(currentLatex))
  )
  const [spacing, setSpacing] = useState<SectionSpacingMode>(() =>
    extractSectionSpacingFromPreamble(currentLatex)
  )
  const [autoCompile, setAutoCompile] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem(AUTO_COMPILE_KEY) === 'true'
  })

  // Re-sync local state when latex changes from an external source
  useEffect(() => {
    setMarginIn(extractRawMarginFromPreamble(currentLatex))
    setFontSize(parseFontSizePt(extractFontSizeFromPreamble(currentLatex)))
    setSpacing(extractSectionSpacingFromPreamble(currentLatex))
  }, [currentLatex])

  // ── Shared apply helper ────────────────────────────────────────────────────

  function applyLatex(newLatex: string, opts?: { debounce?: boolean }) {
    latexRef.current = newLatex
    onPreambleChange(newLatex)
    if (autoCompile) {
      if (opts?.debounce) {
        if (compileTimerRef.current) clearTimeout(compileTimerRef.current)
        compileTimerRef.current = setTimeout(() => onTriggerCompile?.(), 600)
      } else {
        onTriggerCompile?.()
      }
    }
  }

  // Clear debounce timer on unmount
  useEffect(() => {
    return () => {
      if (compileTimerRef.current) clearTimeout(compileTimerRef.current)
    }
  }, [])

  // ── Change handlers ────────────────────────────────────────────────────────

  function handleMargin(value: number) {
    setMarginIn(value)
    const newLatex = setGeometryMargin(latexRef.current, value)
    applyLatex(newLatex, { debounce: true })
  }

  function handleFontSize(size: 10 | 11 | 12) {
    setFontSize(size)
    const newLatex = setDocumentClassFontSize(latexRef.current, size)
    applyLatex(newLatex)
  }

  function handleSpacing(mode: SectionSpacingMode) {
    setSpacing(mode)
    const newLatex = setSectionVspacing(latexRef.current, mode)
    applyLatex(newLatex)
  }

  function handleAutoCompileToggle() {
    const next = !autoCompile
    setAutoCompile(next)
    if (typeof window !== 'undefined') {
      localStorage.setItem(AUTO_COMPILE_KEY, String(next))
    }
  }

  function handleReset() {
    latexRef.current = originalLatex
    onPreambleChange(originalLatex)
    setMarginIn(extractRawMarginFromPreamble(originalLatex))
    setFontSize(parseFontSizePt(extractFontSizeFromPreamble(originalLatex)))
    setSpacing(extractSectionSpacingFromPreamble(originalLatex))
    if (autoCompile) onTriggerCompile?.()
  }

  // ── Shared sub-components ─────────────────────────────────────────────────

  function SectionLabel({ label }: { label: string }) {
    return (
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500 mb-2">
        {label}
      </p>
    )
  }

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col overflow-y-auto scrollbar-subtle bg-[#0e0e0e]">
      <div className="space-y-6 p-4">

        {/* ── Margins ──────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <SectionLabel label="Margins" />
            <span className="text-[11px] tabular-nums text-zinc-400">
              {marginIn.toFixed(2)} in
            </span>
          </div>
          <input
            type="range"
            min={0.5}
            max={1.25}
            step={0.05}
            value={marginIn}
            onChange={(e) => handleMargin(parseFloat(e.target.value))}
            className="w-full accent-orange-400"
          />
          <div className="flex justify-between text-[10px] text-zinc-600">
            <span>0.5 in</span>
            <span>1.25 in</span>
          </div>
        </div>

        {/* ── Font Size ────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Font Size" />
          <div className="flex gap-1">
            {([10, 11, 12] as const).map((s) => (
              <button
                key={s}
                onClick={() => handleFontSize(s)}
                className={`rounded px-3 py-1 text-[11px] transition ${
                  fontSize === s
                    ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {s}pt
              </button>
            ))}
          </div>
        </div>

        {/* ── Section Spacing ──────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Paragraph Spacing" />
          <div className="flex gap-1">
            {(['compact', 'normal', 'spacious'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => handleSpacing(mode)}
                className={`rounded px-3 py-1 text-[11px] capitalize transition ${
                  spacing === mode
                    ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* ── Auto-compile toggle ──────────────────────────────────────── */}
        <div className="border-t border-white/[0.05] pt-4">
          <label className="flex cursor-pointer items-center justify-between gap-3">
            <span className="text-[11px] text-zinc-400">Auto-compile on change</span>
            <button
              role="switch"
              aria-checked={autoCompile}
              onClick={handleAutoCompileToggle}
              className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none ${
                autoCompile ? 'bg-orange-500/70' : 'bg-zinc-700'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
                  autoCompile ? 'translate-x-[18px]' : 'translate-x-[3px]'
                }`}
              />
            </button>
          </label>
        </div>

        {/* ── Reset to Defaults ────────────────────────────────────────── */}
        <div>
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 transition hover:text-zinc-300"
          >
            <RotateCcw size={11} />
            Reset to Defaults
          </button>
        </div>

      </div>
    </div>
  )
}
