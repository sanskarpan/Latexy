'use client'

import { useCallback, useEffect, useState } from 'react'
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

  // Reset on open
  useEffect(() => {
    if (!isOpen) return
    setChanges(null)
    setFormattedLatex(null)
    setPreviewOpen(true)
  }, [isOpen])

  const handleDetect = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    setLoading(true)
    setChanges(null)
    setFormattedLatex(null)
    try {
      const result = await apiClient.formatContacts(latex)
      setChanges(result.changes)
      setFormattedLatex(result.formatted_latex)
      if (result.changes.length === 0) {
        toast.info('All contacts are already normalized')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Detection failed')
    } finally {
      setLoading(false)
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-emerald-500/15">
              <Phone size={13} className="text-emerald-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Normalize Contacts</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <p className="text-[12px] text-zinc-500">
            Normalizes phone numbers, LinkedIn / GitHub URLs, and emails to a consistent format.
          </p>

          {/* Detect button */}
          <button
            onClick={handleDetect}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
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
                <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3 text-center">
                  <p className="text-[12px] text-zinc-500">All contacts are already normalized</p>
                </div>
              ) : (
                <div className="rounded-lg border border-white/[0.06] bg-black/20">
                  <button
                    onClick={() => setPreviewOpen((o) => !o)}
                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
                  >
                    <span>{changes.length} change{changes.length !== 1 ? 's' : ''} found</span>
                    {previewOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  {previewOpen && (
                    <div className="max-h-52 divide-y divide-white/[0.04] overflow-y-auto">
                      {changes.map((c, i) => (
                        <div key={i} className="px-3 py-1.5">
                          <div className="mb-0.5 flex items-center gap-1.5">
                            <span className="w-8 shrink-0 text-[10px] text-zinc-700">L{c.line}</span>
                            <span className="rounded bg-white/[0.04] px-1 py-0.5 text-[9px] uppercase tracking-wider text-zinc-600">
                              {TYPE_LABELS[c.type] ?? c.type}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 pl-9">
                            <span className="flex-1 truncate font-mono text-[11px] text-rose-400/80 line-through">
                              {c.original}
                            </span>
                            <span className="shrink-0 text-zinc-700">→</span>
                            <span className="flex-1 truncate font-mono text-[11px] text-emerald-400/80">
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
                    onClick={onClose}
                    className="flex-1 rounded-lg border border-white/[0.06] py-2 text-xs font-semibold text-zinc-500 transition hover:text-zinc-300"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleApply}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/20 py-2 text-xs font-semibold text-emerald-200 ring-1 ring-emerald-400/20 transition hover:bg-emerald-500/30"
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
