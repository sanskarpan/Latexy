'use client'

import { useState, useEffect, useRef } from 'react'
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
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const handleCopy = () => {
    if (!extractedText) return
    navigator.clipboard.writeText(extractedText)
      .then(() => {
        setCopied(true)
        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => {
        // Clipboard access unavailable (non-HTTPS or permission denied)
      })
  }

  // ── Empty state ──
  if (!extractedText) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 py-12 text-center">
        <Info size={20} className="text-fg-3" />
        <p className="text-[11px] text-fg-3">No extracted text yet.</p>
        <p className="text-[10px] text-fg-3">Compile your resume to see what an ATS reads.</p>
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
      <div className="shrink-0 space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
            ATS Text View
          </p>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
            title="Copy extracted text to clipboard"
          >
            {copied ? <Check size={10} className="text-ok" /> : <Copy size={10} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>

        <p className="text-[10px] text-fg-3">
          Plain text extracted from your compiled PDF — exactly what an ATS parser reads.
          {pageCount != null && <span className="ml-1 text-fg-3">{pageCount} page{pageCount === 1 ? '' : 's'}.</span>}
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
                    ? 'rounded bg-ok/10 px-1.5 py-0.5 text-[9px] font-medium text-ok'
                    : 'rounded bg-surface-2 px-1.5 py-0.5 text-[9px] text-fg-3'
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
        <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-fg-2">
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
        <CheckCircle size={10} className="mt-0.5 shrink-0 text-ok" />
        <p className="text-[10px] text-fg-3">{message}</p>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-1.5 rounded-[var(--radius-md)] bg-warn/10 px-2 py-1.5 ring-1 ring-warn/20">
      <AlertTriangle size={10} className="mt-0.5 shrink-0 text-warn" />
      <p className="text-[10px] text-warn">{message}</p>
    </div>
  )
}
