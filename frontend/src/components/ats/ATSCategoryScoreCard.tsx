'use client'

/**
 * Multi-dimensional ATS score card (#1367).
 *
 * Presents the résumé's rule-based findings under the five named categories a
 * candidate recognises, each finding deep-linking to the editor line it refers
 * to. Driven by cheap signals (quick score + Textkernel simulator), so it
 * renders instantly without waiting for the LLM deep analysis.
 */

import { AlertTriangle, CheckCircle2, ChevronRight, XCircle } from 'lucide-react'
import type { ATSCategory, ATSCategoryStatus, ATSFinding } from '@/lib/ats-categories'

const STATUS_META: Record<ATSCategoryStatus, { icon: typeof CheckCircle2; cls: string; label: string }> = {
  good: { icon: CheckCircle2, cls: 'text-ok', label: 'Looks good' },
  warn: { icon: AlertTriangle, cls: 'text-warn', label: 'Needs attention' },
  fail: { icon: XCircle, cls: 'text-err', label: 'Fix before applying' },
}

const SEVERITY_DOT: Record<ATSFinding['severity'], string> = {
  high: 'bg-err',
  medium: 'bg-warn',
  low: 'bg-fg-3',
}

function FindingRow({ finding, onJumpToLine }: { finding: ATSFinding; onJumpToLine?: (line: number) => void }) {
  const jumpable = finding.line != null && !!onJumpToLine
  const content = (
    <>
      <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${SEVERITY_DOT[finding.severity]}`} aria-hidden="true" />
      <span className="min-w-0 flex-1 text-left text-[12px] leading-snug text-fg-2">
        {finding.label}
        {finding.line == null && finding.hint && (
          <span className="mt-0.5 block text-[11px] text-fg-3">{finding.hint}</span>
        )}
      </span>
      {jumpable && (
        <span className="mt-0.5 flex shrink-0 items-center gap-0.5 text-[11px] text-accent-strong">
          Line {finding.line}
          <ChevronRight size={12} />
        </span>
      )}
    </>
  )

  if (jumpable) {
    return (
      <button
        type="button"
        onClick={() => onJumpToLine!(finding.line!)}
        title={`Jump to line ${finding.line}`}
        className="flex w-full items-start gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left transition hover:bg-surface-2"
      >
        {content}
      </button>
    )
  }
  return <div className="flex w-full items-start gap-2 px-2 py-1.5">{content}</div>
}

export default function ATSCategoryScoreCard({
  categories,
  onJumpToLine,
  grade,
}: {
  categories: ATSCategory[]
  onJumpToLine?: (line: number) => void
  grade?: string | null
}) {
  const totalFindings = categories.reduce((n, c) => n + c.findings.length, 0)

  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-2">Score breakdown</h3>
        {grade && (
          <span className="rounded-[var(--radius-sm)] bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent-strong">
            Grade {grade}
          </span>
        )}
      </div>

      <ul className="divide-y divide-line">
        {categories.map((cat) => {
          const meta = STATUS_META[cat.status]
          const Icon = meta.icon
          return (
            <li key={cat.key} className="px-2 py-2">
              <div className="flex items-center gap-2 px-2">
                <Icon size={14} className={meta.cls} aria-hidden="true" />
                <span className="flex-1 text-[12px] font-medium text-fg">{cat.label}</span>
                <span className={`text-[11px] ${meta.cls}`}>
                  {cat.findings.length === 0 ? meta.label : `${cat.findings.length} to fix`}
                </span>
              </div>
              {cat.findings.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  {cat.findings.map((f) => (
                    <FindingRow key={f.id} finding={f} onJumpToLine={onJumpToLine} />
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {totalFindings === 0 && (
        <p className="px-4 pb-3 pt-1 text-[11px] text-fg-3">
          No parser or convention issues detected — your résumé is clean across all five checks.
        </p>
      )}
    </div>
  )
}
