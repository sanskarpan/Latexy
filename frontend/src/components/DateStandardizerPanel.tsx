'use client'

import { useCallback, useEffect, useState } from 'react'
import { Calendar, Check, ChevronDown, ChevronRight, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type DateOccurrence } from '@/lib/api-client'

type TargetFormat = 'MMM YYYY' | 'MMMM YYYY' | 'YYYY-MM' | 'MM/YYYY'

const FORMAT_OPTIONS: { value: TargetFormat; label: string; example: string }[] = [
  { value: 'MMM YYYY', label: 'Short month', example: 'Jan 2020' },
  { value: 'MMMM YYYY', label: 'Full month', example: 'January 2020' },
  { value: 'YYYY-MM', label: 'ISO 8601', example: '2020-01' },
  { value: 'MM/YYYY', label: 'Numeric', example: '01/2020' },
]

interface DateStandardizerPanelProps {
  isOpen: boolean
  onClose: () => void
  /** Returns current editor LaTeX content */
  getLatex: () => string
  /** Called with the fully-standardized LaTeX when user clicks Apply */
  onApply: (newLatex: string) => void
}

export default function DateStandardizerPanel({
  isOpen,
  onClose,
  getLatex,
  onApply,
}: DateStandardizerPanelProps) {
  const [format, setFormat] = useState<TargetFormat>('MMM YYYY')
  const [occurrences, setOccurrences] = useState<DateOccurrence[] | null>(null)
  const [standardizedLatex, setStandardizedLatex] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(true)

  // Reset results whenever the panel is opened so stale state is never applied
  useEffect(() => {
    if (!isOpen) return
    setOccurrences(null)
    setStandardizedLatex(null)
    setPreviewOpen(true)
  }, [isOpen])

  const handleDetect = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    setLoading(true)
    setOccurrences(null)
    setStandardizedLatex(null)
    try {
      const result = await apiClient.standardizeDates(latex, format)
      setOccurrences(result.occurrences)
      setStandardizedLatex(result.standardized_latex)
      if (result.occurrences.length === 0) {
        toast.info('No dates found to standardize')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Detection failed')
    } finally {
      setLoading(false)
    }
  }, [getLatex, format])

  const handleApply = useCallback(() => {
    if (!standardizedLatex) return
    onApply(standardizedLatex)
    toast.success(`Applied ${occurrences?.length ?? 0} date change${occurrences?.length !== 1 ? 's' : ''}`)
    onClose()
  }, [standardizedLatex, occurrences, onApply, onClose])

  // Reset when format changes so stale results aren't applied
  const handleFormatChange = (f: TargetFormat) => {
    setFormat(f)
    setOccurrences(null)
    setStandardizedLatex(null)
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Calendar size={13} className="text-accent-strong" />
            </div>
            <h2 className="text-sm font-semibold text-fg">Date Format Standardizer</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          {/* Format selector */}
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Target Format
            </label>
            <div className="grid grid-cols-2 gap-2">
              {FORMAT_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => handleFormatChange(opt.value)}
                  className={`rounded-[var(--radius-md)] border px-3 py-2 text-left transition ${
                    format === opt.value
                      ? 'border-accent bg-accent-soft text-accent-strong'
                      : 'border-line text-fg-3 hover:border-line-2 hover:text-fg-2'
                  }`}
                >
                  <p className="text-[12px] font-medium">{opt.example}</p>
                  <p className="text-[10px] text-fg-3">{opt.label}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Detect button */}
          <button
            onClick={handleDetect}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2 disabled:opacity-50"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> Detecting…</>
            ) : (
              'Detect Dates'
            )}
          </button>

          {/* Results */}
          {occurrences !== null && (
            <>
              {occurrences.length === 0 ? (
                <div className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-3 text-center">
                  <p className="text-[12px] text-fg-3">No dates found to standardize</p>
                </div>
              ) : (
                <div className="rounded-[var(--radius-md)] border border-line bg-surface">
                  <button
                    onClick={() => setPreviewOpen(o => !o)}
                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-fg-3"
                  >
                    <span>{occurrences.length} change{occurrences.length !== 1 ? 's' : ''} found</span>
                    {previewOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  {previewOpen && (
                    <div className="max-h-52 divide-y divide-line overflow-y-auto">
                      {occurrences.map((occ, i) => (
                        <div key={i} className="flex items-center gap-2 px-3 py-1.5">
                          <span className="w-8 shrink-0 text-[10px] text-fg-3">L{occ.line}</span>
                          <span className="flex-1 font-mono text-[11px] text-err line-through">
                            {occ.original}
                          </span>
                          <span className="text-fg-3">→</span>
                          <span className="flex-1 font-mono text-[11px] text-ok">
                            {occ.standardized}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Apply / Cancel */}
              {occurrences.length > 0 && (
                <div className="flex gap-2">
                  <button
                    onClick={onClose}
                    className="flex-1 rounded-[var(--radius-md)] border border-line py-2 text-xs font-semibold text-fg-3 transition hover:text-fg-2"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleApply}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
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
