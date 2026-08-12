'use client'

import { useEffect, useState, useRef } from 'react'
import { X, FileText, Code, Copy, Check } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import type { TemplateDetailResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category label map                                                 //
// ------------------------------------------------------------------ //

const ACCENT_CHIP = { bg: 'bg-accent-soft', text: 'text-accent-strong', border: 'border-accent' }

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  software_engineering: ACCENT_CHIP,
  finance:              ACCENT_CHIP,
  academic:             ACCENT_CHIP,
  creative:             ACCENT_CHIP,
  minimal:              ACCENT_CHIP,
  ats_safe:             ACCENT_CHIP,
  two_column:           ACCENT_CHIP,
  executive:            ACCENT_CHIP,
  marketing:            ACCENT_CHIP,
  medical:              ACCENT_CHIP,
  legal:                ACCENT_CHIP,
  graduate:             ACCENT_CHIP,
}

const DEFAULT_STYLE = ACCENT_CHIP

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
  const [copied, setCopied] = useState(false)

  const copySource = async () => {
    if (!template?.latex_content) return
    try {
      await navigator.clipboard.writeText(template.latex_content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard unavailable */
    }
  }
  const [pdfFailed, setPdfFailed] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

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
    // Abort any in-flight request
    abortRef.current?.abort()

    if (!templateId) {
      setTemplate(null)
      return
    }

    const controller = new AbortController()
    abortRef.current = controller
    let cancelled = false

    setLoading(true)
    setError(null)
    setViewMode('pdf')
    setPdfFailed(false)

    apiClient
      .getTemplate(templateId)
      .then(async (tmpl) => {
        if (cancelled) return
        setTemplate(tmpl)
        // Probe the PDF endpoint — if 404, fall back to LaTeX view
        if (tmpl.pdf_url) {
          try {
            const res = await fetch(tmpl.pdf_url, { method: 'HEAD', signal: controller.signal })
            if (!res.ok && !cancelled) setPdfFailed(true)
          } catch {
            if (!cancelled) setPdfFailed(true)
          }
        } else {
          setPdfFailed(true)
        }
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load template')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [templateId])

  if (!templateId) return null

  const style = template ? (CATEGORY_STYLES[template.category] ?? DEFAULT_STYLE) : DEFAULT_STYLE
  const effectiveView = (viewMode === 'pdf' && pdfFailed) ? 'latex' : viewMode

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Modal */}
      <div
        className="relative flex w-full max-w-3xl flex-col rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)] h-[85vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          {loading ? (
            <div className="h-5 w-48 animate-pulse rounded bg-surface-2" />
          ) : (
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-fg leading-snug">
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
            aria-label="Close preview"
            className="shrink-0 rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {loading ? (
            <div className="flex flex-1 items-center justify-center p-12">
              <div className="flex flex-col items-center gap-3 text-fg-3">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />
                <span className="text-sm">Loading template…</span>
              </div>
            </div>
          ) : error ? (
            <div className="flex flex-1 items-center justify-center p-12">
              <p className="text-sm text-err">{error}</p>
            </div>
          ) : template ? (
            <div className="flex flex-1 overflow-hidden">
              {/* Left: metadata */}
              <div className="flex w-52 shrink-0 flex-col gap-5 border-r border-line p-6">
                {template.description && (
                  <div>
                    <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-fg-3">Description</p>
                    <p className="text-xs text-fg-2 leading-relaxed">{template.description}</p>
                  </div>
                )}

                {template.tags.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-fg-3">Tags</p>
                    <div className="flex flex-wrap gap-1">
                      {template.tags.map(tag => (
                        <span key={tag} className="rounded-[var(--radius-md)] bg-surface-2 px-2 py-0.5 text-[10px] text-fg-2">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-fg-3">Format</p>
                  <div className="flex items-center gap-1.5 text-xs text-fg-2">
                    <FileText size={12} />
                    LaTeX (pdflatex)
                  </div>
                </div>
              </div>

              {/* Right: preview area with toggle */}
              <div className="flex flex-1 flex-col overflow-hidden">
                {/* View mode toggle */}
                <div className="flex items-center gap-1 border-b border-line px-4 py-2">
                  <button
                    onClick={() => !pdfFailed && setViewMode('pdf')}
                    disabled={pdfFailed}
                    className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-medium transition ${
                      effectiveView === 'pdf'
                        ? 'bg-surface-2 text-fg'
                        : pdfFailed
                        ? 'text-fg-3 cursor-not-allowed'
                        : 'text-fg-3 hover:text-fg-2'
                    }`}
                  >
                    <FileText size={12} />
                    PDF Preview
                  </button>
                  <button
                    onClick={() => setViewMode('latex')}
                    className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-medium transition ${
                      effectiveView === 'latex'
                        ? 'bg-surface-2 text-fg'
                        : 'text-fg-3 hover:text-fg-2'
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
                  <div className="relative flex-1 overflow-auto bg-surface p-4">
                    <button
                      onClick={copySource}
                      className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] font-semibold text-fg-2 shadow-sm transition hover:text-fg hover:brightness-110"
                      aria-label="Copy LaTeX source"
                    >
                      {copied ? <><Check size={13} className="text-ok" /> Copied</> : <><Copy size={13} /> Copy</>}
                    </button>
                    <pre className="text-[11px] leading-relaxed text-fg-2 whitespace-pre-wrap break-all">
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
          <div className="flex items-center justify-end gap-3 border-t border-line px-6 py-4">
            <button
              onClick={onClose}
              className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-medium text-fg transition hover:bg-surface-2"
            >
              Cancel
            </button>
            <button
              onClick={() => { onUse(template.id); onClose() }}
              className="rounded-[var(--radius-md)] bg-accent px-6 py-2 text-xs font-semibold text-accent-fg hover:brightness-110"
            >
              Use This Template
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
