'use client'

import { useState } from 'react'
import { FileText, Eye } from 'lucide-react'
import type { TemplateResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category colour + icon mapping                                     //
// ------------------------------------------------------------------ //

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  software_engineering: { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  finance:              { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  academic:             { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  creative:             { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  minimal:              { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  ats_safe:             { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  two_column:           { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  executive:            { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  marketing:            { bg: 'bg-accent-soft', text: 'text-accent-strong', border: 'border-accent' },
  medical:              { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  legal:                { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
  graduate:             { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' },
}

const DEFAULT_STYLE = { bg: 'bg-surface-2', text: 'text-fg-2', border: 'border-line' }

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
    <div className="group relative flex flex-col rounded-[var(--radius-lg)] border border-line bg-surface transition hover:border-line-2 hover:bg-surface-2">

      {/* Thumbnail area — aspect-ratio locked so it can never balloon in any grid/flex context */}
      <div className="relative aspect-[4/3] max-h-56 w-full shrink-0 overflow-hidden rounded-t-[var(--radius-lg)] bg-surface border-b border-line flex items-center justify-center">
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
            <FileText className="w-10 h-10 text-fg-3" />
            <span className="text-[11px] text-fg-3">LaTeX</span>
          </div>
        )}

        {/* Overlay with Preview button — visible on hover/focus */}
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--overlay)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            onClick={() => onPreview(template.id)}
            aria-label={`Preview ${template.name}`}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-xs font-medium text-fg transition hover:bg-surface focus:outline-none focus:ring-2 focus:ring-accent ring-offset-bg"
          >
            <Eye size={13} />
            Preview
          </button>
        </div>
      </div>

      {/* Card body */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="text-sm font-semibold text-fg leading-tight">{template.name}</h3>
          {template.description && (
            <p className="mt-1 text-xs text-fg-3 line-clamp-2">{template.description}</p>
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
          className="mt-auto w-full rounded-[var(--radius-md)] border border-accent bg-accent-soft py-2 text-xs font-semibold text-accent-strong transition hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Use Template
        </button>
      </div>
    </div>
  )
}
