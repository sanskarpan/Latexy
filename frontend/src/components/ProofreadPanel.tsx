'use client'

import { useCallback, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Sparkles,
  Wand2,
  X,
} from 'lucide-react'
import { apiClient, type ProofreadIssue, type ProofreadResponse } from '@/lib/api-client'

// ── Constants ────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  weak_verb: 'Weak Verbs',
  passive_voice: 'Passive Voice',
  buzzword: 'Buzzwords',
  vague: 'Vague Language',
}

const CATEGORY_COLORS: Record<string, string> = {
  weak_verb: 'text-amber-400',
  passive_voice: 'text-blue-400',
  buzzword: 'text-violet-400',
  vague: 'text-rose-400',
}

const CATEGORY_BG: Record<string, string> = {
  weak_verb: 'bg-amber-500/10',
  passive_voice: 'bg-blue-500/10',
  buzzword: 'bg-violet-500/10',
  vague: 'bg-rose-500/10',
}

// ── Types ────────────────────────────────────────────────────────────────────

interface ProofreadPanelProps {
  resumeLatex: string
  /** Called with one issue to apply a single fix */
  onApplyFix: (issue: ProofreadIssue) => void
  /** Called with all fixable issues for bulk auto-fix */
  onApplyAllFixes: (issues: ProofreadIssue[]) => void
  /** Called after proofread completes so parent can update Monaco decorations */
  onProofreadComplete?: (issues: ProofreadIssue[]) => void
}

// ── Helper ───────────────────────────────────────────────────────────────────

function issueId(issue: ProofreadIssue): string {
  return `${issue.line}:${issue.column_start}:${issue.original_text}`
}

function scoreColor(score: number): string {
  if (score >= 80) return 'text-emerald-400'
  if (score >= 60) return 'text-amber-400'
  return 'text-rose-400'
}

