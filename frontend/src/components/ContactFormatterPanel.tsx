'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Loader2, Phone, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ContactChange } from '@/lib/api-client'

const TYPE_LABELS: Record<string, string> = {
  phone: 'Phone',
  linkedin: 'LinkedIn',
  github: 'GitHub',
  email: 'Email',
}

interface ContactFormatterPanelProps {
  isOpen: boolean
  onClose: () => void
  getLatex: () => string
  onApply: (newLatex: string) => void
}

export default function ContactFormatterPanel({
  isOpen,
  onClose,
  getLatex,
  onApply,
}: ContactFormatterPanelProps) {
  const [changes, setChanges] = useState<ContactChange[] | null>(null)
  const [formattedLatex, setFormattedLatex] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(true)
  const requestIdRef = useRef(0)
  const modalRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)
  const titleId = useId()

  // Reset on open
  useEffect(() => {
    requestIdRef.current += 1
    if (!isOpen) {
      setLoading(false)
      return
    }
    triggerRef.current = document.activeElement as HTMLElement | null
    setChanges(null)
    setFormattedLatex(null)
    setPreviewOpen(true)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const frame = requestAnimationFrame(() => modalRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
      triggerRef.current?.focus?.()
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !modalRef.current) return
      const focusable = Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.offsetParent !== null || element === document.activeElement)
      if (focusable.length === 0) {
        event.preventDefault()
        modalRef.current.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === modalRef.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  const handleDetect = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    setLoading(true)
    setChanges(null)
    setFormattedLatex(null)
    const requestId = ++requestIdRef.current
    try {
      const result = await apiClient.formatContacts(latex)
      if (requestId !== requestIdRef.current) return
      setChanges(result.changes)
      setFormattedLatex(result.formatted_latex)
      if (result.changes.length === 0) {
        toast.info('All contacts are already normalized')
      }
    } catch (err) {
      if (requestId !== requestIdRef.current) return
      toast.error(err instanceof Error ? err.message : 'Detection failed')
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }, [getLatex])

  const handleApply = useCallback(() => {
    if (!formattedLatex) return
    onApply(formattedLatex)
    toast.success(
      `Applied ${changes?.length ?? 0} contact change${changes?.length !== 1 ? 's' : ''}`
    )
    onClose()
  }, [formattedLatex, changes, onApply, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div ref={modalRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)] focus:outline-none">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] bg-ok/15">
              <Phone size={13} className="text-ok" />
            </div>
            <h2 id={titleId} className="text-sm font-semibold text-fg">Normalize Contacts</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <p className="text-[12px] text-fg-3">
            Normalizes phone numbers, LinkedIn / GitHub URLs, and emails to a consistent format.
          </p>

          {/* Detect button */}
          <button
            type="button"
            onClick={handleDetect}
            disabled={loading}
            aria-busy={loading}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2 disabled:opacity-50"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> Detecting…</>
            ) : (
              'Detect Contact Info'
            )}
          </button>

          {/* Results */}
          {changes !== null && (
            <>
              {changes.length === 0 ? (
                <div className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-3 text-center">
                  <p className="text-[12px] text-fg-3">All contacts are already normalized</p>
                </div>
              ) : (
                <div className="rounded-[var(--radius-md)] border border-line bg-bg">
                  <button
                    type="button"
                    onClick={() => setPreviewOpen((o) => !o)}
                    aria-expanded={previewOpen}
                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-fg-3"
                  >
                    <span>{changes.length} change{changes.length !== 1 ? 's' : ''} found</span>
                    {previewOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  {previewOpen && (
                    <div className="max-h-52 divide-y divide-line overflow-y-auto">
                      {changes.map((c, i) => (
                        <div key={i} className="px-3 py-1.5">
                          <div className="mb-0.5 flex items-center gap-1.5">
                            <span className="w-8 shrink-0 text-[10px] text-fg-3">L{c.line}</span>
                            <span className="rounded bg-surface-2 px-1 py-0.5 text-[9px] uppercase tracking-wider text-fg-3">
                              {TYPE_LABELS[c.type] ?? c.type}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 pl-9">
                            <span className="flex-1 truncate font-mono text-[11px] text-err line-through">
                              {c.original}
                            </span>
                            <span className="shrink-0 text-fg-3">→</span>
                            <span className="flex-1 truncate font-mono text-[11px] text-ok">
                              {c.normalized}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {changes.length > 0 && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={onClose}
                    className="flex-1 rounded-[var(--radius-md)] border border-line py-2 text-xs font-semibold text-fg-3 transition hover:text-fg-2"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleApply}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/20 py-2 text-xs font-semibold text-ok ring-1 ring-ok/20 transition hover:bg-ok/30"
                  >
                    <Check size={12} />
                    Apply All
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
