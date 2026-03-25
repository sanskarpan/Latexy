'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, RefreshCw, Sparkles, X } from 'lucide-react'
import { apiClient, type GenerateBulletsRequest } from '@/lib/api-client'

type Tone = 'technical' | 'leadership' | 'analytical' | 'creative'

const TONES: { key: Tone; label: string }[] = [
  { key: 'technical',  label: 'Technical'  },
  { key: 'leadership', label: 'Leadership' },
  { key: 'analytical', label: 'Analytical' },
  { key: 'creative',   label: 'Creative'   },
]

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
  const [responsibility, setResp]         = useState('')
  const [tone, setTone]                   = useState<Tone>('technical')
  const [bullets, setBullets]             = useState<string[]>([])
  const [isLoading, setIsLoading]         = useState(false)
  const [insertedIdx, setInsertedIdx]     = useState<number | null>(null)
  const [generationAttempted, setAttempted] = useState(false)
  const containerRef                      = useRef<HTMLDivElement>(null)

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  // Reset inserted state when bullets change
  useEffect(() => { setInsertedIdx(null) }, [bullets])

  const handleGenerate = async () => {
    if (!responsibility.trim() || isLoading) return
    setIsLoading(true)
    setBullets([])
    setAttempted(false)
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
    } catch {
      setAttempted(true)
    } finally {
      setIsLoading(false)
    }
  }

  const handleInsert = (bullet: string, idx: number) => {
    onInsert(bullet)
    setInsertedIdx(idx)
    setTimeout(onClose, 300)
  }

  if (!isOpen) return null

  // Clamp to keep widget visible (approximate widget height 380px)
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
        ref={containerRef}
        className="absolute left-4 z-50 w-80 rounded-xl border border-white/[0.1] bg-zinc-950 shadow-2xl shadow-black/60 ring-1 ring-white/[0.06]"
        style={{ top: clampedTop }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-violet-400" />
            <span className="text-[11px] font-semibold text-zinc-200">AI Bullet Generator</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-0.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={13} />
          </button>
        </div>

        <div className="space-y-2.5 p-3">
          {/* Job title */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              Job title
            </label>
            <input
              type="text"
              value={jobTitle}
              onChange={e => setJobTitle(e.target.value)}
              placeholder="e.g. Software Engineer"
              className="w-full rounded-lg border border-white/[0.07] bg-black/40 px-2.5 py-1.5 text-[11px] text-zinc-300 outline-none placeholder:text-zinc-700 focus:border-white/[0.14] transition"
            />
          </div>

          {/* Responsibility */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              What you did
            </label>
            <textarea
              value={responsibility}
              onChange={e => setResp(e.target.value)}
              placeholder="Describe what you built, owned, or achieved…"
              rows={2}
              className="w-full resize-none rounded-lg border border-white/[0.07] bg-black/40 px-2.5 py-1.5 text-[11px] text-zinc-300 outline-none placeholder:text-zinc-700 focus:border-white/[0.14] transition"
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
                className={`flex-1 rounded-md py-1 text-[9px] font-semibold transition ${
                  tone === key
                    ? 'bg-violet-500/25 text-violet-200 ring-1 ring-violet-400/30'
                    : 'bg-white/[0.04] text-zinc-600 hover:text-zinc-400'
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
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-500/20 py-2 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30 disabled:opacity-40"
          >
            {isLoading ? (
              <><Loader2 size={11} className="animate-spin" /> Generating 5 bullets…</>
            ) : (
              <><Sparkles size={11} /> Generate</>
            )}
          </button>

          {/* Empty / error state after generation attempt */}
          {generationAttempted && bullets.length === 0 && !isLoading && (
            <p className="text-center text-[10px] text-rose-400/80">
              No bullets returned — check your API key or try rephrasing.
            </p>
          )}

          {/* Results */}
          {bullets.length > 0 && (
            <div className="space-y-1.5 pt-0.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
                Click to insert
              </p>
              {bullets.map((bullet, i) => (
                <button
                  key={i}
                  onClick={() => handleInsert(bullet, i)}
                  className={`group flex w-full items-start gap-2 rounded-lg border p-2 text-left transition ${
                    insertedIdx === i
                      ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300'
                      : 'border-white/[0.06] bg-white/[0.03] text-zinc-300 hover:border-violet-400/20 hover:bg-violet-500/[0.08]'
                  }`}
                >
                  <span className="mt-0.5 shrink-0">
                    {insertedIdx === i
                      ? <Check size={11} className="text-emerald-400" />
                      : <span className="block h-[11px] w-[11px] rounded-full border border-white/[0.12] group-hover:border-violet-400/40" />
                    }
                  </span>
                  <span className="text-[11px] leading-relaxed">{bullet}</span>
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
