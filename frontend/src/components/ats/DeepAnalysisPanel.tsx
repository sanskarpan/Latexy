'use client'

import { useEffect, useRef, useState } from 'react'
import { Brain, X, AlertCircle, Zap, ChevronDown, TrendingUp, Tag } from 'lucide-react'
import type { ATSDeepAnalysis, ATSDeepSection } from '@/lib/event-types'
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
}

function ScoreRing({ score, size = 72 }: { score: number; size?: number }) {
  const r = 15.9
  const circumference = 2 * Math.PI * r
  const dashArray = `${(score / 100) * circumference} ${circumference}`
  const color = score >= 80 ? '#34d399' : score >= 60 ? '#f59e0b' : '#f87171'

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="-rotate-90" width={size} height={size} viewBox="0 0 36 36">
        <circle cx="18" cy="18" r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="3" />
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
    <div className="rounded-xl border border-white/[0.06] bg-black/30 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-zinc-200">{section.name}</span>
        <span className={`text-[10px] font-bold tabular-nums ${
          section.score >= 80 ? 'text-emerald-400' :
          section.score >= 60 ? 'text-amber-400' : 'text-rose-400'
        }`}>{section.score}/100</span>
      </div>

      {section.strengths.length > 0 && (
        <div className="space-y-0.5">
          {section.strengths.slice(0, 2).map((s, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
              <span className="text-[10px] text-zinc-400">{s}</span>
            </div>
          ))}
        </div>
      )}

      {section.improvements.length > 0 && (
        <div className="space-y-0.5">
          {section.improvements.slice(0, 2).map((imp, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
              <span className="text-[10px] text-zinc-400">{imp}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DimensionBar({ label, description, score }: { label: string; description: string; score: number }) {
  const color = score >= 80 ? '#34d399' : score >= 60 ? '#f59e0b' : '#f87171'
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium text-zinc-300">{label}</span>
        <span className="text-[10px] font-bold tabular-nums" style={{ color }}>{Math.round(score)}</span>
      </div>
      <div className="h-1 rounded-full bg-white/[0.05]">
        <div
          className="h-1 rounded-full transition-all duration-700"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
      <p className="text-[9px] text-zinc-600">{description}</p>
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
}: DeepAnalysisPanelProps) {
  const [historyOpen, setHistoryOpen] = useState(false)
  const [industryOverride, setIndustryOverride] = useState<string>('generic')
  const [industryDropdownOpen, setIndustryDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIndustryDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

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
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Deep AI Analysis"
        className="fixed right-0 top-0 z-50 flex h-full w-[480px] flex-col border-l border-white/[0.07] bg-[#0d0d0d] shadow-2xl"
      >
        {/* Header */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.07] px-4">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-violet-500/20">
              <Brain size={13} className="text-violet-300" />
            </div>
            <span className="text-sm font-semibold text-zinc-100">Deep AI Analysis</span>
            {displayedIndustryLabel && (
              <span className="flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-400/20 shrink-0">
                <Tag size={8} />
                {displayedIndustryLabel}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1.5 text-zinc-600 transition hover:bg-white/[0.05] hover:text-zinc-200"
          >
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto pb-2">
          {/* Idle state */}
          {!isLoading && !analysis && !error && !isRunning && (
            <div className="space-y-5 p-5">
              <div className="rounded-xl border border-white/[0.06] bg-black/30 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Zap size={14} className="text-violet-300" />
                  <span className="text-sm font-semibold text-zinc-200">AI-Powered Section Analysis</span>
                </div>
                <p className="text-[12px] leading-relaxed text-zinc-500">
                  Get detailed feedback on each section of your resume from GPT-4o mini.
                  Includes scores, specific improvements, and ATS compatibility analysis.
                </p>
              </div>

              {/* Industry override selector */}
              <div ref={dropdownRef} className="relative">
                <button
                  type="button"
                  onClick={() => setIndustryDropdownOpen((v) => !v)}
                  className="flex w-full items-center justify-between rounded-lg border border-white/[0.07] bg-white/[0.03] px-3 py-2 text-left text-[11px] text-zinc-400 transition hover:border-white/[0.12] hover:bg-white/[0.05]"
                >
                  <span className="flex items-center gap-1.5">
                    <Tag size={11} className="text-violet-400/70" />
                    <span>
                      {INDUSTRY_OPTIONS.find((o) => o.key === industryOverride)?.label ?? 'General (auto-detect)'}
                    </span>
                  </span>
                  <ChevronDown size={11} className={`text-zinc-600 transition-transform ${industryDropdownOpen ? 'rotate-180' : ''}`} />
                </button>
                {industryDropdownOpen && (
                  <div className="absolute left-0 right-0 top-full z-10 mt-1 rounded-lg border border-white/[0.08] bg-[#111] py-1 shadow-xl">
                    {INDUSTRY_OPTIONS.map((opt) => (
                      <button
                        key={opt.key}
                        type="button"
                        onClick={() => { setIndustryOverride(opt.key); setIndustryDropdownOpen(false) }}
                        className={`flex w-full items-center px-3 py-2 text-left text-[11px] transition hover:bg-white/[0.05] ${
                          industryOverride === opt.key ? 'text-violet-300' : 'text-zinc-400'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {usesRemaining !== null && !hideUpgradeCtas && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-400/20 bg-amber-500/[0.06] px-3 py-2">
                  <span className="text-[11px] text-amber-300">
                    {usesRemaining > 0
                      ? `${usesRemaining} free ${usesRemaining === 1 ? 'use' : 'uses'} remaining`
                      : 'Trial limit reached — sign in for unlimited access'}
                  </span>
                </div>
              )}

              <button
                onClick={() => onRun(industryOverride !== 'generic' ? industryOverride : undefined)}
                disabled={!hideUpgradeCtas && usesRemaining === 0}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600/80 to-violet-500/60 py-3 text-sm font-semibold text-white ring-1 ring-violet-400/20 transition hover:from-violet-600 hover:to-violet-500/80 disabled:opacity-40"
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
                <div className="h-14 w-14 rounded-full border-2 border-violet-400/20" />
                <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-violet-400" />
                <Brain size={20} className="absolute inset-0 m-auto text-violet-400" />
              </div>
              <div className="space-y-1 text-center">
                <p className="text-sm font-semibold text-zinc-200">Analysing your resume…</p>
                <p className="text-[11px] text-zinc-600">GPT-4o mini · section-by-section review</p>
              </div>
              {/* Skeleton cards */}
              <div className="w-full space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-xl bg-white/[0.03]" />
                ))}
              </div>
            </div>
          )}

          {/* Error state */}
          {error && !isLoading && !isRunning && (
            <div className="space-y-4 p-5">
              <div className="flex items-start gap-3 rounded-xl border border-rose-400/20 bg-rose-500/[0.07] p-4">
                <AlertCircle size={15} className="mt-0.5 shrink-0 text-rose-400" />
                <div>
                  <p className="text-sm font-semibold text-rose-300">Analysis failed</p>
                  <p className="mt-0.5 text-[11px] text-zinc-500">{error}</p>
                </div>
              </div>
              <button
                onClick={onRun}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-500/20 py-2.5 text-sm font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
              >
                <Brain size={13} /> Try again
              </button>
            </div>
          )}

          {/* Results state */}
          {analysis && !isLoading && !isRunning && (
            <div className="space-y-4 p-4">
              {/* Overall score */}
              <div className="flex items-center gap-4 rounded-xl border border-white/[0.06] bg-black/40 p-4">
                <ScoreRing score={analysis.overall_score} />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-zinc-200">Overall ATS Score</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                    {analysis.overall_feedback}
                  </p>
                </div>
              </div>

              {/* Multi-dimensional score breakdown */}
              {analysis.multi_dim_scores && Object.keys(analysis.multi_dim_scores).length > 0 && (
                <div className="space-y-3 rounded-xl border border-white/[0.06] bg-black/30 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
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
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
                    Section Breakdown
                  </p>
                  {analysis.sections.map((section, i) => (
                    <SectionCard key={i} section={section} />
                  ))}
                </div>
              )}

              {/* ATS compatibility */}
              {analysis.ats_compatibility && (
                <div className="rounded-xl border border-white/[0.06] bg-black/30 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-zinc-200">ATS Compatibility</p>
                    <span className={`text-[10px] font-bold ${
                      analysis.ats_compatibility.score >= 80 ? 'text-emerald-400' :
                      analysis.ats_compatibility.score >= 60 ? 'text-amber-400' : 'text-rose-400'
                    }`}>{analysis.ats_compatibility.score}/100</span>
                  </div>
                  {analysis.ats_compatibility.issues.length > 0 && (
                    <div className="space-y-1">
                      {analysis.ats_compatibility.issues.map((issue, i) => (
                        <p key={i} className="text-[10px] text-zinc-500">• {issue}</p>
                      ))}
                    </div>
                  )}
                  {analysis.ats_compatibility.keyword_gaps.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {analysis.ats_compatibility.keyword_gaps.slice(0, 8).map((kw, i) => (
                        <span key={i} className="rounded-md bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-300 ring-1 ring-rose-500/20">
                          {kw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Job match */}
              {analysis.job_match && (
                <div className="rounded-xl border border-white/[0.06] bg-black/30 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-zinc-200">Job Match</p>
                    <span className={`text-[10px] font-bold ${
                      analysis.job_match.score >= 80 ? 'text-emerald-400' :
                      analysis.job_match.score >= 60 ? 'text-amber-400' : 'text-rose-400'
                    }`}>{analysis.job_match.score}%</span>
                  </div>
                  <p className="text-[10px] text-zinc-500">{analysis.job_match.recommendation}</p>
                  {analysis.job_match.missing_requirements.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {analysis.job_match.missing_requirements.slice(0, 6).map((req, i) => (
                        <span key={i} className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300 ring-1 ring-amber-500/20">
                          {req}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-white/[0.05] pt-3">
                <span className="text-[10px] text-zinc-700">
                  {analysis.tokens_used.toLocaleString()} tokens · {analysis.analysis_time.toFixed(1)}s
                </span>
                <button
                  onClick={() => onRun(industryOverride !== 'generic' ? industryOverride : undefined)}
                  className="flex items-center gap-1.5 rounded-lg bg-violet-500/15 px-3 py-1.5 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/25"
                >
                  <Brain size={11} /> Re-analyse
                </button>
              </div>
            </div>
          )}
          {/* Score History — always visible when resumeId is provided */}
          {resumeId && (
            <div className="border-t border-white/[0.06] mx-4 mt-2">
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="flex w-full items-center justify-between py-3 text-left"
              >
                <div className="flex items-center gap-2">
                  <TrendingUp size={13} className="text-orange-300/70" />
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                    Score History
                  </span>
                </div>
                <ChevronDown
                  size={13}
                  className={`text-zinc-600 transition-transform ${historyOpen ? 'rotate-180' : ''}`}
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
