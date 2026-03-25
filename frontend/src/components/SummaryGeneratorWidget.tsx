'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronUp, Loader2, RefreshCw, Sparkles, X } from 'lucide-react'
import { apiClient, type SummaryVariant } from '@/lib/api-client'

interface SummaryGeneratorWidgetProps {
  isOpen: boolean
  onClose: () => void
  /** Insert the chosen summary text at cursor position */
  onInsert: (text: string) => void
  /** Full LaTeX content for context */
  resumeLatex: string
  /** Pixel offset from editor container top */
  top: number
}

export default function SummaryGeneratorWidget({
  isOpen,
  onClose,
  onInsert,
  resumeLatex,
  top,
}: SummaryGeneratorWidgetProps) {
  const [targetRole, setTargetRole] = useState('')
  const [jobDesc, setJobDesc] = useState('')
  const [jobDescOpen, setJobDescOpen] = useState(false)
  const [summaries, setSummaries] = useState<SummaryVariant[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [insertedIdx, setInsertedIdx] = useState<number | null>(null)
  const [attempted, setAttempted] = useState(false)

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  // Reset inserted state when summaries change
  useEffect(() => { setInsertedIdx(null) }, [summaries])

  const handleGenerate = async () => {
    if (isLoading) return
    setIsLoading(true)
    setSummaries([])
    setAttempted(false)
    try {
      const res = await apiClient.generateSummary({
        resume_latex: resumeLatex,
        target_role: targetRole.trim() || undefined,
        job_description: jobDesc.trim() || undefined,
        count: 3,
      })
      setSummaries(res.summaries)
      setAttempted(true)
    } catch {
      setAttempted(true)
    } finally {
      setIsLoading(false)
    }
  }

  const handleInsert = (summary: SummaryVariant, idx: number) => {
    onInsert(summary.text)
    setInsertedIdx(idx)
    setTimeout(onClose, 300)
  }

  if (!isOpen) return null

  const clampedTop = Math.max(8, top - 4)

  return (
    <>
      {/* Click-outside backdrop */}
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Widget panel */}
      <div
        className="absolute left-4 z-50 w-84 rounded-xl border border-white/[0.1] bg-zinc-950 shadow-2xl shadow-black/60 ring-1 ring-white/[0.06]"
        style={{ top: clampedTop, width: '22rem' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-violet-400" />
            <span className="text-[11px] font-semibold text-zinc-200">AI Summary Generator</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-0.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={13} />
          </button>
        </div>

        <div className="space-y-2.5 p-3">
          {/* Target role */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              Target role (optional)
            </label>
            <input
              type="text"
              value={targetRole}
              onChange={e => setTargetRole(e.target.value)}
              placeholder="e.g. Senior Software Engineer"
              className="w-full rounded-lg border border-white/[0.07] bg-black/40 px-2.5 py-1.5 text-[11px] text-zinc-300 outline-none placeholder:text-zinc-700 focus:border-white/[0.14] transition"
            />
          </div>

          {/* Job description toggle */}
          <div>
            <button
              onClick={() => setJobDescOpen(v => !v)}
              className="flex w-full items-center justify-between text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600 hover:text-zinc-400 transition"
            >
              <span>Job description (optional)</span>
              {jobDescOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
            {jobDescOpen && (
              <textarea
                value={jobDesc}
                onChange={e => setJobDesc(e.target.value)}
                placeholder="Paste job description for tailored summaries…"
                rows={3}
                className="mt-1 w-full resize-none rounded-lg border border-white/[0.07] bg-black/40 px-2.5 py-1.5 text-[11px] text-zinc-300 outline-none placeholder:text-zinc-700 focus:border-white/[0.14] transition"
              />
            )}
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={isLoading}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-500/20 py-2 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={11} className="animate-spin" /> Generating summaries…</>
            ) : (
              <><Sparkles size={11} /> Generate 3 Alternatives</>
            )}
          </button>

          {/* Empty / error state */}
          {attempted && summaries.length === 0 && !isLoading && (
            <p className="text-center text-[10px] text-rose-400/80">
              No summaries returned — check your API key or try again.
            </p>
          )}

          {/* Results */}
          {summaries.length > 0 && (
            <div className="space-y-1.5 pt-0.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
                Click to insert
              </p>
              {summaries.map((s, i) => (
                <button
                  key={i}
                  onClick={() => handleInsert(s, i)}
                  className={`group flex w-full flex-col items-start gap-1 rounded-lg border p-2 text-left transition ${
                    insertedIdx === i
                      ? 'border-emerald-400/30 bg-emerald-500/10'
                      : 'border-white/[0.06] bg-white/[0.03] hover:border-violet-400/20 hover:bg-violet-500/[0.08]'
                  }`}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className={`text-[9px] font-bold uppercase tracking-[0.1em] ${
                      insertedIdx === i ? 'text-emerald-400' : 'text-violet-400/80'
                    }`}>
                      {s.title}
                    </span>
                    {insertedIdx === i && <Check size={10} className="shrink-0 text-emerald-400" />}
                  </div>
                  <span className={`text-[10.5px] leading-relaxed ${
                    insertedIdx === i ? 'text-emerald-300' : 'text-zinc-400 group-hover:text-zinc-300'
                  }`}>
                    {s.text}
                  </span>
                </button>
              ))}

              {/* Regenerate */}
              <button
                onClick={handleGenerate}
                disabled={isLoading}
                className="mt-1 flex w-full items-center justify-center gap-1 text-[10px] text-zinc-600 transition hover:text-zinc-400 disabled:opacity-40"
              >
                <RefreshCw size={9} />
                Regenerate
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
