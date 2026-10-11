'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { BookOpen, Check, Copy, Loader2, MessageSquare, RefreshCw, Scissors, Sparkles, Trash2, TrendingUp, Wand2, X, ZoomIn } from 'lucide-react'
import { apiClient, type BulletVariantSet, type RewriteAction } from '@/lib/api-client'
import { useEntitlements } from '@/contexts/EntitlementsContext'

interface ActionDef {
  key: RewriteAction | 'synonyms'
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
  { key: 'paraphrase',  label: 'Paraphrase',  icon: <RefreshCw size={11} />,      description: 'Reword without changing meaning' },
  { key: 'concise',     label: 'Concise',     icon: <Scissors size={11} />,       description: 'Remove repetition and filler' },
  { key: 'scientific',  label: 'Scientific',  icon: <Sparkles size={11} />,       description: 'Precise, objective academic prose' },
  { key: 'split',       label: 'Split sentences', icon: <ZoomIn size={11} />,     description: 'Break up complex sentences' },
  { key: 'join',        label: 'Join sentences', icon: <MessageSquare size={11} />, description: 'Combine adjacent short sentences' },
  { key: 'synonyms',    label: 'Synonyms',    icon: <BookOpen size={11} />,       description: 'Replace a selected word or phrase' },
]

const TONES = [
  { key: 'formal', label: 'Formal', description: 'Professional & precise' },
  { key: 'casual', label: 'Casual', description: 'Friendly & conversational' },
]

type Phase = 'picking' | 'tone_picking' | 'steer_input' | 'loading' | 'result' | 'synonyms' | 'variant_setup' | 'variants' | 'library'

interface WritingAssistantWidgetProps {
  isOpen: boolean
  selectedText: string
  context: string
  resumeId: string
  jobDescription: string
  documentLatex: string
  onAccept: (rewrittenText: string) => void
  onClose: () => void
  top: number
}

