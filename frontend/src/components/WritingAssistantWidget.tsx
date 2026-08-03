'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Check, Loader2, MessageSquare, RefreshCw, Scissors, Sparkles, TrendingUp, Wand2, X, ZoomIn } from 'lucide-react'
import { apiClient, type RewriteAction } from '@/lib/api-client'

interface ActionDef {
  key: RewriteAction
  label: string
  icon: React.ReactNode
  description: string
}

const ACTIONS: ActionDef[] = [
  { key: 'improve',     label: 'Improve',     icon: <Sparkles size={11} />,      description: 'Stronger impact & clarity' },
  { key: 'shorten',     label: 'Shorten',     icon: <Scissors size={11} />,      description: 'Condense by ~50%' },
  { key: 'quantify',    label: 'Quantify',    icon: <TrendingUp size={11} />,    description: 'Add metrics & numbers' },
  { key: 'power_verbs', label: 'Power Verbs', icon: <Check size={11} />,         description: 'Replace weak verbs' },
  { key: 'change_tone', label: 'Change Tone', icon: <MessageSquare size={11} />, description: 'Formal or casual style' },
  { key: 'expand',      label: 'Expand',      icon: <ZoomIn size={11} />,        description: 'Add more detail' },
  { key: 'steer',       label: 'Steer',       icon: <Wand2 size={11} />,         description: 'Regenerate with your own note' },
]

const TONES = [
  { key: 'formal', label: 'Formal', description: 'Professional & precise' },
  { key: 'casual', label: 'Casual', description: 'Friendly & conversational' },
]

type Phase = 'picking' | 'tone_picking' | 'steer_input' | 'loading' | 'result'

interface WritingAssistantWidgetProps {
  isOpen: boolean
  selectedText: string
  context: string
  onAccept: (rewrittenText: string) => void
  onClose: () => void
  top: number
}

