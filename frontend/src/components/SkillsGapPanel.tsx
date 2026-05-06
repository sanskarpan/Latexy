'use client'

/**
 * Skills Gap Panel — Feature 80.
 *
 * Two-column display of current skills vs gap skills.
 * Renders the LLM markdown analysis below.
 */

import { useMemo } from 'react'
import { CheckCircle2, Target, Clock, AlertTriangle } from 'lucide-react'
import type { CareerAnalysisResponse } from '@/lib/api-client'

// ── Simple Markdown renderer (no external dep) ────────────────────────────────

function renderMarkdown(md: string) {
  const lines = md.split('\n')
  const elements: React.ReactNode[] = []
  let key = 0

  for (const line of lines) {
    if (line.startsWith('## ')) {
      elements.push(<h2 key={key++} className="mb-2 mt-4 text-[13px] font-bold text-zinc-200">{line.slice(3)}</h2>)
    } else if (line.startsWith('### ')) {
      elements.push(<h3 key={key++} className="mb-1 mt-3 text-[12px] font-semibold text-zinc-300">{line.slice(4)}</h3>)
    } else if (line.startsWith('**') && line.endsWith('**')) {
      elements.push(<p key={key++} className="mb-1 text-[11px] font-semibold text-zinc-200">{line.slice(2, -2)}</p>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={key++} className="mb-0.5 ml-3 list-disc text-[11px] text-zinc-400">
          {line.slice(2)}
        </li>
      )
    } else if (/^\d+\. /.test(line)) {
      elements.push(
        <li key={key++} className="mb-0.5 ml-3 list-decimal text-[11px] text-zinc-400">
          {line.replace(/^\d+\. /, '')}
        </li>
      )
    } else if (line.trim()) {
      elements.push(<p key={key++} className="mb-1 text-[11px] text-zinc-400">{line}</p>)
    }
  }
  return elements
}

// ── Skill chip ─────────────────────────────────────────────────────────────────

function SkillChip({
  label,
  variant,
}: {
  label: string
  variant: 'have' | 'gap'
}) {
  const cls =
    variant === 'have'
      ? 'bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20'
      : 'bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20'
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {label}
    </span>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface SkillsGapPanelProps {
  analysis: CareerAnalysisResponse
}

export default function SkillsGapPanel({ analysis }: SkillsGapPanelProps) {
  const timelineYears = analysis.timeline_months
    ? Math.round((analysis.timeline_months / 12) * 10) / 10
    : null

  const targetTitle =
    analysis.target_role?.title ?? analysis.target_role_freetext ?? 'Target Role'

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
            Career Gap Analysis
          </div>
          <div className="mt-0.5 text-[13px] font-bold text-zinc-200">
            → {targetTitle}
          </div>
        </div>
        {timelineYears !== null && (
          <div className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px]">
            <Clock size={12} className="text-zinc-600" />
            <span className="text-zinc-400">
              ~{timelineYears} yr{timelineYears !== 1 ? 's' : ''}
            </span>
          </div>
        )}
      </div>

      {/* Skills columns */}
      <div className="grid grid-cols-2 gap-4">
        {/* Skills you have */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-600">
            <CheckCircle2 size={11} />
            Skills You Have
          </div>
          <div className="flex flex-wrap gap-1">
            {analysis.current_skills.length > 0
              ? analysis.current_skills.map((s) => (
                  <SkillChip key={s} label={s} variant="have" />
                ))
              : <span className="text-[11px] text-zinc-700">Not detected</span>
            }
          </div>
        </div>

        {/* Skills to develop */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-600">
            <Target size={11} />
            Skills to Develop
          </div>
          <div className="flex flex-wrap gap-1">
            {analysis.gap_skills.length > 0
              ? analysis.gap_skills.map((s) => (
                  <SkillChip key={s} label={s} variant="gap" />
                ))
              : (
                <span className="text-[11px] text-emerald-500">
                  Already qualified!
                </span>
              )
            }
          </div>
        </div>
      </div>

      {/* LLM Analysis */}
      {analysis.llm_analysis && (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
          <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
            Career Development Plan
          </div>
          <div className="prose prose-invert max-w-none">
            {renderMarkdown(analysis.llm_analysis)}
          </div>
        </div>
      )}
    </div>
  )
}
