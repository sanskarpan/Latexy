'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, RefreshCw, Scissors, Sparkles, TrendingUp, X, ZoomIn } from 'lucide-react'
import { apiClient, type RewriteAction } from '@/lib/api-client'

interface ActionDef {
  key: RewriteAction
  label: string
  icon: React.ReactNode
  description: string
}

const ACTIONS: ActionDef[] = [
  { key: 'improve',     label: 'Improve',     icon: <Sparkles size={11} />,   description: 'Stronger impact & clarity' },
  { key: 'shorten',     label: 'Shorten',     icon: <Scissors size={11} />,   description: 'Condense by ~50%' },
  { key: 'quantify',    label: 'Quantify',    icon: <TrendingUp size={11} />, description: 'Add metrics & numbers' },
  { key: 'power_verbs', label: 'Power Verbs', icon: <Check size={11} />,      description: 'Replace weak verbs' },
  { key: 'expand',      label: 'Expand',      icon: <ZoomIn size={11} />,     description: 'Add more detail' },
]

type Phase = 'picking' | 'loading' | 'result'

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
  const [rewritten, setRewritten]       = useState<string | null>(null)
  const [error, setError]               = useState<string | null>(null)

  // Reset when widget opens/closes or selectedText changes
  useEffect(() => {
    if (isOpen) {
      setPhase('picking')
      setActiveAction(null)
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

  const callApi = async (action: RewriteAction) => {
    setActiveAction(action)
    setPhase('loading')
    setError(null)
    setRewritten(null)
    try {
      const res = await apiClient.rewriteText({
        selected_text: selectedText,
        action,
        context: context || undefined,
      })
      setRewritten(res.rewritten)
      setPhase('result')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to rewrite')
      setPhase('picking')
    }
  }

  const handleRegenerate = () => {
    if (activeAction) callApi(activeAction)
  }

  if (!isOpen) return null

  const clampedTop = Math.max(8, top - 4)

  return (
    <>
      {/* Click-outside backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} aria-hidden="true" />

      {/* Widget panel */}
      <div
        className="absolute left-4 z-50 w-80 rounded-xl border border-white/[0.1] bg-zinc-950 shadow-2xl shadow-black/60 ring-1 ring-white/[0.06]"
        style={{ top: clampedTop }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.07] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-violet-400" />
            <span className="text-[11px] font-semibold text-zinc-200">AI Writing Assistant</span>
            {activeAction && phase !== 'picking' && (
              <span className="rounded-md bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-400/20">
                {ACTIONS.find(a => a.key === activeAction)?.label}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close writing assistant"
            className="rounded-md p-0.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={13} />
          </button>
        </div>

        <div className="p-3 space-y-2.5">
          {/* Selected text preview */}
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">Selected text</p>
            <p className="rounded-lg border border-white/[0.06] bg-black/30 px-2.5 py-1.5 text-[11px] leading-relaxed text-zinc-400 line-clamp-2">
              {selectedText}
            </p>
          </div>

          {/* Error */}
          {error && (
            <p className="rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-[11px] text-rose-400 ring-1 ring-rose-500/20">
              {error}
            </p>
          )}

          {/* ── Phase: picking ─────────────────────────────────────── */}
          {phase === 'picking' && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">Choose an action</p>
              {ACTIONS.map(({ key, label, icon, description }) => (
                <button
                  key={key}
                  onClick={() => callApi(key)}
                  className="flex w-full items-center gap-2.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-2.5 py-2 text-left transition hover:border-violet-400/20 hover:bg-violet-500/[0.08]"
                >
                  <span className="shrink-0 text-violet-400">{icon}</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[11px] font-semibold text-zinc-200">{label}</span>
                    <span className="block text-[10px] text-zinc-600">{description}</span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* ── Phase: loading ─────────────────────────────────────── */}
          {phase === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-6 text-zinc-500">
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">Rewriting…</span>
            </div>
          )}

          {/* ── Phase: result ──────────────────────────────────────── */}
          {phase === 'result' && rewritten !== null && (
            <div className="space-y-2.5">
              {/* Diff view */}
              <div className="rounded-lg border border-white/[0.07] bg-black/20 p-2.5 space-y-2">
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-rose-500/70">Original</p>
                  <p className="text-[11px] leading-relaxed text-rose-400/80 line-through decoration-rose-500/40">
                    {selectedText}
                  </p>
                </div>
                <div className="border-t border-white/[0.06]" />
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-500/70">Rewritten</p>
                  <p className="text-[11px] leading-relaxed text-emerald-300">
                    {rewritten}
                  </p>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onAccept(rewritten)}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/20 py-2 text-[11px] font-semibold text-emerald-300 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30"
                >
                  <Check size={11} />
                  Accept
                </button>
                <button
                  onClick={handleRegenerate}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.07] bg-white/[0.03] px-3 py-2 text-[11px] font-semibold text-zinc-400 transition hover:border-violet-400/20 hover:text-zinc-200"
                  title="Try again"
                >
                  <RefreshCw size={11} />
                </button>
                <button
                  onClick={onClose}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.07] bg-white/[0.03] px-3 py-2 text-[11px] font-semibold text-zinc-400 transition hover:text-zinc-200"
                  title="Reject"
                >
                  <X size={11} />
                </button>
              </div>

              {/* Back to actions */}
              <button
                onClick={() => setPhase('picking')}
                className="flex w-full items-center justify-center gap-1 text-[10px] text-zinc-600 transition hover:text-zinc-400"
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