export default function WritingAssistantWidget({
  isOpen,
  selectedText,
  context,
  onAccept,
  onClose,
  top,
}: WritingAssistantWidgetProps) {
  const [phase, setPhase]               = useState<Phase>('picking')
  const [activeAction, setActiveAction] = useState<RewriteAction | null>(null)
  const [activeTone, setActiveTone]     = useState<string | null>(null)
  const [activeInstruction, setActiveInstruction] = useState<string | null>(null)
  const [steerNote, setSteerNote]       = useState('')
  const [rewritten, setRewritten]       = useState<string | null>(null)
  const [error, setError]               = useState<string | null>(null)
  const containerRef                    = useRef<HTMLDivElement>(null)
  // Flip/clamp so the panel is never clipped when opened low in the editor.
  const [placement, setPlacement] = useState<{
    top?: number
    bottom?: number
    maxHeight: number
  } | null>(null)

  // Reset when widget opens/closes or selectedText changes
  useEffect(() => {
    if (isOpen) {
      setPhase('picking')
      setActiveAction(null)
      setActiveTone(null)
      setActiveInstruction(null)
      setSteerNote('')
      setRewritten(null)
      setError(null)
    }
  }, [isOpen, selectedText])

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  const callApi = async (action: RewriteAction, tone?: string, instruction?: string) => {
    setActiveAction(action)
    setActiveTone(tone ?? null)
    setActiveInstruction(instruction ?? null)
    setPhase('loading')
    setError(null)
    setRewritten(null)
    try {
      const res = await apiClient.rewriteText({
        selected_text: selectedText,
        action,
        context: context || undefined,
        tone: tone || undefined,
        instruction: instruction || undefined,
      })
      setRewritten(res.rewritten)
      setPhase('result')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to rewrite')
      setPhase('picking')
    }
  }

  const handleActionClick = (key: RewriteAction) => {
    if (key === 'change_tone') {
      setActiveAction('change_tone')
      setPhase('tone_picking')
    } else if (key === 'steer') {
      setActiveAction('steer')
      setPhase('steer_input')
    } else {
      callApi(key)
    }
  }

  const handleRegenerate = () => {
    if (activeAction) callApi(activeAction, activeTone ?? undefined, activeInstruction ?? undefined)
  }

  // Anchor position within the positioned editor container.
  const anchorTop = Math.max(8, top - 4)

  // Measure against the viewport, flip upward when there's more room above,
  // and always cap height so long content scrolls inside the panel.
  // Recomputes on phase change since the panel grows with the diff/result view.
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
  }, [isOpen, top, anchorTop, phase])

  if (!isOpen) return null

  return (
    <>
      {/* Click-outside backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} aria-hidden="true" />

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
            <span className="text-[11px] font-semibold text-fg">AI Writing Assistant</span>
            {activeAction && phase !== 'picking' && (
              <span className="rounded-[var(--radius-md)] bg-accent-soft px-1.5 py-0.5 text-[10px] font-medium text-accent-strong ring-1 ring-accent/20">
                {ACTIONS.find(a => a.key === activeAction)?.label}
                {activeTone && phase === 'result' && ` · ${activeTone}`}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close writing assistant"
            className="rounded-[var(--radius-md)] p-0.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={13} />
          </button>
        </div>

        <div className="p-3 space-y-2.5">
          {/* Selected text preview */}
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">Selected text</p>
            <p className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-[11px] leading-relaxed text-fg-2 line-clamp-2">
              {selectedText}
            </p>
          </div>

          {/* Error */}
          {error && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-2.5 py-1.5 text-[11px] text-err ring-1 ring-err/20">
              {error}
            </p>
          )}

          {/* ── Phase: picking ─────────────────────────────────────── */}
          {phase === 'picking' && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">Choose an action</p>
              {ACTIONS.map(({ key, label, icon, description }) => (
                <button
                  key={key}
                  onClick={() => handleActionClick(key)}
                  className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-2 text-left transition hover:border-accent/20 hover:bg-accent-soft"
                >
                  <span className="shrink-0 text-accent-strong">{icon}</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[11px] font-semibold text-fg">{label}</span>
                    <span className="block text-[10px] text-fg-3">{description}</span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* ── Phase: tone_picking ─────────────────────────────────── */}
          {phase === 'tone_picking' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPhase('picking')}
                  className="text-[10px] text-fg-3 transition hover:text-fg-2"
                  aria-label="Back to actions"
                >
                  ←
                </button>
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">Choose tone</p>
              </div>
              {TONES.map(({ key, label, description }) => (
                <button
                  key={key}
                  onClick={() => callApi('change_tone', key)}
                  className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-2 text-left transition hover:border-accent/20 hover:bg-accent-soft"
                >
                  <span className="shrink-0 text-accent-strong"><MessageSquare size={11} /></span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[11px] font-semibold text-fg">{label}</span>
                    <span className="block text-[10px] text-fg-3">{description}</span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* ── Phase: steer_input ──────────────────────────────────── */}
          {phase === 'steer_input' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPhase('picking')}
                  className="text-[10px] text-fg-3 transition hover:text-fg-2"
                  aria-label="Back to actions"
                >
                  ←
                </button>
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">Your instruction</p>
              </div>
              <textarea
                value={steerNote}
                onChange={(e) => setSteerNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && steerNote.trim()) {
                    e.preventDefault()
                    callApi('steer', undefined, steerNote.trim())
                  }
                }}
                autoFocus
                maxLength={500}
                placeholder="e.g. Emphasize leadership and quantify the impact; keep it to one line."
                className="h-20 w-full resize-none rounded-[var(--radius-md)] border border-line-2 bg-surface px-2.5 py-1.5 text-[11px] leading-relaxed text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/30"
              />
              <button
                onClick={() => callApi('steer', undefined, steerNote.trim())}
                disabled={!steerNote.trim()}
                className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent/30 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Wand2 size={11} />
                Regenerate with this note
              </button>
            </div>
          )}

          {/* ── Phase: loading ─────────────────────────────────────── */}
          {phase === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-6 text-fg-3">
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">Rewriting…</span>
            </div>
          )}

          {/* ── Phase: result ──────────────────────────────────────── */}
          {phase === 'result' && rewritten !== null && (
            <div className="space-y-2.5">
              {/* Diff view */}
              <div className="rounded-[var(--radius-md)] border border-line bg-surface p-2.5 space-y-2">
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-err/70">Original</p>
                  <p className="text-[11px] leading-relaxed text-err/80 line-through decoration-err/40">
                    {selectedText}
                  </p>
                </div>
                <div className="border-t border-line" />
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-ok/70">Rewritten</p>
                  <p className="text-[11px] leading-relaxed text-ok">
                    {rewritten}
                  </p>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onAccept(rewritten)}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/20 py-2 text-[11px] font-semibold text-ok ring-1 ring-ok/30 transition hover:bg-ok/30"
                >
                  <Check size={11} />
                  Accept
                </button>
                <button
                  onClick={handleRegenerate}
                  className="flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[11px] font-semibold text-fg-2 transition hover:border-accent/20 hover:text-fg"
                  title="Try again"
                >
                  <RefreshCw size={11} />
                </button>
                <button
                  onClick={onClose}
                  className="flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[11px] font-semibold text-fg-2 transition hover:text-fg"
                  title="Reject"
                >
                  <X size={11} />
                </button>
              </div>

              {/* Back to actions */}
              <button
                onClick={() => setPhase('picking')}
                className="flex w-full items-center justify-center gap-1 text-[10px] text-fg-3 transition hover:text-fg-2"
              >
                Try a different action
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
