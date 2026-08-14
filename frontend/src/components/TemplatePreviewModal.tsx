'use client'

import { useEffect, useState, useRef } from 'react'
import { X, FileText, Code, Copy, Check, Download, Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import type { TemplateDetailResponse } from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Category label map                                                 //
// ------------------------------------------------------------------ //

// Every category shares the same chip style — kept as one constant rather
// than a dead per-category lookup map.
const DEFAULT_STYLE = { bg: 'bg-accent-soft', text: 'text-accent-strong', border: 'border-accent' }

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

type ViewMode = 'pdf' | 'latex'

// ------------------------------------------------------------------ //
//  Props                                                              //
// ------------------------------------------------------------------ //

interface TemplatePreviewModalProps {
  templateId: string | null
  /** Invoked when the user commits to the template. May return a promise so the
   *  modal can show an in-flight state and only close on completion. */
  onUse: (id: string) => void | Promise<void>
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
  const [pdfFailed, setPdfFailed] = useState(false)
  const [using, setUsing] = useState(false)

  const modalRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)

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

  const downloadTex = () => {
    if (!template?.latex_content) return
    const blob = new Blob([template.latex_content], { type: 'application/x-tex' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${template.name || 'template'}.tex`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const handleUse = async () => {
    if (!template || using) return
    setUsing(true)
    try {
      await onUse(template.id)
      onClose()
    } finally {
      setUsing(false)
    }
  }

  // Open lifecycle: capture the trigger, lock body scroll, move focus into the
  // dialog, and restore focus to the trigger on close.
  useEffect(() => {
    if (!templateId) return
    triggerRef.current = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const raf = requestAnimationFrame(() => modalRef.current?.focus())
    return () => {
      cancelAnimationFrame(raf)
      document.body.style.overflow = previousOverflow
      triggerRef.current?.focus?.()
    }
  }, [templateId])

  // Keyboard handling: Escape to close, Tab trapped within the dialog.
  useEffect(() => {
    if (!templateId) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
        ).filter(el => el.offsetParent !== null || el === document.activeElement)
        if (focusables.length === 0) {
          e.preventDefault()
          modalRef.current.focus()
          return
        }
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        const active = document.activeElement
        if (e.shiftKey) {
          if (active === first || active === modalRef.current) {
            e.preventDefault()
            last.focus()
          }
        } else if (active === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [templateId, onClose])

  // Fetch template detail when id changes
  useEffect(() => {
    if (!templateId) {
      setTemplate(null)
      return
    }

    let cancelled = false

    setLoading(true)
    setError(null)
    setViewMode('pdf')
    setPdfFailed(false)

    apiClient
      .getTemplate(templateId)
      .then((tmpl) => {
        if (cancelled) return
        setTemplate(tmpl)
        // Render the PDF optimistically — an <iframe> does not require CORS, so we
        // must NOT probe pdf_url with a fetch (a cross-origin HEAD would throw and
        // wrongly hide a perfectly valid PDF). Only fall back to LaTeX when there is
        // no pdf_url at all, or when the iframe reports a real load error.
        if (!tmpl.pdf_url) setPdfFailed(true)
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load template')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [templateId])

  if (!templateId) return null

  const style = DEFAULT_STYLE
  const effectiveView = (viewMode === 'pdf' && pdfFailed) ? 'latex' : viewMode

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Modal */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="template-preview-title"
        tabIndex={-1}
        className="relative flex w-full max-w-3xl flex-col rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)] h-[85vh] focus:outline-none"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          {loading ? (
            <div className="h-5 w-48 animate-pulse rounded bg-surface-2" />
          ) : (
            <div className="min-w-0">
              <h2 id="template-preview-title" className="text-lg font-semibold text-fg leading-snug">
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
            <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
              {/* Metadata — stacks on top on mobile, sidebar on desktop */}
              <div className="flex w-full shrink-0 flex-col gap-5 border-b border-line p-6 max-h-[32vh] overflow-y-auto md:max-h-none md:w-52 md:border-b-0 md:border-r md:overflow-visible">
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
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {/* View mode toggle */}
                <div className="flex items-center gap-1 border-b border-line px-4 py-2">
                  <button
                    onClick={() => !pdfFailed && setViewMode('pdf')}
                    disabled={pdfFailed}
                    aria-disabled={pdfFailed}
                    title={pdfFailed ? 'PDF unavailable for this template' : undefined}
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
                    {pdfFailed && <span className="text-[10px] text-fg-3">(unavailable)</span>}
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
                  <div className="relative min-h-0 flex-1 overflow-hidden bg-surface">
                    <button
                      onClick={copySource}
                      className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] font-semibold text-fg-2 shadow-sm transition hover:text-fg hover:brightness-110"
                      aria-label="Copy LaTeX source"
                    >
                      {copied ? <><Check size={13} className="text-ok" /> Copied</> : <><Copy size={13} /> Copy</>}
                    </button>
                    <div className="h-full overflow-auto p-4">
                      <pre className="text-[11px] leading-relaxed text-fg-2 whitespace-pre font-mono">
                        {template.latex_content}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        {!loading && !error && template && (
          <div className="flex flex-col-reverse items-stretch gap-3 border-t border-line px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
            {/* Downloads */}
            <div className="flex items-center gap-2">
              {template.pdf_url && (
                <a
                  href={template.pdf_url}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-xs font-medium text-fg-2 transition hover:bg-surface-2 hover:text-fg"
                >
                  <Download size={13} />
                  PDF
                </a>
              )}
              {template.latex_content && (
                <button
                  onClick={downloadTex}
                  className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-xs font-medium text-fg-2 transition hover:bg-surface-2 hover:text-fg"
                >
                  <Download size={13} />
                  .tex
                </button>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={onClose}
                disabled={using}
                className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-medium text-fg transition hover:bg-surface-2 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleUse}
                disabled={using}
                aria-busy={using}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-6 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {using ? (
                  <>
                    <Loader2 size={13} className="animate-spin" />
                    Creating…
                  </>
                ) : (
                  'Use This Template'
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
