'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Check, Loader2, RefreshCw, Sparkles, X } from 'lucide-react'
import {
  apiClient,
  type GenerateBulletsRequest,
  type PhraseSeniority,
  type PhraseSignal,
} from '@/lib/api-client'

type Tone = 'technical' | 'leadership' | 'analytical' | 'creative'

const TONES: { key: Tone; label: string }[] = [
  { key: 'technical',  label: 'Technical'  },
  { key: 'leadership', label: 'Leadership' },
  { key: 'analytical', label: 'Analytical' },
  { key: 'creative',   label: 'Creative'   },
]

const SIGNAL_LABELS: Record<PhraseSignal, string> = {
  high_impact: 'High impact',
  // This signal is a heuristic about plain, parseable wording; do not present
  // it as a prediction about third-party applicant-tracking systems.
  ats_friendly: 'Parsing clarity',
  leadership: 'Leadership',
  technical_depth: 'Technical depth',
}

interface BulletGeneratorWidgetProps {
  isOpen: boolean
  onClose: () => void
  /** Insert the chosen bullet into the editor */
  onInsert: (bullet: string) => void
  /** Pixel offset from the editor container top edge (from Monaco scroll position) */
  top: number
}

export default function BulletGeneratorWidget({
  isOpen,
  onClose,
  onInsert,
  top,
}: BulletGeneratorWidgetProps) {
  const [jobTitle, setJobTitle]           = useState('')
  const [mode, setMode]                   = useState<'generate' | 'library'>('generate')
  const [responsibility, setResp]         = useState('')
  const [tone, setTone]                   = useState<Tone>('technical')
  const [bullets, setBullets]             = useState<string[]>([])
  const [isLoading, setIsLoading]         = useState(false)
  const [insertedIdx, setInsertedIdx]     = useState<number | null>(null)
  const [generationAttempted, setAttempted] = useState(false)
  const [error, setError]                 = useState<string | null>(null)
  const [seniority, setSeniority]         = useState<PhraseSeniority>('senior')
  const [industry, setIndustry]           = useState('')
  const [skillCategory, setSkillCategory] = useState('')
  const [phrases, setPhrases]             = useState<Array<{ text: string; signals: PhraseSignal[] }>>([])
  const containerRef                      = useRef<HTMLDivElement>(null)
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

  // Reset inserted state when bullets change
  useEffect(() => { setInsertedIdx(null) }, [bullets, phrases])

  const handleGenerate = async () => {
    if (!responsibility.trim() || isLoading) return
    setIsLoading(true)
    setBullets([])
    setAttempted(false)
    setError(null)
    try {
      const req: GenerateBulletsRequest = {
        job_title:      jobTitle.trim() || 'Professional',
        responsibility: responsibility.trim(),
        tone,
        count: 5,
      }
      const res = await apiClient.generateBullets(req)
      setBullets(res.bullets)
      setAttempted(true)
    } catch (reason) {
      setAttempted(true)
      setError(reason instanceof Error ? reason.message : 'Bullets could not be generated')
    } finally {
      setIsLoading(false)
    }
  }

  const handleBrowseLibrary = async () => {
    if (!jobTitle.trim() || !industry.trim() || !skillCategory.trim() || isLoading) return
    setIsLoading(true)
    setPhrases([])
    setAttempted(false)
    setError(null)
    try {
      const response = await apiClient.generatePhraseLibrary({
        job_title: jobTitle.trim(),
        seniority,
        industry: industry.trim(),
        skill_category: skillCategory.trim(),
        count: 10,
      })
      setPhrases(response.phrases)
      setAttempted(true)
    } catch (reason) {
      setAttempted(true)
      setError(reason instanceof Error ? reason.message : 'Phrase library could not be loaded')
    } finally {
      setIsLoading(false)
    }
  }

  const handleInsert = (bullet: string, idx: number) => {
    onInsert(bullet)
    setInsertedIdx(idx)
    setTimeout(onClose, 300)
  }

  // Anchor position within the positioned editor container.
  const anchorTop = Math.max(8, top - 4)

  // Measure the panel against the viewport and decide direction + maxHeight.
  // Runs after the panel mounts at `anchorTop`, then flips upward if there's
  // more room above, and always caps height so content scrolls inside.
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
  }, [isOpen, top, anchorTop, bullets, phrases])

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
        className="absolute left-4 z-50 w-80 overflow-y-auto overscroll-contain rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)] ring-1 ring-line"
        style={{
          top: placement?.top ?? (placement?.bottom !== undefined ? undefined : anchorTop),
          bottom: placement?.bottom,
          maxHeight: placement?.maxHeight,
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-accent-strong" />
            <span className="text-[11px] font-semibold text-fg">Bullet ideas</span>
          </div>
          <button
            type="button"
            aria-label="Close bullet ideas"
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-0.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={13} />
          </button>
        </div>

        <div className="space-y-2.5 p-3">
          <div className="grid grid-cols-2 gap-1 rounded-[var(--radius-md)] bg-surface-2 p-1" role="tablist" aria-label="Bullet idea source">
            {(['generate', 'library'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={mode === option}
                onClick={() => {
                  setMode(option)
                  setAttempted(false)
                  setError(null)
                }}
                className={`rounded px-2 py-1 text-[10px] font-semibold ${mode === option ? 'bg-surface text-fg shadow-sm' : 'text-fg-3'}`}
              >
                {option === 'generate' ? 'Write from my facts' : 'Phrase library'}
              </button>
            ))}
          </div>

          {/* Job title */}
          <div>
            <label htmlFor="bullet-job-title" className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Job title
            </label>
            <input
              id="bullet-job-title"
              type="text"
              value={jobTitle}
              onChange={e => setJobTitle(e.target.value)}
              placeholder="e.g. Software Engineer"
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-[11px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
            />
          </div>

          {mode === 'generate' ? <>
          {/* Responsibility */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              What you did
            </label>
            <textarea
              value={responsibility}
              onChange={e => setResp(e.target.value)}
              placeholder="Describe what you built, owned, or achieved…"
              rows={2}
              className="w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-[11px] text-fg-2 outline-none placeholder:text-fg-3 focus:border-line-2 transition"
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleGenerate()
              }}
            />
          </div>

          {/* Tone selector */}
          <div className="flex gap-1">
            {TONES.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTone(key)}
                className={`flex-1 rounded-[var(--radius-md)] py-1 text-[9px] font-semibold transition ${
                  tone === key
                    ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
                    : 'bg-surface-2 text-fg-3 hover:text-fg-2'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={!responsibility.trim() || isLoading}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={11} className="animate-spin" /> Generating 5 bullets…</>
            ) : (
              <><Sparkles size={11} /> Generate</>
            )}
          </button>

          {/* Empty / error state after generation attempt */}
          {generationAttempted && bullets.length === 0 && !isLoading && (
            <p className="text-center text-[10px] text-err">
              {error ?? 'No bullets returned — check your API key or try rephrasing.'}
            </p>
          )}

          {/* Results */}
          {bullets.length > 0 && (
            <div className="space-y-1.5 pt-0.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                Click to insert
              </p>
              {bullets.map((bullet, i) => (
                <button
                  key={i}
                  onClick={() => handleInsert(bullet, i)}
                  className={`group flex w-full items-start gap-2 rounded-[var(--radius-md)] border p-2 text-left transition ${
                    insertedIdx === i
                      ? 'border-ok bg-surface-2 text-ok'
                      : 'border-line bg-surface-2 text-fg-2 hover:border-accent hover:bg-accent-soft'
                  }`}
                >
                  <span className="mt-0.5 shrink-0">
                    {insertedIdx === i
                      ? <Check size={11} className="text-ok" />
                      : <span className="block h-[11px] w-[11px] rounded-full border border-line-2 group-hover:border-accent" />
                    }
                  </span>
                  <span className="text-[11px] leading-relaxed">{bullet}</span>
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
          </> : <>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3" htmlFor="phrase-seniority">Seniority</label>
                <select
                  id="phrase-seniority"
                  value={seniority}
                  onChange={(event) => setSeniority(event.target.value as PhraseSeniority)}
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-2 py-1.5 text-[11px] text-fg-2"
                >
                  <option value="entry">Entry</option>
                  <option value="mid">Mid-level</option>
                  <option value="senior">Senior</option>
                  <option value="lead">Lead</option>
                  <option value="executive">Executive</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3" htmlFor="phrase-industry">Industry</label>
                <input
                  id="phrase-industry"
                  value={industry}
                  onChange={(event) => setIndustry(event.target.value)}
                  placeholder="e.g. Fintech"
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-2 py-1.5 text-[11px] text-fg-2"
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3" htmlFor="phrase-skill">Skill category</label>
              <input
                id="phrase-skill"
                value={skillCategory}
                onChange={(event) => setSkillCategory(event.target.value)}
                placeholder="e.g. Distributed systems"
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-[11px] text-fg-2"
              />
            </div>
            <p className="rounded border border-warn/30 bg-warn/10 px-2 py-1.5 text-[10px] text-warn">
              Replace every [X] placeholder with a truthful metric before using a phrase.
            </p>
            <button
              type="button"
              onClick={() => void handleBrowseLibrary()}
              disabled={!jobTitle.trim() || !industry.trim() || !skillCategory.trim() || isLoading}
              className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent disabled:opacity-40"
            >
              {isLoading ? <><Loader2 size={11} className="animate-spin" /> Loading phrases…</> : <><Sparkles size={11} /> Browse 10 phrases</>}
            </button>
            {generationAttempted && phrases.length === 0 && !isLoading && (
              <p role="alert" className="text-center text-[10px] text-err">{error ?? 'No safe phrases were returned.'}</p>
            )}
            {phrases.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">Click to insert and personalize</p>
                {phrases.map((phrase, index) => (
                  <button
                    key={phrase.text}
                    type="button"
                    onClick={() => handleInsert(phrase.text, index)}
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 p-2 text-left hover:border-accent"
                  >
                    <span className="block text-[11px] leading-relaxed text-fg-2">{phrase.text}</span>
                    <span className="mt-1.5 flex flex-wrap gap-1">
                      {phrase.signals.map((signal) => (
                        <span key={signal} className="rounded-full border border-line px-1.5 py-0.5 text-[9px] text-fg-3">{SIGNAL_LABELS[signal]}</span>
                      ))}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </>}
        </div>
      </div>
    </>
  )
}
