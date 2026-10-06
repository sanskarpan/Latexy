'use client'

/**
 * Skills Gap Panel — Feature 80.
 *
 * Two-column display of current skills vs gap skills.
 * Renders the LLM markdown analysis below.
 */

import { useMemo } from 'react'
import { CheckCircle2, Target, Clock, ExternalLink } from 'lucide-react'
import type { CareerAnalysisResponse } from '@/lib/api-client'

// ── Simple Markdown renderer (no external dep) ────────────────────────────────

function renderMarkdown(md: string) {
  const lines = md.split('\n')
  const elements: React.ReactNode[] = []
  let key = 0

  for (const line of lines) {
    if (line.startsWith('## ')) {
      elements.push(<h2 key={key++} className="mb-2 mt-4 text-[13px] font-bold text-fg">{line.slice(3)}</h2>)
    } else if (line.startsWith('### ')) {
      elements.push(<h3 key={key++} className="mb-1 mt-3 text-[12px] font-semibold text-fg-2">{line.slice(4)}</h3>)
    } else if (line.startsWith('**') && line.endsWith('**')) {
      elements.push(<p key={key++} className="mb-1 text-[11px] font-semibold text-fg">{line.slice(2, -2)}</p>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={key++} className="mb-0.5 ml-3 list-disc text-[11px] text-fg-2">
          {line.slice(2)}
        </li>
      )
    } else if (/^\d+\. /.test(line)) {
      elements.push(
        <li key={key++} className="mb-0.5 ml-3 list-decimal text-[11px] text-fg-2">
          {line.replace(/^\d+\. /, '')}
        </li>
      )
    } else if (line.trim()) {
      elements.push(<p key={key++} className="mb-1 text-[11px] text-fg-2">{line}</p>)
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
      ? 'bg-ok/10 text-ok ring-1 ring-ok/20'
      : 'bg-warn/10 text-warn ring-1 ring-warn/20'
  return (
    <span className={`inline-flex items-center rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {label}
    </span>
  )
}

function safeEscoHref(uri: string | null | undefined): string | null {
  const prefix = 'http://data.europa.eu/esco/skill/'
  return uri?.startsWith(prefix) ? uri.replace('http://', 'https://') : null
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
  const taxonomyMatches = useMemo(
    () => analysis.skill_taxonomy_mappings?.filter((mapping) => mapping.matched) ?? [],
    [analysis.skill_taxonomy_mappings],
  )

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
            Career Gap Analysis
          </div>
          <div className="mt-0.5 text-[13px] font-bold text-fg">
            → {targetTitle}
          </div>
        </div>
        {timelineYears !== null && (
          <div className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[11px]">
            <Clock size={12} className="text-fg-3" />
            <span className="text-fg-2">
              ~{timelineYears} yr{timelineYears !== 1 ? 's' : ''}
            </span>
          </div>
        )}
      </div>

      {analysis.skill_taxonomy && (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[10px] text-fg-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              Skills normalized with {analysis.skill_taxonomy}
              {analysis.skill_taxonomy_language ? ` (${analysis.skill_taxonomy_language})` : ''}.
              Unmatched terms remain unchanged.
            </span>
            <a
              href="https://esco.ec.europa.eu/en/classification/skill_main"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-accent-strong hover:underline"
            >
              About ESCO <ExternalLink size={10} aria-hidden="true" />
            </a>
          </div>
          {taxonomyMatches.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer font-semibold text-fg-2">
                ESCO matches ({taxonomyMatches.length})
              </summary>
              <ul className="mt-1 space-y-1">
                {taxonomyMatches.map((mapping) => (
                  <li key={`${mapping.input}:${mapping.uri ?? mapping.preferred_label}`}>
                    {safeEscoHref(mapping.uri) ? (
                      <a
                        href={safeEscoHref(mapping.uri)!}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent-strong hover:underline"
                      >
                        {mapping.input} → {mapping.preferred_label}
                      </a>
                    ) : `${mapping.input} → ${mapping.preferred_label}`}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Skills columns */}
      <div className="grid grid-cols-2 gap-4">
        {/* Skills you have */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ok">
            <CheckCircle2 size={11} />
            Skills You Have
          </div>
          <div className="flex flex-wrap gap-1">
            {analysis.current_skills.length > 0
              ? analysis.current_skills.map((s) => (
                  <SkillChip key={s} label={s} variant="have" />
                ))
              : <span className="text-[11px] text-fg-3">Not detected</span>
            }
          </div>
        </div>

        {/* Skills to develop */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-warn">
            <Target size={11} />
            Skills to Develop
          </div>
          <div className="flex flex-wrap gap-1">
            {analysis.gap_skills.length > 0
              ? analysis.gap_skills.map((s) => (
                  <SkillChip key={s} label={s} variant="gap" />
                ))
              : (
                <span className="text-[11px] text-ok">
                  Already qualified!
                </span>
              )
            }
          </div>
        </div>
      </div>

      {/* LLM Analysis */}
      {analysis.llm_analysis && (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
          <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
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