function scoreBg(score: number): string {
  if (score >= 80) return 'border-emerald-400/30 bg-emerald-500/10'
  if (score >= 60) return 'border-amber-400/30 bg-amber-500/10'
  return 'border-rose-400/30 bg-rose-500/10'
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ProofreadPanel({
  resumeLatex,
  onApplyFix,
  onApplyAllFixes,
  onProofreadComplete,
}: ProofreadPanelProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<ProofreadResponse | null>(null)
  const [ignoredIds, setIgnoredIds] = useState<Set<string>>(new Set())
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(Object.keys(CATEGORY_LABELS))
  )

  const handleRunProofread = useCallback(async () => {
    if (isLoading || !resumeLatex.trim()) return
    setIsLoading(true)
    setIgnoredIds(new Set())
    try {
      const res = await apiClient.proofreadResume(resumeLatex)
      setResult(res)
      onProofreadComplete?.(res.issues)
    } catch {
      // silently fail — no API key, network, etc.
    } finally {
      setIsLoading(false)
    }
  }, [isLoading, resumeLatex, onProofreadComplete])

  const toggleCategory = useCallback((cat: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }, [])

  const ignoreIssue = useCallback((issue: ProofreadIssue) => {
    setIgnoredIds(prev => new Set([...prev, issueId(issue)]))
  }, [])

  // Derive active (non-ignored) issues
  const activeIssues = result?.issues.filter(i => !ignoredIds.has(issueId(i))) ?? []
  const byCategory = activeIssues.reduce<Record<string, ProofreadIssue[]>>((acc, issue) => {
    ;(acc[issue.category] ??= []).push(issue)
    return acc
  }, {})
  const safeFixIssues = activeIssues.filter(i => i.suggested_text)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Header / Run button ── */}
      <div className="shrink-0 space-y-3 border-b border-white/[0.05] p-4">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
            Writing Quality
          </span>
          {result && (
            <span
              className={`rounded-md border px-2 py-0.5 text-[11px] font-bold tabular-nums ${scoreBg(result.overall_score)} ${scoreColor(result.overall_score)}`}
            >
              {result.overall_score}/100
            </span>
          )}
        </div>

        <button
          onClick={handleRunProofread}
          disabled={isLoading}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-500/20 py-2.5 text-[12px] font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30 disabled:opacity-40"
        >
          {isLoading ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              Analyzing writing quality…
            </>
          ) : (
            <>
              <Sparkles size={13} />
              {result ? 'Re-run Proofreader' : 'Run Proofreader'}
            </>
          )}
        </button>
      </div>

      {/* ── Results ── */}
      {result && !isLoading && (
        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {/* Category summary chips */}
          {Object.entries(result.summary).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(result.summary).map(([cat, count]) => (
                <span
                  key={cat}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${CATEGORY_COLORS[cat] ?? 'text-zinc-400'} ${CATEGORY_BG[cat] ?? 'bg-white/[0.04]'}`}
                >
                  {count} {(CATEGORY_LABELS[cat] ?? cat).toLowerCase()}
                </span>
              ))}
            </div>
          )}

          {/* Clean state */}
          {activeIssues.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-8">
              <CheckCircle2 size={24} className="text-emerald-400" />
              <p className="text-center text-[11px] text-zinc-500">
                {result.issues.length === 0
                  ? 'No writing issues found. Excellent work!'
                  : 'All issues resolved or ignored.'}
              </p>
            </div>
          )}

          {/* Auto-fix all button */}
          {safeFixIssues.length > 0 && (
            <button
              onClick={() => {
                onApplyAllFixes(safeFixIssues)
                setIgnoredIds(prev => {
                  const next = new Set(prev)
                  safeFixIssues.forEach(i => next.add(issueId(i)))
                  return next
                })
              }}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.07] py-2 text-[11px] font-semibold text-emerald-300 transition hover:bg-emerald-500/10"
            >
              <Wand2 size={12} />
              Auto-fix {safeFixIssues.length} safe issue
              {safeFixIssues.length === 1 ? '' : 's'}
            </button>
          )}

          {/* Issues grouped by category */}
          {Object.entries(byCategory).map(([category, issues]) => (
            <div key={category}>
              {/* Category header */}
              <button
                onClick={() => toggleCategory(category)}
                className="flex w-full items-center gap-2 py-1 text-left"
              >
                {expandedCategories.has(category) ? (
                  <ChevronDown size={11} className="shrink-0 text-zinc-600" />
                ) : (
                  <ChevronRight size={11} className="shrink-0 text-zinc-600" />
                )}
                <span
                  className={`text-[10px] font-bold uppercase tracking-[0.1em] ${CATEGORY_COLORS[category] ?? 'text-zinc-400'}`}
                >
                  {CATEGORY_LABELS[category] ?? category}
                </span>
                <span className="ml-auto text-[10px] text-zinc-700">{issues.length}</span>
              </button>

              {/* Issue cards */}
              {expandedCategories.has(category) && (
                <div className="mt-1 space-y-1.5">
                  {issues.map(issue => (
                    <div
                      key={issueId(issue)}
                      className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5"
                    >
                      {/* Top row: line number + ignore */}
                      <div className="mb-1.5 flex items-center justify-between">
                        <span className="text-[10px] text-zinc-600">Line {issue.line}</span>
                        <button
                          onClick={() => ignoreIssue(issue)}
                          title="Ignore this issue"
                          className="rounded p-0.5 text-zinc-700 transition hover:bg-white/[0.06] hover:text-zinc-400"
                        >
                          <X size={10} />
                        </button>
                      </div>

                      {/* Offending text */}
                      <p className="mb-1 font-mono text-[11px] text-amber-300/80">
                        &quot;{issue.original_text}&quot;
                      </p>

                      {/* Message */}
                      <p className="mb-2 text-[10px] leading-relaxed text-zinc-500">
                        {issue.message}
                      </p>

                      {/* Apply fix button */}
                      {issue.suggested_text && (
                        <button
                          onClick={() => {
                            onApplyFix(issue)
                            ignoreIssue(issue)
                          }}
                          className="flex items-center gap-1.5 rounded-md bg-white/[0.05] px-2 py-1 text-[10px] text-zinc-300 transition hover:bg-white/[0.08]"
                        >
                          Apply: &quot;{issue.suggested_text}&quot;
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Idle state ── */}
      {!result && !isLoading && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 pb-6 text-center">
          <AlertTriangle size={20} className="text-zinc-700" />
          <p className="text-[11px] leading-relaxed text-zinc-600">
            Scan your resume for weak verbs, passive voice, buzzwords, and vague language.
          </p>
        </div>
      )}
    </div>
  )
}
