'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
  const containerRef = useRef<HTMLDivElement>(null)
  // Flip/clamp so the panel is never clipped when opened low in the editor.
  const [placement, setPlacement] = useState<{
    top?: number
    bottom?: number
    maxHeight: number
  } | null>(null)

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

  // Anchor position within the positioned editor container.
  const anchorTop = Math.max(8, top - 4)

  // Measure against the viewport, flip upward when there's more room above,
  // and always cap height so long content scrolls inside the panel.
  useLayoutEffect(() => {
    if (!isOpen) return
    const el = containerRef.current
    if (!el) return
    const margin = 12
    // Derive the anchor's viewport position from the positioned parent so the
    // measurement is stable across re-measures (independent of any flip already
    // applied to the panel itself).
    const parent = el.offsetParent as HTMLElement | null
    const parentRect = parent?.getBoundingClientRect()
    const parentTop = parentRect?.top ?? 0
    const parentBottom = parentRect?.bottom ?? window.innerHeight
    const anchorViewportTop = parentTop + anchorTop
    const spaceBelow = window.innerHeight - anchorViewportTop - margin
    const spaceAbove = anchorViewportTop - margin
    if (spaceBelow < 320 && spaceAbove > spaceBelow) {
      // Open upward: pin the panel's bottom to the anchor line.
      setPlacement({
        bottom: parentBottom - anchorViewportTop,
        maxHeight: spaceAbove,
      })
    } else {
      setPlacement({ top: anchorTop, maxHeight: Math.max(120, spaceBelow) })
    }
  }, [isOpen, top, anchorTop, summaries, jobDescOpen])

  if (!isOpen) return null

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
        ref={containerRef}
        className="absolute left-4 z-50 w-84 overflow-y-auto overscroll-contain rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)] ring-1 ring-line"
        style={{
          top: placement?.top ?? (placement?.bottom !== undefined ? undefined : anchorTop),
          bottom: placement?.bottom,
          maxHeight: placement?.maxHeight,
          width: '22rem',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-accent-strong" />
            <span className="text-[11px] font-semibold text-fg">AI Summary Generator</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-0.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={13} />
          </button>
        </div>

        <div className="space-y-2.5 p-3">
          {/* Target role */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Target role (optional)
            </label>
            <input
              type="text"
              value={targetRole}
              onChange={e => setTargetRole(e.target.value)}
              placeholder="e.g. Senior Software Engineer"
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
            />
          </div>

          {/* Job description toggle */}
          <div>
            <button
              onClick={() => setJobDescOpen(v => !v)}
              className="flex w-full items-center justify-between text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3 hover:text-fg-2 transition"
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
                className="mt-1 w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
              />
            )}
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={isLoading}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={11} className="animate-spin" /> Generating summaries…</>
            ) : (
              <><Sparkles size={11} /> Generate 3 Alternatives</>
            )}
          </button>

          {/* Empty / error state */}
          {attempted && summaries.length === 0 && !isLoading && (
            <p className="text-center text-[10px] text-err">
              No summaries returned — check your API key or try again.
            </p>
          )}

          {/* Results */}
          {summaries.length > 0 && (
            <div className="space-y-1.5 pt-0.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                Click to insert
              </p>
              {summaries.map((s, i) => (
                <button
                  key={i}
                  onClick={() => handleInsert(s, i)}
                  className={`group flex w-full flex-col items-start gap-1 rounded-[var(--radius-md)] border p-2 text-left transition ${
                    insertedIdx === i
                      ? 'border-ok bg-ok/10'
                      : 'border-line bg-surface-2 hover:border-accent hover:bg-accent-soft'
                  }`}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className={`text-[9px] font-bold uppercase tracking-[0.1em] ${
                      insertedIdx === i ? 'text-ok' : 'text-accent-strong'
                    }`}>
                      {s.title}
                    </span>
                    {insertedIdx === i && <Check size={10} className="shrink-0 text-ok" />}
                  </div>
                  <span className={`text-[10.5px] leading-relaxed ${
                    insertedIdx === i ? 'text-ok' : 'text-fg-2 group-hover:text-fg'
                  }`}>
                    {s.text}
                  </span>
                </button>
              ))}

              {/* Regenerate */}
              <button
                onClick={handleGenerate}
                disabled={isLoading}
                className="mt-1 flex w-full items-center justify-center gap-1 text-[10px] text-fg-3 transition hover:text-fg-2 disabled:opacity-40"
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
