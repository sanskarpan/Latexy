'use client'

import { useState } from 'react'
import { AlertTriangle, Info, Wrench, Zap, CheckCircle, FileText } from 'lucide-react'
import type { LintIssue } from '@/lib/latex-linter'
import ATSTextView from '@/components/ATSTextView'

// ─── Props ────────────────────────────────────────────────────────────────────

interface LinterPanelProps {
  issues: LintIssue[]
  enabled: boolean
  onToggleEnabled: (enabled: boolean) => void
  onJumpToLine: (line: number) => void
  onApplyFix: (issue: LintIssue) => void
  onAutoFixAll: () => void
  /** Plain text extracted from the compiled PDF by pdftotext (ATS pre-flight Layer 2) */
  extractedPdfText?: string | null
  pageCount?: number | null
}

// ─── Component ────────────────────────────────────────────────────────────────

type LinterView = 'issues' | 'ats-text'

export default function LinterPanel({
  issues,
  enabled,
  onToggleEnabled,
  onJumpToLine,
  onApplyFix,
  onAutoFixAll,
  extractedPdfText,
  pageCount,
}: LinterPanelProps) {
  const [view, setView] = useState<LinterView>('issues')

  const warnings = issues.filter((i) => i.severity === 'warning' || i.severity === 'error')
  const infos = issues.filter((i) => i.severity === 'info')
  const fixableCount = issues.filter((i) => i.fixable).length

  return (
    <div className="flex h-full flex-col overflow-hidden">

      {/* ── Header ── */}
      <div className="shrink-0 space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          {/* Sub-tab toggle */}
          <div className="flex items-center gap-0.5 rounded-[var(--radius-md)] bg-surface-2 p-0.5">
            <button
              onClick={() => setView('issues')}
              className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium transition ${
                view === 'issues' ? 'bg-surface-2 text-fg' : 'text-fg-3 hover:text-fg-2'
              }`}
            >
              <AlertTriangle size={9} />
              Issues
              {issues.length > 0 && (
                <span className="rounded bg-warn/20 px-1 font-mono text-[8px] text-warn">
                  {issues.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setView('ats-text')}
              className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium transition ${
                view === 'ats-text' ? 'bg-surface-2 text-fg' : 'text-fg-3 hover:text-fg-2'
              }`}
            >
              <FileText size={9} />
              ATS Text
              {extractedPdfText && (
                <span className="h-1.5 w-1.5 rounded-full bg-ok" />
              )}
            </button>
          </div>

          {/* Linter toggle (only relevant for Issues view) */}
          {view === 'issues' && (
            <button
              onClick={() => onToggleEnabled(!enabled)}
              className={`relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
                enabled ? 'bg-accent' : 'bg-surface-2'
              }`}
              aria-label={enabled ? 'Disable linting' : 'Enable linting'}
              role="switch"
              aria-checked={enabled}
            >
              <span
                className={`pointer-events-none inline-block h-3 w-3 translate-y-0.5 rounded-full bg-fg shadow transition-transform duration-200 ${
                  enabled ? 'translate-x-3.5' : 'translate-x-0.5'
                }`}
              />
            </button>
          )}
        </div>

        {view === 'issues' && enabled && fixableCount > 0 && (
          <button
            onClick={onAutoFixAll}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-3 py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110"
          >
            <Zap size={11} />
            Auto-Fix All ({fixableCount} fixable)
          </button>
        )}
      </div>

      {/* ── ATS Text View ── */}
      {view === 'ats-text' && (
        <div className="min-h-0 flex-1 overflow-hidden">
          <ATSTextView extractedText={extractedPdfText ?? null} pageCount={pageCount} />
        </div>
      )}

      {/* ── Issue list + footer (issues view only) ── */}
      {view === 'issues' && (
        <>
          <div className="flex-1 overflow-y-auto">
            {!enabled ? (
              <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
                <Info size={20} className="text-fg-3" />
                <p className="text-[11px] text-fg-3">Linting is disabled.</p>
              </div>
            ) : issues.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
                <CheckCircle size={20} className="text-ok" />
                <p className="text-[11px] text-fg-3">No issues found.</p>
                <p className="text-[10px] text-fg-3">Results update 3s after you stop typing.</p>
              </div>
            ) : (
              <div className="divide-y divide-line">
                {warnings.length > 0 && (
                  <IssueGroup
                    label="Warnings"
                    issues={warnings}
                    color="amber"
                    onJumpToLine={onJumpToLine}
                    onApplyFix={onApplyFix}
                  />
                )}
                {infos.length > 0 && (
                  <IssueGroup
                    label="Info"
                    issues={infos}
                    color="blue"
                    onJumpToLine={onJumpToLine}
                    onApplyFix={onApplyFix}
                  />
                )}
              </div>
            )}
          </div>

          {enabled && (
            <div className="shrink-0 border-t border-line px-3 py-2">
              <p className="text-[10px] text-fg-3">
                {issues.length} issue{issues.length === 1 ? '' : 's'}
                {issues.length > 0 && (
                  <>
                    {' '}·{' '}
                    <span className="text-warn">{warnings.length} warning{warnings.length === 1 ? '' : 's'}</span>
                    {infos.length > 0 && (
                      <span className="text-fg-3 ml-1">· {infos.length} info</span>
                    )}
                  </>
                )}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── IssueGroup ───────────────────────────────────────────────────────────────

function IssueGroup({
  label,
  issues,
  color,
  onJumpToLine,
  onApplyFix,
}: {
  label: string
  issues: LintIssue[]
  color: 'amber' | 'blue'
  onJumpToLine: (line: number) => void
  onApplyFix: (issue: LintIssue) => void
}) {
  const colorMap = {
    amber: {
      label: 'text-warn',
      badge: 'bg-warn/10 text-warn',
      icon: <AlertTriangle size={10} className="shrink-0 text-warn" />,
    },
    blue: {
      label: 'text-fg-3',
      badge: 'bg-surface-2 text-fg-2',
      icon: <Info size={10} className="shrink-0 text-fg-2" />,
    },
  }

  const c = colorMap[color]

  return (
    <div className="py-1">
      <p className={`px-3 py-1 text-[9px] font-semibold uppercase tracking-[0.14em] ${c.label}`}>
        {label} ({issues.length})
      </p>
      {issues.map((issue, idx) => (
        <div key={`${issue.ruleId}-${issue.line}-${issue.column}-${idx}`} className="px-3 py-2">
          <div className="flex items-start gap-2">
            <div className="mt-0.5">{c.icon}</div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] leading-snug text-fg-2">{issue.message}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${c.badge}`}>
                  {issue.ruleId}
                </span>
                <button
                  onClick={() => onJumpToLine(issue.line)}
                  className="text-[10px] text-fg-3 underline-offset-2 hover:text-fg-2 hover:underline"
                >
                  line {issue.line}
                </button>
                {issue.fixable && (
                  <button
                    onClick={() => onApplyFix(issue)}
                    className="flex items-center gap-0.5 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-2 ring-1 ring-line transition hover:bg-accent-soft hover:text-accent-strong hover:ring-accent"
                  >
                    <Wrench size={8} />
                    Fix
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
