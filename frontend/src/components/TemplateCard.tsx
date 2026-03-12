'use client'

import { useState } from 'react'
import { FileText, Eye } from 'lucide-react'
import type { TemplateResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category colour + icon mapping                                     //
// ------------------------------------------------------------------ //

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  software_engineering: { bg: 'bg-blue-500/10',    text: 'text-blue-300',    border: 'border-blue-500/20' },
  finance:              { bg: 'bg-emerald-500/10',  text: 'text-emerald-300', border: 'border-emerald-500/20' },
  academic:             { bg: 'bg-violet-500/10',   text: 'text-violet-300',  border: 'border-violet-500/20' },
  creative:             { bg: 'bg-pink-500/10',     text: 'text-pink-300',    border: 'border-pink-500/20' },
  minimal:              { bg: 'bg-zinc-500/10',     text: 'text-zinc-300',    border: 'border-zinc-500/20' },
  ats_safe:             { bg: 'bg-green-500/10',    text: 'text-green-300',   border: 'border-green-500/20' },
  two_column:           { bg: 'bg-cyan-500/10',     text: 'text-cyan-300',    border: 'border-cyan-500/20' },
  executive:            { bg: 'bg-amber-500/10',    text: 'text-amber-300',   border: 'border-amber-500/20' },
  marketing:            { bg: 'bg-orange-500/10',   text: 'text-orange-300',  border: 'border-orange-500/20' },
  medical:              { bg: 'bg-red-500/10',      text: 'text-red-300',     border: 'border-red-500/20' },
  legal:                { bg: 'bg-indigo-500/10',   text: 'text-indigo-300',  border: 'border-indigo-500/20' },
  graduate:             { bg: 'bg-teal-500/10',     text: 'text-teal-300',    border: 'border-teal-500/20' },
}

const DEFAULT_STYLE = { bg: 'bg-zinc-500/10', text: 'text-zinc-300', border: 'border-zinc-500/20' }

// ------------------------------------------------------------------ //
//  Component                                                          //
// ------------------------------------------------------------------ //

interface TemplateCardProps {
  template: TemplateResponse
  onSelect: (id: string) => void
  onPreview: (id: string) => void
  disabled?: boolean
}

export default function TemplateCard({ template, onSelect, onPreview, disabled }: TemplateCardProps) {
  const style = CATEGORY_STYLES[template.category] ?? DEFAULT_STYLE
  const [imgFailed, setImgFailed] = useState(false)

  return (
    <div className="group relative flex flex-col rounded-xl border border-white/8 bg-white/[0.02] transition hover:border-white/15 hover:bg-white/[0.04]">

      {/* Thumbnail area */}
      <div className="relative h-44 w-full overflow-hidden rounded-t-xl bg-zinc-900/60 border-b border-white/8 flex items-center justify-center">
        {template.thumbnail_url && !imgFailed ? (
          <img
            src={template.thumbnail_url}
            alt={`${template.name} preview`}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover object-top"
            onError={() => setImgFailed(true)}
          />
        ) : (
          /* Placeholder when no thumbnail yet */
          <div className="flex flex-col items-center gap-2 select-none">
            <FileText className="w-10 h-10 text-zinc-600" />
            <span className="text-[11px] text-zinc-600">LaTeX</span>
          </div>
        )}

        {/* Overlay with Preview button — visible on hover/focus */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            onClick={() => onPreview(template.id)}
            aria-label={`Preview ${template.name}`}
            className="flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-xs font-medium text-white backdrop-blur-sm transition hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-orange-300/50"
          >
            <Eye size={13} />
            Preview
          </button>
        </div>
      </div>

      {/* Card body */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100 leading-tight">{template.name}</h3>
          {template.description && (
            <p className="mt-1 text-xs text-zinc-500 line-clamp-2">{template.description}</p>
          )}
        </div>

        {/* Category badge */}
        <span className={`self-start rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] ${style.bg} ${style.text} ${style.border}`}>
          {template.category_label}
        </span>

        {/* Use Template button */}
        <button
          onClick={() => onSelect(template.id)}
          disabled={disabled}
          className="mt-auto w-full rounded-lg border border-orange-300/25 bg-orange-300/10 py-2 text-xs font-semibold text-orange-200 transition hover:bg-orange-300/20 hover:border-orange-300/40 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Use Template
        </button>
      </div>
    </div>
  )
}
