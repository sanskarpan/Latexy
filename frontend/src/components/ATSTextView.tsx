'use client'

import { useState } from 'react'
import { Copy, Check, AlertTriangle, CheckCircle, Info } from 'lucide-react'
import {
  SECTION_PATTERNS,
  detectSections,
  hasLigatureGarbling,
  hasColumnGarbling,
} from '@/lib/ats-text-analysis'

// ─── Props ────────────────────────────────────────────────────────────────────

interface ATSTextViewProps {
  extractedText: string | null
  pageCount?: number | null
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ATSTextView({ extractedText, pageCount }: ATSTextViewProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    if (!extractedText) return
    navigator.clipboard.writeText(extractedText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  // ── Empty state ──
  if (!extractedText) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 py-12 text-center">
        <Info size={20} className="text-zinc-700" />
        <p className="text-[11px] text-zinc-600">No extracted text yet.</p>
        <p className="text-[10px] text-zinc-700">Compile your resume to see what an ATS reads.</p>
      </div>
    )
  }

  const ligatureGarbling = hasLigatureGarbling(extractedText)
  const columnGarbling = hasColumnGarbling(extractedText)
  const detectedSections = detectSections(extractedText)
  const hasIssues = ligatureGarbling || columnGarbling

  return (
    <div className="flex h-full flex-col overflow-hidden">

      {/* ── Header ── */}
      <div className="shrink-0 space-y-2 border-b border-white/[0.05] p-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
            ATS Text View
          </p>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
            title="Copy extracted text to clipboard"
          >
            {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>

        <p className="text-[10px] text-zinc-700">
          Plain text extracted from your compiled PDF — exactly what an ATS parser reads.
          {pageCount != null && <span className="ml-1 text-zinc-600">{pageCount} page{pageCount === 1 ? '' : 's'}.</span>}
        </p>

        {/* ── Diagnostics ── */}
        <div className="space-y-1.5">
          {ligatureGarbling && (
            <DiagnosticRow
              level="warning"
              message="Unicode ligature characters detected (ﬁ, ﬀ, ﬂ). Add \input{glyphtounicode} to your preamble — the Linter tab shows the fix."
            />
          )}
          {columnGarbling && (
            <DiagnosticRow
              level="warning"
              message="Possible multi-column garbling: contact info and section headers appear on the same line. Use a single-column layout."
            />
          )}
          {!hasIssues && (
            <DiagnosticRow
              level="ok"
              message="No encoding issues detected in extracted text."
            />
          )}
        </div>

        {/* ── Sections detected / missing ── */}
        <div className="flex flex-wrap gap-1">
          {SECTION_PATTERNS.map(({ label }) => {
            const found = detectedSections.includes(label)
            return (
              <span
                key={label}
                className={
                  found
                    ? 'rounded bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-medium text-emerald-400'
                    : 'rounded bg-white/[0.04] px-1.5 py-0.5 text-[9px] text-zinc-600'
                }
                title={found ? `${label} detected` : `${label} not found`}
              >
                {label}
              </span>
            )
          })}
        </div>
      </div>

      {/* ── Extracted text ── */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-zinc-400">
          {extractedText}
        </pre>
      </div>
    </div>
  )
}

// ─── DiagnosticRow ────────────────────────────────────────────────────────────

function DiagnosticRow({
  level,
  message,
}: {
  level: 'warning' | 'ok'
  message: string
}) {
  if (level === 'ok') {
    return (
      <div className="flex items-start gap-1.5">
        <CheckCircle size={10} className="mt-0.5 shrink-0 text-emerald-500" />
        <p className="text-[10px] text-zinc-500">{message}</p>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-1.5 rounded-lg bg-amber-500/8 px-2 py-1.5 ring-1 ring-amber-500/20">
      <AlertTriangle size={10} className="mt-0.5 shrink-0 text-amber-400" />
      <p className="text-[10px] text-amber-300/80">{message}</p>
    </div>
  )
}
