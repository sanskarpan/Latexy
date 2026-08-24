'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Brain, X, AlertCircle, Zap, ChevronDown, TrendingUp, Tag } from 'lucide-react'
import type { ATSDeepAnalysis, ATSDeepSection } from '@/lib/event-types'
import type { ATSCategory } from '@/lib/ats-categories'
import ATSCategoryScoreCard from './ATSCategoryScoreCard'
import ATSRadarChart from './ATSRadarChart'
import ScoreHistoryChart from '@/components/ScoreHistoryChart'

const INDUSTRY_OPTIONS = [
  { key: 'generic',         label: 'General (auto-detect)' },
  { key: 'tech_saas',       label: 'Technology / SaaS' },
  { key: 'finance_banking', label: 'Finance / Banking' },
  { key: 'healthcare',      label: 'Healthcare / Clinical' },
  { key: 'consulting',      label: 'Consulting / Strategy' },
]

const MULTI_DIM_LABELS: { key: string; label: string; description: string }[] = [
  { key: 'grammar',               label: 'Grammar',          description: 'Tense consistency, punctuation & formatting' },
  { key: 'bullet_clarity',        label: 'Bullet Clarity',   description: 'Impact-led bullets with quantified achievements' },
  { key: 'section_completeness',  label: 'Sections',         description: 'Required & recommended sections present' },
  { key: 'page_density',          label: 'Page Density',     description: 'Content density relative to page length' },
  { key: 'keyword_density',       label: 'Keyword Density',  description: 'JD keyword alignment (N/A without job description)' },
]

interface DeepAnalysisPanelProps {
  isOpen: boolean
  onClose: () => void
  isLoading: boolean
  analysis: ATSDeepAnalysis | null
  error: string | null
  usesRemaining: number | null
  onRun: (industryOverride?: string) => void
  isRunning: boolean
  hideUpgradeCtas?: boolean
  resumeId?: string
  /** Rule-based multi-dimensional breakdown (#1367); shown above the LLM analysis. */
  categories?: ATSCategory[]
  /** Deep-link a finding to an editor line. */
  onJumpToLine?: (line: number) => void
  /** Quick-score grade, shown on the breakdown card. */
  quickGrade?: string | null
}

function ScoreRing({ score, size = 72 }: { score: number; size?: number }) {
  const r = 15.9
  const circumference = 2 * Math.PI * r
  const dashArray = `${(score / 100) * circumference} ${circumference}`
  const color = score >= 80 ? 'var(--ok)' : score >= 60 ? 'var(--warn)' : 'var(--err)'

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="-rotate-90" width={size} height={size} viewBox="0 0 36 36">
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--line)" strokeWidth="3" />
        <circle
          cx="18" cy="18" r={r} fill="none"
          stroke={color}
          strokeWidth="3"
          strokeDasharray={dashArray}
          strokeLinecap="round"
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center text-base font-bold"
        style={{ color }}
      >
        {Math.round(score)}
      </span>
    </div>
  )
}

