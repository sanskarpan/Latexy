'use client'

import { useEffect, useState } from 'react'
import { X, FileText, Code } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import type { TemplateDetailResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category label map                                                 //
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

type ViewMode = 'pdf' | 'latex'

// ------------------------------------------------------------------ //
//  Props                                                              //
// ------------------------------------------------------------------ //

interface TemplatePreviewModalProps {
  templateId: string | null
  onUse: (id: string) => void
  onClose: () => void
}

// ------------------------------------------------------------------ //
//  Component                                                          //
// ------------------------------------------------------------------ //

export default function TemplatePreviewModal({
  templateId,
  onUse,
  onClose,
}: TemplatePreviewModalProps) {
  const [template, setTemplate] = useState<TemplateDetailResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('pdf')
  const [pdfFailed, setPdfFailed] = useState(false)

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  // Fetch template detail when id changes
  useEffect(() => {
    if (!templateId) {
      setTemplate(null)
      return
    }
    setLoading(true)
    setError(null)
    setViewMode('pdf')
    setPdfFailed(false)
    apiClient
      .getTemplate(templateId)
      .then(async (tmpl) => {
        setTemplate(tmpl)
        // Probe the PDF endpoint — if 404, fall back to LaTeX view
        if (tmpl.pdf_url) {
          try {
            const res = await fetch(tmpl.pdf_url, { method: 'HEAD' })
            if (!res.ok) setPdfFailed(true)
          } catch {
            setPdfFailed(true)
          }
        } else {
          setPdfFailed(true)
        }
      })
      .catch(() => setError('Failed to load template'))
      .finally(() => setLoading(false))
  }, [templateId])

  if (!templateId) return null

  const style = template ? (CATEGORY_STYLES[template.category] ?? DEFAULT_STYLE) : DEFAULT_STYLE
  const effectiveView = (viewMode === 'pdf' && pdfFailed) ? 'latex' : viewMode

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Modal */}
      <div
        className="relative flex w-full max-w-3xl flex-col rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl h-[85vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-white/8 px-6 py-5">
          {loading ? (
            <div className="h-5 w-48 animate-pulse rounded bg-white/10" />
          ) : (
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-white leading-snug">
                {template?.name ?? '—'}
              </h2>
              {template && (
                <span className={`mt-1.5 inline-block rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] ${style.bg} ${style.text} ${style.border}`}>
                  {template.category_label}
                </span>
              )}
            </div>
          )}
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/8 hover:text-zinc-300"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {loading ? (
            <div className="flex flex-1 items-center justify-center p-12">
              <div className="flex flex-col items-center gap-3 text-zinc-500">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-700 border-t-orange-300" />
                <span className="text-sm">Loading template…</span>
              </div>
            </div>
          ) : error ? (
            <div className="flex flex-1 items-center justify-center p-12">
              <p className="text-sm text-rose-400">{error}</p>
            </div>
          ) : template ? (
            <div className="flex flex-1 overflow-hidden">
              {/* Left: metadata */}
              <div className="flex w-52 shrink-0 flex-col gap-5 border-r border-white/8 p-6">
                {template.description && (
                  <div>
                    <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-600">Description</p>
                    <p className="text-xs text-zinc-400 leading-relaxed">{template.description}</p>
                  </div>
                )}

                {template.tags.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-600">Tags</p>
                    <div className="flex flex-wrap gap-1">
                      {template.tags.map(tag => (
                        <span key={tag} className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-zinc-400">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-600">Format</p>
                  <div className="flex items-center gap-1.5 text-xs text-zinc-400">
                    <FileText size={12} />
                    LaTeX (pdflatex)
                  </div>
                </div>
              </div>

              {/* Right: preview area with toggle */}
              <div className="flex flex-1 flex-col overflow-hidden">
                {/* View mode toggle */}
                <div className="flex items-center gap-1 border-b border-white/8 px-4 py-2">
                  <button
                    onClick={() => setViewMode('pdf')}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                      effectiveView === 'pdf'
                        ? 'bg-white/10 text-white'
                        : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    <FileText size={12} />
                    PDF Preview
                  </button>
                  <button
                    onClick={() => setViewMode('latex')}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                      effectiveView === 'latex'
                        ? 'bg-white/10 text-white'
                        : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    <Code size={12} />
                    LaTeX Source
                  </button>
                </div>

                {/* Content */}
                {effectiveView === 'pdf' && template.pdf_url ? (
                  <iframe
                    src={`${template.pdf_url}#toolbar=0&navpanes=0`}
                    title={`${template.name} PDF preview`}
                    className="flex-1 w-full bg-white"
                    onError={() => setPdfFailed(true)}
                  />
                ) : (
                  <div className="flex-1 overflow-auto bg-zinc-900/60 p-4">
                    <pre className="text-[11px] leading-relaxed text-zinc-400 whitespace-pre-wrap break-all">
                      {template.latex_content}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        {!loading && !error && template && (
          <div className="flex items-center justify-end gap-3 border-t border-white/8 px-6 py-4">
            <button
              onClick={onClose}
              className="rounded-lg border border-white/10 px-4 py-2 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:text-zinc-200"
            >
              Cancel
            </button>
            <button
              onClick={() => { onUse(template.id); onClose() }}
              className="btn-accent px-6 py-2 text-xs font-semibold"
            >
              Use This Template
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
