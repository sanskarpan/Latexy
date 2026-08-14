'use client'

import { useState } from 'react'
import { FileText, Eye } from 'lucide-react'
import type { TemplateResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category colour + icon mapping                                     //
// ------------------------------------------------------------------ //

// All categories render the same neutral badge — no category is semantically
// more important than another, so none gets a special accent treatment.
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
  const style = DEFAULT_STYLE
  const [imgFailed, setImgFailed] = useState(false)

  return (
    <div className="group relative flex flex-col rounded-[var(--radius-lg)] border border-line bg-surface transition hover:border-line-2 hover:bg-surface-2">

      {/* Thumbnail area — the whole thing is a preview trigger so it works on touch (no hover needed).
          aspect-ratio locked so it can never balloon in any grid/flex context. */}
      <button
        type="button"
        onClick={() => onPreview(template.id)}
        aria-label={`Preview ${template.name}`}
        className="group/thumb relative aspect-[4/3] max-h-56 w-full shrink-0 cursor-pointer overflow-hidden rounded-t-[var(--radius-lg)] border-b border-line bg-surface flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset"
      >
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

        {/* Preview affordance overlay — revealed on hover/focus for pointer devices, and
            always visible on coarse-pointer (touch) devices where hover doesn't exist. */}
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--overlay)] opacity-0 transition-opacity group-hover/thumb:opacity-100 group-focus-visible/thumb:opacity-100 [@media(hover:none)]:opacity-100">
          <span className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-xs font-medium text-fg">
            <Eye size={13} />
            Preview
          </span>
        </div>
      </button>

      {/* Card body */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="text-sm font-semibold leading-tight">
            <button
              type="button"
              onClick={() => onPreview(template.id)}
              className="text-left text-fg transition hover:text-accent-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)]"
            >
              {template.name}
            </button>
          </h3>
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