function SectionCard({ section }: { section: ATSDeepSection }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-fg">{section.name}</span>
        <span className={`text-[10px] font-bold tabular-nums ${
          section.score >= 80 ? 'text-ok' :
          section.score >= 60 ? 'text-warn' : 'text-err'
        }`}>{section.score}/100</span>
      </div>

      {section.strengths.length > 0 && (
        <div className="space-y-0.5">
          {section.strengths.slice(0, 2).map((s, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
              <span className="text-[10px] text-fg-2">{s}</span>
            </div>
          ))}
        </div>
      )}

      {section.improvements.length > 0 && (
        <div className="space-y-0.5">
          {section.improvements.slice(0, 2).map((imp, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
              <span className="text-[10px] text-fg-2">{imp}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DimensionBar({ label, description, score }: { label: string; description: string; score: number }) {
  const color = score >= 80 ? 'var(--ok)' : score >= 60 ? 'var(--warn)' : 'var(--err)'
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium text-fg-2">{label}</span>
        <span className="text-[10px] font-bold tabular-nums" style={{ color }}>{Math.round(score)}</span>
      </div>
      <div className="h-1 rounded-full bg-surface-2">
        <div
          className="h-1 rounded-full transition-all duration-700"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
      <p className="text-[9px] text-fg-3">{description}</p>
    </div>
  )
}

export default function DeepAnalysisPanel({
  isOpen,
  onClose,
  isLoading,
  analysis,
  error,
  usesRemaining,
  onRun,
  isRunning,
  hideUpgradeCtas = false,
  resumeId,
  categories,
  onJumpToLine,
  quickGrade,
}: DeepAnalysisPanelProps) {
  const [historyOpen, setHistoryOpen] = useState(false)
  const [industryOverride, setIndustryOverride] = useState<string>('generic')
  const [industryDropdownOpen, setIndustryDropdownOpen] = useState(false)
  const industryTriggerRef = useRef<HTMLButtonElement>(null)
  const [mounted, setMounted] = useState(false)
  const [industryDropdownPos, setIndustryDropdownPos] = useState<{
    top?: number
    bottom?: number
    left: number
    width: number
    maxHeight: number
  } | null>(null)

  useEffect(() => { setMounted(true) }, [])

  // The industry dropdown is portaled to document.body to escape the panel's
  // overflow-y-auto scroll ancestor. Compute edge-aware fixed positioning from
  // the trigger rect (mirrors ExportDropdown).
  function openIndustryDropdown() {
    if (industryTriggerRef.current) {
      const rect = industryTriggerRef.current.getBoundingClientRect()
      const margin = 12
      const spaceBelow = window.innerHeight - rect.bottom - margin
      const spaceAbove = rect.top - margin
      if (spaceBelow < 240 && spaceAbove > spaceBelow) {
        setIndustryDropdownPos({
          bottom: window.innerHeight - rect.top + 6,
          left: rect.left,
          width: rect.width,
          maxHeight: Math.min(spaceAbove, 240),
        })
      } else {
        setIndustryDropdownPos({
          top: rect.bottom + 6,
          left: rect.left,
          width: rect.width,
          maxHeight: Math.min(spaceBelow, 240),
        })
      }
    }
    setIndustryDropdownOpen(true)
  }

  // Displayed industry label: from result or from override selection
  const displayedIndustryLabel =
    analysis?.industry_label ??
    (industryOverride !== 'generic'
      ? INDUSTRY_OPTIONS.find((o) => o.key === industryOverride)?.label
      : null)

  // ESC key to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-[var(--overlay)]"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Deep AI Analysis"
        className="fixed right-0 top-0 z-50 flex h-full w-[480px] flex-col border-l border-line bg-bg shadow-[var(--shadow-2)]"
      >
        {/* Header */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Brain size={13} className="text-accent-strong" />
            </div>
            <span className="text-sm font-semibold text-fg">Deep AI Analysis</span>
            {displayedIndustryLabel && (
              <span className="flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-medium text-accent-strong ring-1 ring-accent shrink-0">
                <Tag size={8} />
                {displayedIndustryLabel}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto pb-2">
          {/* Rule-based multi-dimensional breakdown (#1367) — always available,
              above the optional LLM deep analysis. Each finding deep-links to
              the editor line it refers to. */}
          {categories && categories.length > 0 && (
            <div className="p-4 pb-0">
              <ATSCategoryScoreCard categories={categories} onJumpToLine={onJumpToLine} grade={quickGrade} />
            </div>
          )}

          {/* Idle state */}
          {!isLoading && !analysis && !error && !isRunning && (
            <div className="space-y-5 p-5">
              <div className="rounded-[var(--radius-md)] border border-line bg-surface p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Zap size={14} className="text-accent-strong" />
                  <span className="text-sm font-semibold text-fg">AI-Powered Section Analysis</span>
                </div>
                <p className="text-[12px] leading-relaxed text-fg-3">
                  Get detailed feedback on each section of your resume from GPT-4o mini.
                  Includes scores, specific improvements, and ATS compatibility analysis.
                </p>
              </div>

              {/* Industry override selector */}
              <div className="relative">
                <button
                  ref={industryTriggerRef}
                  type="button"
                  onClick={() => (industryDropdownOpen ? setIndustryDropdownOpen(false) : openIndustryDropdown())}
                  className="flex w-full items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-left text-[11px] text-fg-2 transition hover:border-line-2 hover:bg-surface-2"
                >
                  <span className="flex items-center gap-1.5">
                    <Tag size={11} className="text-accent-strong" />
                    <span>
                      {INDUSTRY_OPTIONS.find((o) => o.key === industryOverride)?.label ?? 'General (auto-detect)'}
                    </span>
                  </span>
                  <ChevronDown size={11} className={`text-fg-3 transition-transform ${industryDropdownOpen ? 'rotate-180' : ''}`} />
                </button>
                {mounted && industryDropdownOpen && industryDropdownPos && createPortal(
                  <>
                    {/* Backdrop */}
                    <div
                      className="fixed inset-0 z-[200]"
                      onClick={() => setIndustryDropdownOpen(false)}
                    />
                    {/* Dropdown — fixed positioning so it escapes the panel's overflow-y-auto */}
                    <div
                      className="z-[201] overflow-y-auto overscroll-contain rounded-[var(--radius-md)] border border-line bg-surface py-1 shadow-[var(--shadow-2)]"
                      style={{
                        position: 'fixed',
                        top: industryDropdownPos.top,
                        bottom: industryDropdownPos.bottom,
                        left: industryDropdownPos.left,
                        width: industryDropdownPos.width,
                        maxHeight: industryDropdownPos.maxHeight,
                      }}
                    >
                      {INDUSTRY_OPTIONS.map((opt) => (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => { setIndustryOverride(opt.key); setIndustryDropdownOpen(false) }}
                          className={`flex w-full items-center px-3 py-2 text-left text-[11px] transition hover:bg-surface-2 ${
                            industryOverride === opt.key ? 'text-accent-strong' : 'text-fg-2'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </>,
                  document.body
                )}
              </div>

              {usesRemaining !== null && !hideUpgradeCtas && (
                <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-warn/20 bg-warn/[0.06] px-3 py-2">
                  <span className="text-[11px] text-warn">
                    {usesRemaining > 0
                      ? `${usesRemaining} free ${usesRemaining === 1 ? 'use' : 'uses'} remaining`
                      : 'Trial limit reached — sign in for unlimited access'}
                  </span>
                </div>
              )}

              <button
                onClick={() => onRun(industryOverride !== 'generic' ? industryOverride : undefined)}
                disabled={!hideUpgradeCtas && usesRemaining === 0}
                className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-accent py-3 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-40"
              >
                <Brain size={14} />
                Run Deep Analysis
              </button>
            </div>
          )}

          {/* Loading state */}
          {(isLoading || isRunning) && (
            <div className="flex flex-col items-center justify-center gap-4 p-8">
              <div className="relative">
                <div className="h-14 w-14 rounded-full border-2 border-accent/20" />
                <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-accent" />
                <Brain size={20} className="absolute inset-0 m-auto text-accent-strong" />
              </div>
              <div className="space-y-1 text-center">
                <p className="text-sm font-semibold text-fg">Analysing your resume…</p>
                <p className="text-[11px] text-fg-3">GPT-4o mini · section-by-section review</p>
              </div>
              {/* Skeleton cards */}
              <div className="w-full space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-[var(--radius-md)] bg-surface-2" />
                ))}
              </div>
            </div>
          )}

          {/* Error state */}
          {error && !isLoading && !isRunning && (
            <div className="space-y-4 p-5">
              <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-err/20 bg-err/[0.07] p-4">
                <AlertCircle size={15} className="mt-0.5 shrink-0 text-err" />
                <div>
                  <p className="text-sm font-semibold text-err">Analysis failed</p>
                  <p className="mt-0.5 text-[11px] text-fg-3">{error}</p>
                </div>
              </div>
              <button
                onClick={() => onRun(industryOverride !== 'generic' ? industryOverride : undefined)}
                className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent-soft py-2.5 text-sm font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110"
              >
                <Brain size={13} /> Try again
              </button>
            </div>
          )}

          {/* Results state */}
          {analysis && !isLoading && !isRunning && (
            <div className="space-y-4 p-4">
              {/* Overall score */}
              <div className="flex items-center gap-4 rounded-[var(--radius-md)] border border-line bg-surface p-4">
                <ScoreRing score={analysis.overall_score} />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-fg">Overall ATS Score</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                    {analysis.overall_feedback}
                  </p>
                </div>
              </div>

              {/* Multi-dimensional score breakdown */}
              {analysis.multi_dim_scores && Object.keys(analysis.multi_dim_scores).length > 0 && (
                <div className="space-y-3 rounded-[var(--radius-md)] border border-line bg-surface p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
                    Score Breakdown
                  </p>
                  <div className="flex justify-center">
                    <ATSRadarChart scores={analysis.multi_dim_scores} />
                  </div>
                  <div className="space-y-2.5 pt-1">
                    {MULTI_DIM_LABELS.map((dim) => {
                      const score = analysis.multi_dim_scores?.[dim.key]
                      return score !== undefined ? (
                        <DimensionBar
                          key={dim.key}
                          label={dim.label}
                          description={dim.description}
                          score={score}
                        />
                      ) : null
                    })}
                  </div>
                </div>
              )}

              {/* Sections */}
              {analysis.sections.length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
                    Section Breakdown
                  </p>
                  {analysis.sections.map((section, i) => (
                    <SectionCard key={i} section={section} />
                  ))}
                </div>
              )}

              {/* ATS compatibility */}
              {analysis.ats_compatibility && (
                <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-fg">ATS Compatibility</p>
                    <span className={`text-[10px] font-bold ${
                      analysis.ats_compatibility.score >= 80 ? 'text-ok' :
                      analysis.ats_compatibility.score >= 60 ? 'text-warn' : 'text-err'
                    }`}>{analysis.ats_compatibility.score}/100</span>
                  </div>
                  {analysis.ats_compatibility.issues.length > 0 && (
                    <div className="space-y-1">
                      {analysis.ats_compatibility.issues.map((issue, i) => (
                        <p key={i} className="text-[10px] text-fg-3">• {issue}</p>
                      ))}
                    </div>
                  )}
                  {analysis.ats_compatibility.keyword_gaps.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {analysis.ats_compatibility.keyword_gaps.slice(0, 8).map((kw, i) => (
                        <span key={i} className="rounded-[var(--radius-md)] bg-err/10 px-2 py-0.5 text-[10px] text-err ring-1 ring-err/20">
                          {kw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Job match */}
              {analysis.job_match && (
                <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-fg">Job Match</p>
                    <span className={`text-[10px] font-bold ${
                      analysis.job_match.score >= 80 ? 'text-ok' :
                      analysis.job_match.score >= 60 ? 'text-warn' : 'text-err'
                    }`}>{analysis.job_match.score}%</span>
                  </div>
                  <p className="text-[10px] text-fg-3">{analysis.job_match.recommendation}</p>
                  {analysis.job_match.missing_requirements.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {analysis.job_match.missing_requirements.slice(0, 6).map((req, i) => (
                        <span key={i} className="rounded-[var(--radius-md)] bg-warn/10 px-2 py-0.5 text-[10px] text-warn ring-1 ring-warn/20">
                          {req}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-line pt-3">
                <span className="text-[10px] text-fg-3">
                  {analysis.tokens_used.toLocaleString()} tokens · {analysis.analysis_time.toFixed(1)}s
                </span>
                <button
                  onClick={() => onRun(industryOverride !== 'generic' ? industryOverride : undefined)}
                  className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-3 py-1.5 text-[11px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110"
                >
                  <Brain size={11} /> Re-analyse
                </button>
              </div>
            </div>
          )}
          {/* Score History — always visible when resumeId is provided */}
          {resumeId && (
            <div className="border-t border-line mx-4 mt-2">
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="flex w-full items-center justify-between py-3 text-left"
              >
                <div className="flex items-center gap-2">
                  <TrendingUp size={13} className="text-accent-strong" />
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                    Score History
                  </span>
                </div>
                <ChevronDown
                  size={13}
                  className={`text-fg-3 transition-transform ${historyOpen ? 'rotate-180' : ''}`}
                />
              </button>
              {historyOpen && (
                <div className="pb-4">
                  <ScoreHistoryChart resumeId={resumeId} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
