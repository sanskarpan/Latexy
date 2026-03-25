'use client'

import { useEffect, useRef, useState } from 'react'
import { RotateCcw, AlertTriangle } from 'lucide-react'
import {
  LATEX_FONTS,
  extractFontFromPreamble,
  extractAccentColorFromPreamble,
  extractFontSizeFromPreamble,
  extractMarginsFromPreamble,
  setFontInPreamble,
  setAccentColorInPreamble,
  removeAccentColorFromPreamble,
  setFontSizeInPreamble,
  setMarginsInPreamble,
} from '@/lib/latex-preamble'

// ─── Preset accent colors ────────────────────────────────────────────────────

const PRESET_COLORS: { hex: string; label: string }[] = [
  { hex: '6B46C1', label: 'Violet' },
  { hex: '2563EB', label: 'Blue' },
  { hex: '0891B2', label: 'Cyan' },
  { hex: '059669', label: 'Emerald' },
  { hex: '65A30D', label: 'Lime' },
  { hex: 'CA8A04', label: 'Amber' },
  { hex: 'EA580C', label: 'Orange' },
  { hex: 'DC2626', label: 'Red' },
  { hex: 'DB2777', label: 'Pink' },
  { hex: '7C3AED', label: 'Purple' },
  { hex: '0F172A', label: 'Slate' },
  { hex: '374151', label: 'Gray' },
]

// ─── Props ───────────────────────────────────────────────────────────────────

