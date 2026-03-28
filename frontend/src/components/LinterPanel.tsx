'use client'

import { AlertTriangle, Info, Wrench, Zap, CheckCircle } from 'lucide-react'
import type { LintIssue } from '@/lib/latex-linter'

// ─── Props ────────────────────────────────────────────────────────────────────

interface LinterPanelProps {
  issues: LintIssue[]
  enabled: boolean
  onToggleEnabled: (enabled: boolean) => void
  onJumpToLine: (line: number) => void
  onApplyFix: (issue: LintIssue) => void
  onAutoFixAll: () => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function LinterPanel({
  issues,
  enabled,
  onToggleEnabled,
  onJumpToLine,
  onApplyFix,
  onAutoFixAll,
}: LinterPanelProps) {
  const warnings = issues.filter((i) => i.severity === 'warning' || i.severity === 'error')
  const infos = issues.filter((i) => i.severity === 'info')
  const fixableCount = issues.filter((i) => i.fixable).length

  return (
    <div className="flex h-full flex-col overflow-hidden">

      {/* ── Header ── */}
      <div className="shrink-0 space-y-2 border-b border-white/[0.05] p-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
            Real-time linting
          </p>
          <button
            onClick={() => onToggleEnabled(!enabled)}
            className={`relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
              enabled ? 'bg-violet-500/60' : 'bg-white/[0.08]'
            }`}
            aria-label={enabled ? 'Disable linting' : 'Enable linting'}
            role="switch"
            aria-checked={enabled}
          >
            <span
              className={`pointer-events-none inline-block h-3 w-3 translate-y-0.5 rounded-full bg-white shadow transition-transform duration-200 ${
                enabled ? 'translate-x-3.5' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        {enabled && fixableCount > 0 && (
          <button
            onClick={onAutoFixAll}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-500/15 px-3 py-1.5 text-[11px] font-medium text-violet-300 ring-1 ring-violet-500/25 transition hover:bg-violet-500/25"
          >
            <Zap size={11} />
            Auto-Fix All ({fixableCount} fixable)
          </button>
        )}
      </div>

      {/* ── Issue list ── */}
      <div className="flex-1 overflow-y-auto">
        {!enabled ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <Info size={20} className="text-zinc-700" />
            <p className="text-[11px] text-zinc-600">Linting is disabled.</p>
          </div>
        ) : issues.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <CheckCircle size={20} className="text-emerald-600" />
            <p className="text-[11px] text-zinc-500">No issues found.</p>
            <p className="text-[10px] text-zinc-700">Results update 3s after you stop typing.</p>
          </div>
        ) : (
          <div className="divide-y divide-white/[0.03]">
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

      {/* ── Footer ── */}
      {enabled && (
        <div className="shrink-0 border-t border-white/[0.04] px-3 py-2">
          <p className="text-[10px] text-zinc-700">
            {issues.length} issue{issues.length === 1 ? '' : 's'}
            {issues.length > 0 && (
              <>
                {' '}·{' '}
                <span className="text-amber-500/60">{warnings.length} warning{warnings.length === 1 ? '' : 's'}</span>
                {infos.length > 0 && (
                  <span className="text-blue-500/60 ml-1">· {infos.length} info</span>
                )}
              </>
            )}
          </p>
        </div>
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
      label: 'text-amber-400/70',
      badge: 'bg-amber-500/10 text-amber-400',
      icon: <AlertTriangle size={10} className="shrink-0 text-amber-400" />,
    },
    blue: {
      label: 'text-blue-400/70',
      badge: 'bg-blue-500/10 text-blue-400',
      icon: <Info size={10} className="shrink-0 text-blue-400" />,
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
              <p className="text-[11px] leading-snug text-zinc-300">{issue.message}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${c.badge}`}>
                  {issue.ruleId}
                </span>
                <button
                  onClick={() => onJumpToLine(issue.line)}
                  className="text-[10px] text-zinc-600 underline-offset-2 hover:text-zinc-400 hover:underline"
                >
                  line {issue.line}
                </button>
                {issue.fixable && (
                  <button
                    onClick={() => onApplyFix(issue)}
                    className="flex items-center gap-0.5 rounded bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-zinc-400 ring-1 ring-white/[0.06] transition hover:bg-violet-500/15 hover:text-violet-300 hover:ring-violet-500/25"
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
