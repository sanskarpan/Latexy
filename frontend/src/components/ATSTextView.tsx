'use client'

import { useState } from 'react'
import { Copy, Check, AlertTriangle, CheckCircle, Info } from 'lucide-react'

// ─── Garbling detection ───────────────────────────────────────────────────────

// Unicode ligature characters that indicate pdftotext failed to decode them —
// means the PDF was compiled without \input{glyphtounicode}.
const LIGATURE_RE = /[ﬀﬁﬂﬃﬄﬅﬆ]/

// Sequences that look like ATS-garbled column layout: a line that contains
// both contact-info tokens (email/phone) and experience keywords on the same
// line (left-col and right-col merged).
const COLUMN_GARBLE_RE = /[@+]\S+.*(?:experience|education|skills|work|employment)/i

// ─── Section detection ────────────────────────────────────────────────────────

const SECTION_PATTERNS: Array<{ label: string; re: RegExp }> = [
  { label: 'Contact Info',   re: /\b(email|phone|linkedin|github|@[^\s]+)\b/i },
  { label: 'Experience',     re: /\b(experience|employment|work history)\b/i },
  { label: 'Education',      re: /\b(education|university|college|degree|bachelor|master|phd)\b/i },
  { label: 'Skills',         re: /\b(skills|technologies|proficiencies|languages)\b/i },
  { label: 'Projects',       re: /\b(projects?|open.?source)\b/i },
  { label: 'Summary',        re: /\b(summary|objective|profile|about)\b/i },
]

function detectSections(text: string): string[] {
  return SECTION_PATTERNS.filter(({ re }) => re.test(text)).map(({ label }) => label)
}

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

  const hasLigatureGarbling = LIGATURE_RE.test(extractedText)
  const hasColumnGarbling = COLUMN_GARBLE_RE.test(extractedText)
  const detectedSections = detectSections(extractedText)
  const hasIssues = hasLigatureGarbling || hasColumnGarbling

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
          {hasLigatureGarbling && (
            <DiagnosticRow
              level="warning"
              message="Unicode ligature characters detected (ﬁ, ﬀ, ﬂ). Add \input{glyphtounicode} to your preamble — the Linter tab shows the fix."
            />
          )}
          {hasColumnGarbling && (
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

        {/* ── Sections found ── */}
        {detectedSections.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {detectedSections.map((s) => (
              <span
                key={s}
                className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-medium text-emerald-400"
              >
                {s}
              </span>
            ))}
            {SECTION_PATTERNS
              .filter(({ label }) => !detectedSections.includes(label))
              .map(({ label }) => (
                <span
                  key={label}
                  className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[9px] text-zinc-600"
                >
                  {label}
                </span>
              ))}
          </div>
        )}
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