interface DesignPanelProps {
  currentLatex: string
  onPreambleChange: (newLatex: string) => void
  onTriggerCompile?: () => void
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function DesignPanel({
  currentLatex,
  onPreambleChange,
  onTriggerCompile,
}: DesignPanelProps) {
  // Always have a ref to the latest latex so event handlers don't go stale
  const latexRef = useRef(currentLatex)
  useEffect(() => {
    latexRef.current = currentLatex
  }, [currentLatex])

  // Local UI state — initialized once from parsed preamble
  const [selectedFont, setSelectedFont] = useState(() =>
    extractFontFromPreamble(currentLatex)
  )
  const [accentColor, setAccentColor] = useState(
    () => extractAccentColorFromPreamble(currentLatex) ?? '6B46C1'
  )
  const [hasAccentDefined, setHasAccentDefined] = useState(
    () => extractAccentColorFromPreamble(currentLatex) !== null
  )
  const [fontSize, setFontSize] = useState(() =>
    extractFontSizeFromPreamble(currentLatex)
  )
  const [margin, setMargin] = useState(() =>
    extractMarginsFromPreamble(currentLatex)
  )
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  // ── Handlers ─────────────────────────────────────────────────────────────

  function applyAndCompile(newLatex: string) {
    latexRef.current = newLatex
    onPreambleChange(newLatex)
    onTriggerCompile?.()
  }

  function handleFontChange(fontName: string) {
    setSelectedFont(fontName)
    const font = LATEX_FONTS.find((f) => f.name === fontName)
    const newLatex = setFontInPreamble(
      latexRef.current,
      font?.package ?? null,
      font?.command ?? null
    )
    applyAndCompile(newLatex)
  }

  function handleAccentColorChange(hex: string) {
    setAccentColor(hex)
    const newLatex = setAccentColorInPreamble(latexRef.current, hex)
    setHasAccentDefined(true)
    applyAndCompile(newLatex)
  }

  function handleFontSizeChange(size: '10pt' | '11pt' | '12pt') {
    setFontSize(size)
    const newLatex = setFontSizeInPreamble(latexRef.current, size)
    applyAndCompile(newLatex)
  }

  function handleMarginChange(m: string) {
    setMargin(m)
    const newLatex = setMarginsInPreamble(latexRef.current, m)
    applyAndCompile(newLatex)
  }

  function handleReset() {
    setShowResetConfirm(false)
    let newLatex = latexRef.current
    // Reset font → Computer Modern
    newLatex = setFontInPreamble(newLatex, null, null)
    setSelectedFont('Computer Modern')
    // Reset font size → 11pt
    newLatex = setFontSizeInPreamble(newLatex, '11pt')
    setFontSize('11pt')
    // Reset margins → 0.75in
    newLatex = setMarginsInPreamble(newLatex, '0.75in')
    setMargin('0.75in')
    // Remove accent color if present
    if (extractAccentColorFromPreamble(newLatex)) {
      newLatex = removeAccentColorFromPreamble(newLatex)
      setHasAccentDefined(false)
      setAccentColor('6B46C1')
    }
    applyAndCompile(newLatex)
  }

  // ── Section header ────────────────────────────────────────────────────────

  function SectionLabel({ label }: { label: string }) {
    return (
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
        {label}
      </p>
    )
  }

  // ─── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col overflow-y-auto scrollbar-subtle">
      <div className="space-y-6 p-4">

        {/* ── Font Family ────────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Font Family" />
          <div
            className="max-h-[200px] overflow-y-auto rounded-xl border border-white/[0.06] bg-black/30"
          >
            {/* Serif group */}
            <div className="px-2 pt-2 pb-1">
              <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-zinc-800 px-1 mb-1">
                Serif
              </p>
              {LATEX_FONTS.filter((f) => f.category === 'serif').map((font) => (
                <FontRow
                  key={font.name}
                  font={font}
                  active={selectedFont === font.name}
                  onClick={() => handleFontChange(font.name)}
                />
              ))}
            </div>

            {/* Sans-serif group */}
            <div className="border-t border-white/[0.04] px-2 pt-2 pb-2">
              <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-zinc-800 px-1 mb-1">
                Sans-Serif
              </p>
              {LATEX_FONTS.filter((f) => f.category === 'sans-serif').map((font) => (
                <FontRow
                  key={font.name}
                  font={font}
                  active={selectedFont === font.name}
                  onClick={() => handleFontChange(font.name)}
                />
              ))}
            </div>
          </div>
        </div>

        {/* ── Accent Color ───────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Accent Color" />
          <div className="flex flex-wrap gap-1.5">
            {PRESET_COLORS.map(({ hex, label }) => (
              <button
                key={hex}
                title={label}
                onClick={() => handleAccentColorChange(hex)}
                className="relative h-6 w-6 rounded-full transition-transform hover:scale-110 focus:outline-none"
                style={{ backgroundColor: `#${hex}` }}
              >
                {accentColor.toUpperCase() === hex && (
                  <span className="absolute inset-0 rounded-full ring-2 ring-white/60 ring-offset-1 ring-offset-black" />
                )}
              </button>
            ))}

            {/* Custom color picker */}
            <label
              title="Custom color"
              className="relative flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/[0.04] transition hover:bg-white/[0.08]"
            >
              <span className="text-[10px] text-zinc-500">+</span>
              <input
                type="color"
                value={`#${accentColor}`}
                onChange={(e) => {
                  const hex = e.target.value.replace('#', '')
                  handleAccentColorChange(hex)
                }}
                className="absolute inset-0 h-full w-full cursor-pointer rounded-full opacity-0"
              />
            </label>
          </div>

          {!hasAccentDefined && (
            <div className="flex items-start gap-1.5 rounded-lg bg-amber-500/10 px-2.5 py-2 text-[10px] text-amber-400 ring-1 ring-amber-500/20">
              <AlertTriangle size={11} className="mt-px shrink-0" />
              <span>
                No <code className="opacity-70">\definecolor&#123;accent&#125;</code> found. Applying will
                add it — it only affects templates that use this color.
              </span>
            </div>
          )}
        </div>

        {/* ── Font Size ──────────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Base Font Size" />
          <div className="grid grid-cols-3 gap-1 rounded-xl border border-white/[0.06] bg-black/30 p-1">
            {(['10pt', '11pt', '12pt'] as const).map((s) => (
              <button
                key={s}
                onClick={() => handleFontSizeChange(s)}
                className={`rounded-lg py-2 text-[11px] font-medium transition ${
                  fontSize === s
                    ? 'bg-violet-500/25 text-violet-200 ring-1 ring-violet-400/30'
                    : 'text-zinc-600 hover:text-zinc-300'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* ── Margins ────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <SectionLabel label="Margins" />
          <div className="grid grid-cols-3 gap-1 rounded-xl border border-white/[0.06] bg-black/30 p-1">
            {([
              { label: 'Tight', value: '0.5in' },
              { label: 'Normal', value: '0.75in' },
              { label: 'Spacious', value: '1in' },
            ] as const).map(({ label, value }) => (
              <button
                key={value}
                onClick={() => handleMarginChange(value)}
                className={`rounded-lg py-2 text-[11px] font-medium transition ${
                  margin === value
                    ? 'bg-violet-500/25 text-violet-200 ring-1 ring-violet-400/30'
                    : 'text-zinc-600 hover:text-zinc-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-zinc-700">
            {margin === '0.5in'
              ? '0.5 in — compact, maximizes content area'
              : margin === '0.75in'
              ? '0.75 in — standard resume margin'
              : '1 in — spacious, suits shorter resumes'}
          </p>
        </div>

        {/* ── Reset ──────────────────────────────────────────────────── */}
        <div className="border-t border-white/[0.05] pt-4">
          {showResetConfirm ? (
            <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3 space-y-2">
              <p className="text-[11px] text-rose-300">
                Reset to Computer Modern, 11pt, 0.75in margins, and remove accent color?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={handleReset}
                  className="rounded-lg bg-rose-500/20 px-3 py-1.5 text-[11px] font-semibold text-rose-300 ring-1 ring-rose-500/30 transition hover:bg-rose-500/30"
                >
                  Reset
                </button>
                <button
                  onClick={() => setShowResetConfirm(false)}
                  className="rounded-lg px-3 py-1.5 text-[11px] text-zinc-500 transition hover:text-zinc-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowResetConfirm(true)}
              className="flex items-center gap-1.5 text-[11px] text-zinc-700 transition hover:text-zinc-400"
            >
              <RotateCcw size={11} />
              Reset to defaults
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── FontRow ─────────────────────────────────────────────────────────────────

function FontRow({
  font,
  active,
  onClick,
}: {
  font: (typeof LATEX_FONTS)[number]
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition ${
        active
          ? 'bg-violet-500/20 text-violet-200'
          : 'text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-200'
      }`}
    >
      <span
        className="min-w-0 flex-1 truncate text-[12px]"
        style={{ fontFamily: font.webPreview }}
      >
        {font.name}
      </span>
      {active && (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
      )}
    </button>
  )
}
