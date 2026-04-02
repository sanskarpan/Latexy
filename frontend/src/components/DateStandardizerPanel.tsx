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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-sky-500/15">
              <Calendar size={13} className="text-sky-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Date Format Standardizer</h2>
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
          {/* Format selector */}
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              Target Format
            </label>
            <div className="grid grid-cols-2 gap-2">
              {FORMAT_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => handleFormatChange(opt.value)}
                  className={`rounded-lg border px-3 py-2 text-left transition ${
                    format === opt.value
                      ? 'border-sky-400/30 bg-sky-500/10 text-sky-200'
                      : 'border-white/[0.06] text-zinc-500 hover:border-white/[0.10] hover:text-zinc-300'
                  }`}
                >
                  <p className="text-[12px] font-medium">{opt.example}</p>
                  <p className="text-[10px] text-zinc-600">{opt.label}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Detect button */}
          <button
            onClick={handleDetect}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
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
                <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3 text-center">
                  <p className="text-[12px] text-zinc-500">No dates found to standardize</p>
                </div>
              ) : (
                <div className="rounded-lg border border-white/[0.06] bg-black/20">
                  <button
                    onClick={() => setPreviewOpen(o => !o)}
                    className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
                  >
                    <span>{occurrences.length} change{occurrences.length !== 1 ? 's' : ''} found</span>
                    {previewOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </button>
                  {previewOpen && (
                    <div className="max-h-52 divide-y divide-white/[0.04] overflow-y-auto">
                      {occurrences.map((occ, i) => (
                        <div key={i} className="flex items-center gap-2 px-3 py-1.5">
                          <span className="w-8 shrink-0 text-[10px] text-zinc-700">L{occ.line}</span>
                          <span className="flex-1 font-mono text-[11px] text-rose-400/80 line-through">
                            {occ.original}
                          </span>
                          <span className="text-zinc-700">→</span>
                          <span className="flex-1 font-mono text-[11px] text-emerald-400/80">
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
                    className="flex-1 rounded-lg border border-white/[0.06] py-2 text-xs font-semibold text-zinc-500 transition hover:text-zinc-300"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleApply}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-sky-500/20 py-2 text-xs font-semibold text-sky-200 ring-1 ring-sky-400/20 transition hover:bg-sky-500/30"
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
