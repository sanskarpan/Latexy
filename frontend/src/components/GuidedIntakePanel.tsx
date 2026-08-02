'use client'

import { useState } from 'react'
import { ChevronDown, SlidersHorizontal } from 'lucide-react'
import {
  SENIORITY_OPTIONS as SENIORITY,
  TONE_OPTIONS as TONE,
  intakeActiveCount,
  type GuidedIntake,
} from '@/lib/guided-intake'

/**
 * Guided-intake direction for AI optimization (input-driven optimization, PRD
 * 2026-08-02). A short, optional, progressively-disclosed set of fields that let
 * the user steer the rewrite (industry / seniority / tone / emphasize / downplay)
 * instead of having ATS heuristics forced on them. Collapsed by default with
 * sensible empty defaults — never a wall of configuration. Types and helpers
 * live in `@/lib/guided-intake` (React-free, unit tested).
 */

function TagInput({
  label,
  hint,
  values,
  onChange,
  accent,
}: {
  label: string
  hint: string
  values: string[]
  onChange: (v: string[]) => void
  accent: 'emerald' | 'zinc'
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const t = draft.trim()
    if (t && !values.includes(t)) onChange([...values, t])
    setDraft('')
  }
  const chip =
    accent === 'emerald'
      ? 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/20'
      : 'bg-white/[0.06] text-zinc-300 ring-white/10'
  return (
    <div>
      <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-400">{label}</label>
      <p className="mt-0.5 text-[10px] text-zinc-600">{hint}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {values.map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => onChange(values.filter((x) => x !== v))}
            className={`rounded-md px-2 py-0.5 text-[11px] ring-1 ${chip} transition hover:opacity-80`}
            title="Remove"
          >
            {v} ×
          </button>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            }
          }}
          onBlur={add}
          placeholder="type + Enter"
          className="min-w-[110px] flex-1 bg-transparent text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none"
        />
      </div>
    </div>
  )
}

export default function GuidedIntakePanel({
  value,
  onChange,
}: {
  value: GuidedIntake
  onChange: (v: GuidedIntake) => void
}) {
  const [open, setOpen] = useState(false)
  const set = <K extends keyof GuidedIntake>(k: K, v: GuidedIntake[K]) => onChange({ ...value, [k]: v })
  const activeCount = intakeActiveCount(value)

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-left"
      >
        <span className="flex items-center gap-2 text-xs font-semibold text-zinc-300">
          <SlidersHorizontal size={13} className="text-orange-300/80" />
          Fine-tune the AI (optional)
          {activeCount > 0 && (
            <span className="rounded-full bg-orange-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-orange-200">
              {activeCount}
            </span>
          )}
        </span>
        <ChevronDown size={14} className={`text-zinc-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="space-y-3 border-t border-white/10 px-3 py-3">
          <p className="text-[10px] text-zinc-600">
            Tell the AI what matters — it respects these over generic ATS defaults. All optional.
          </p>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-400">Industry</label>
              <input
                value={value.industry}
                onChange={(e) => set('industry', e.target.value)}
                placeholder="e.g. Fintech"
                className="mt-1 w-full rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-orange-400/40 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-400">Seniority</label>
              <select
                value={value.seniority}
                onChange={(e) => set('seniority', e.target.value)}
                className="mt-1 w-full rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-zinc-200 focus:border-orange-400/40 focus:outline-none"
              >
                <option value="">Auto</option>
                {SENIORITY.map((s) => (
                  <option key={s} value={s} className="bg-zinc-900">
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-400">Tone</label>
              <select
                value={value.tone}
                onChange={(e) => set('tone', e.target.value)}
                className="mt-1 w-full rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-zinc-200 focus:border-orange-400/40 focus:outline-none"
              >
                <option value="">Auto</option>
                {TONE.map((t) => (
                  <option key={t} value={t} className="bg-zinc-900">
                    {t}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <TagInput
              label="Emphasize"
              hint="Achievements / skills to make prominent"
              values={value.emphasize}
              onChange={(v) => set('emphasize', v)}
              accent="emerald"
            />
            <TagInput
              label="Downplay"
              hint="Keep but reduce — never deleted"
              values={value.downplay}
              onChange={(v) => set('downplay', v)}
              accent="zinc"
            />
          </div>
        </div>
      )}
    </div>
  )
}