export default function WritingAssistantWidget({
  isOpen,
  selectedText,
  context,
  resumeId,
  jobDescription,
  documentLatex,
  onAccept,
  onClose,
  top,
}: WritingAssistantWidgetProps) {
  const { can } = useEntitlements()
  const canRef = useRef(can)
  canRef.current = can
  const [phase, setPhase]               = useState<Phase>('picking')
  const [activeAction, setActiveAction] = useState<RewriteAction | 'synonyms' | null>(null)
  const [activeTone, setActiveTone]     = useState<string | null>(null)
  const [activeInstruction, setActiveInstruction] = useState<string | null>(null)
  const [steerNote, setSteerNote]       = useState('')
  const [rewritten, setRewritten]       = useState<string | null>(null)
  const [synonyms, setSynonyms]         = useState<string[]>([])
  const [error, setError]               = useState<string | null>(null)
  const [variantSet, setVariantSet]     = useState<BulletVariantSet | null>(null)
  const [library, setLibrary]           = useState<BulletVariantSet[]>([])
  const [targetLabel, setTargetLabel]   = useState('General')
  const [loadingMessage, setLoadingMessage] = useState('Rewriting…')
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
      setSynonyms([])
      setError(null)
      setVariantSet(null)
      setTargetLabel(jobDescription.trim() ? 'Current job description' : 'General')
    }
  }, [isOpen, selectedText, jobDescription])

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  const callApi = async (action: RewriteAction, tone?: string, instruction?: string) => {
    if (!canRef.current('d06')) return
    setActiveAction(action)
    setActiveTone(tone ?? null)
    setActiveInstruction(instruction ?? null)
    setPhase('loading')
    setLoadingMessage('Rewriting…')
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
    if (!canRef.current('d06')) return
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

  const loadSynonyms = async () => {
    if (!canRef.current('d07')) return
    setActiveAction('synonyms')
    setPhase('loading')
    setLoadingMessage('Finding synonyms…')
    setError(null)
    try {
      const response = await apiClient.suggestSynonyms(selectedText, context || undefined)
      setSynonyms(response.synonyms)
      setPhase('synonyms')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to suggest synonyms')
      setPhase('picking')
    }
  }

  const chooseAction = (key: RewriteAction | 'synonyms') => {
    if (key === 'synonyms') {
      void loadSynonyms()
    } else {
      handleActionClick(key)
    }
  }

  const handleRegenerate = () => {
    if (activeAction && activeAction !== 'synonyms') {
      callApi(activeAction, activeTone ?? undefined, activeInstruction ?? undefined)
    }
  }

  const generateVariants = async () => {
    if (!canRef.current('d10')) return
    setPhase('loading')
    setLoadingMessage('Generating three variants…')
    setError(null)
    try {
      const generated = await apiClient.generateBulletVariants({
        resume_id: resumeId,
        source_text: selectedText,
        job_description: jobDescription.trim() || undefined,
        target_label: targetLabel.trim() || 'General',
      })
      setVariantSet(generated)
      setLibrary((current) => [generated, ...current.filter((item) => item.id !== generated.id)])
      setPhase('variants')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate bullet variants')
      setPhase('variant_setup')
    }
  }

  const openLibrary = async () => {
    setPhase('loading')
    setLoadingMessage('Loading saved variants…')
    setError(null)
    try {
      setLibrary(await apiClient.getBulletVariants(resumeId))
      setPhase('library')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load bullet library')
      setPhase('picking')
    }
  }

  const deleteVariantSet = async (id: string) => {
    try {
      await apiClient.deleteBulletVariantSet(id)
      setLibrary((current) => current.filter((item) => item.id !== id))
      if (variantSet?.id === id) setVariantSet(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to remove variant set')
    }
  }

  const acceptOption = (option: string, feature: 'd06' | 'd07' | 'd10') => {
    if (!canRef.current(feature)) return
    onAccept(option)
  }

  const openVariantSetup = () => {
    if (!canRef.current('d10')) return
    setPhase('variant_setup')
  }

  const normalizedDocument = ' ' + documentLatex.split(/\s+/).join(' ').toLocaleLowerCase() + ' '
  const isAlreadyInDocument = (option: string) =>
    normalizedDocument.includes(' ' + option.split(/\s+/).join(' ').toLocaleLowerCase() + ' ')

  const copyOption = async (option: string) => {
    try {
      await navigator.clipboard.writeText(option)
    } catch {
      setError('Clipboard access is unavailable. Select and copy the text manually.')
    }
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
                  onClick={() => chooseAction(key)}
                  disabled={!can(key === 'synonyms' ? 'd07' : 'd06')}
                  className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-2 text-left transition hover:border-accent/20 hover:bg-accent-soft"
                >
                  <span className="shrink-0 text-accent-strong">{icon}</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[11px] font-semibold text-fg">{label}</span>
                    <span className="block text-[10px] text-fg-3">{description}</span>
                  </span>
                </button>
              ))}
              <button
                onClick={openVariantSetup}
                disabled={!can('d10')}
                className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft px-2.5 py-2 text-left transition hover:brightness-110"
              >
                <span className="shrink-0 text-accent-strong"><Wand2 size={11} /></span>
                <span className="flex-1 min-w-0">
                  <span className="block text-[11px] font-semibold text-fg">Generate 3 variants</span>
                  <span className="block text-[10px] text-fg-3">Review job-specific alternatives side by side</span>
                </span>
              </button>
              <button
                onClick={() => void openLibrary()}
                className="flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-2 text-left transition hover:border-accent/20 hover:bg-accent-soft"
              >
                <span className="shrink-0 text-accent-strong"><BookOpen size={11} /></span>
                <span className="text-[11px] font-semibold text-fg">Saved bullet library</span>
              </button>
            </div>
          )}

          {/* ── Phase: variant setup ──────────────────────────────── */}
          {phase === 'variant_setup' && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPhase('picking')}
                  className="text-[10px] text-fg-3 transition hover:text-fg-2"
                  aria-label="Back to actions"
                >
                  ←
                </button>
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                  Three reviewable variants
                </p>
              </div>
              <label className="block text-[10px] font-semibold uppercase tracking-[0.1em] text-fg-3">
                Library label
                <input
                  value={targetLabel}
                  onChange={(event) => setTargetLabel(event.target.value)}
                  maxLength={200}
                  placeholder="e.g. Acme — Staff Engineer"
                  className="mt-1.5 w-full rounded-[var(--radius-md)] border border-line-2 bg-surface px-2.5 py-2 text-[11px] normal-case tracking-normal text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/30"
                />
              </label>
              <p className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-2 text-[10px] leading-relaxed text-fg-3">
                {jobDescription.trim()
                  ? 'Uses the current job description. Only its fingerprint and this label are saved.'
                  : 'No job description is loaded, so these variants will be general.'}
              </p>
              <button
                onClick={() => void generateVariants()}
                disabled={!can('d10') || !targetLabel.trim()}
                className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent/30 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Wand2 size={11} />
                Generate and save 3 variants
              </button>
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
                  disabled={!can('d06')}
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
                disabled={!can('d06') || !steerNote.trim()}
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
              <span className="text-xs">{loadingMessage}</span>
            </div>
          )}

          {phase === 'synonyms' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <button onClick={() => setPhase('picking')} className="text-[10px] text-fg-3 hover:text-fg-2">
                  ← Actions
                </button>
                <span className="text-[10px] text-fg-3">Choose one replacement</span>
              </div>
              {synonyms.map(synonym => (
                <button
                  key={synonym}
                  type="button"
                  onClick={() => acceptOption(synonym, 'd07')}
                  disabled={!can('d07')}
                  className="flex w-full items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-2 text-left text-[11px] text-fg transition hover:border-accent/20 hover:bg-accent-soft"
                >
                  {synonym}
                  <span className="text-[9px] text-accent-strong">Replace</span>
                </button>
              ))}
              <button
                type="button"
                onClick={() => { void loadSynonyms() }}
                disabled={!can('d07')}
                className="flex w-full items-center justify-center gap-1 text-[10px] text-fg-3 hover:text-fg-2"
              >
                <RefreshCw size={10} /> Regenerate suggestions
              </button>
            </div>
          )}

          {/* ── Phase: generated variants ─────────────────────────── */}
          {phase === 'variants' && variantSet && (
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <button onClick={() => setPhase('picking')} className="text-[10px] text-fg-3 hover:text-fg-2">
                  ← Actions
                </button>
                <span className="truncate text-[10px] font-medium text-accent-strong">{variantSet.target_label}</span>
              </div>
              <p className="rounded-[var(--radius-md)] border border-err/20 bg-err/5 px-2.5 py-2 text-[10px] leading-relaxed text-err/80 line-through decoration-err/40">
                {variantSet.source_text}
              </p>
              {variantSet.options.map((option, index) => {
                const duplicate = isAlreadyInDocument(option)
                return (
                  <div key={option} className="rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                    <p className="text-[9px] font-semibold uppercase tracking-[0.1em] text-fg-3">Option {index + 1}</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-ok">{option}</p>
                    <button
                      onClick={() => acceptOption(option, 'd10')}
                      disabled={!can('d10') || duplicate}
                      title={duplicate ? 'This exact bullet is already present in the document' : undefined}
                      className="mt-2 flex w-full items-center justify-center gap-1 rounded-[var(--radius-md)] bg-ok/15 py-1.5 text-[10px] font-semibold text-ok ring-1 ring-ok/25 transition hover:bg-ok/25 disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      <Check size={10} />
                      {duplicate ? 'Already in document' : 'Apply this variant'}
                    </button>
                  </div>
                )
              })}
              <div className="flex gap-2">
                <button onClick={() => void generateVariants()} disabled={!can('d10')} className="flex flex-1 items-center justify-center gap-1 rounded-[var(--radius-md)] border border-line px-2 py-1.5 text-[10px] text-fg-2 hover:bg-surface-2">
                  <RefreshCw size={10} /> Regenerate
                </button>
                <button onClick={() => void openLibrary()} className="flex flex-1 items-center justify-center gap-1 rounded-[var(--radius-md)] border border-line px-2 py-1.5 text-[10px] text-fg-2 hover:bg-surface-2">
                  <BookOpen size={10} /> Library
                </button>
              </div>
            </div>
          )}

          {/* ── Phase: saved library ──────────────────────────────── */}
          {phase === 'library' && (
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <button onClick={() => setPhase('picking')} className="text-[10px] text-fg-3 hover:text-fg-2">← Actions</button>
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-fg-3">Saved bullet library</p>
              </div>
              {library.length === 0 ? (
                <p className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-5 text-center text-[11px] text-fg-3">
                  No saved variants for this résumé yet.
                </p>
              ) : library.map((savedSet) => {
                const matchesSelection = savedSet.source_text.trim() === selectedText.trim()
                return (
                  <div key={savedSet.id} className="rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[10px] font-semibold text-accent-strong">{savedSet.target_label}</p>
                        <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-fg-3">{savedSet.source_text}</p>
                      </div>
                      <button
                        onClick={() => void deleteVariantSet(savedSet.id)}
                        aria-label={`Delete variants for ${savedSet.target_label}`}
                        className="shrink-0 rounded p-1 text-fg-3 hover:bg-err/10 hover:text-err"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                    <div className="mt-2 space-y-1.5 border-t border-line pt-2">
                      {savedSet.options.map((option, index) => {
                        const duplicate = isAlreadyInDocument(option)
                        return (
                          <div key={option} className="rounded border border-line bg-bg px-2 py-1.5">
                            <p className="text-[10px] leading-relaxed text-fg-2">{index + 1}. {option}</p>
                            {matchesSelection && can('d10') ? (
                              <button
                                onClick={() => acceptOption(option, 'd10')}
                                disabled={!can('d10') || duplicate}
                                className="mt-1 text-[9px] font-semibold text-ok disabled:cursor-not-allowed disabled:text-fg-3"
                              >
                                {duplicate ? 'Already in document' : 'Apply to selection'}
                              </button>
                            ) : (
                              <button onClick={() => void copyOption(option)} className="mt-1 flex items-center gap-1 text-[9px] font-semibold text-fg-3 hover:text-fg-2">
                                <Copy size={9} /> Copy
                              </button>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
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
                  onClick={() => acceptOption(rewritten, 'd06')}
                  disabled={!can('d06')}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/20 py-2 text-[11px] font-semibold text-ok ring-1 ring-ok/30 transition hover:bg-ok/30"
                >
                  <Check size={11} />
                  Accept
                </button>
                <button
                  onClick={handleRegenerate}
                  disabled={!can('d06')}
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
