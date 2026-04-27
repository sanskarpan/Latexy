'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Layers,
  Loader2,
  Sparkles,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type ReorderSectionsRequest,
  type ReorderSectionsResponse,
} from '@/lib/api-client'

// ------------------------------------------------------------------ //
//  Types                                                              //
// ------------------------------------------------------------------ //

interface SectionReorderPanelProps {
  isOpen: boolean
  onClose: () => void
  getLatex: () => string
  onApply: (newLatex: string) => void
}

type CareerStage = 'entry_level' | 'mid' | 'senior' | 'executive' | ''

// ------------------------------------------------------------------ //
//  Sortable row                                                        //
// ------------------------------------------------------------------ //

function SortableRow({
  id,
  label,
  index,
  isSuggested,
  originalIndex,
}: {
  id: string
  label: string
  index: number
  isSuggested: boolean
  originalIndex: number
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const moved = isSuggested && index !== originalIndex

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-2 rounded-lg px-2 py-2 transition-colors ${
        isDragging ? 'bg-white/[0.08]' : 'hover:bg-white/[0.04]'
      }`}
    >
      <button
        {...attributes}
        {...listeners}
        className="shrink-0 cursor-grab touch-none text-zinc-700 hover:text-zinc-400 active:cursor-grabbing"
        aria-label="Drag to reorder"
      >
        <GripVertical size={14} />
      </button>
      <span className="flex-1 truncate text-[12px] text-zinc-200">{label}</span>
      {moved && (
        <span className="shrink-0 rounded bg-violet-500/20 px-1.5 py-0.5 text-[10px] text-violet-300">
          moved
        </span>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Panel                                                              //
// ------------------------------------------------------------------ //

export default function SectionReorderPanel({
  isOpen,
  onClose,
  getLatex,
  onApply,
}: SectionReorderPanelProps) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReorderSectionsResponse | null>(null)
  const [userOrder, setUserOrder] = useState<string[]>([])
  const [careerStage, setCareerStage] = useState<CareerStage>('')
  const [jd, setJd] = useState('')
  const [jdOpen, setJdOpen] = useState(false)
  const [diffOpen, setDiffOpen] = useState(false)

  // Reset on open
  useEffect(() => {
    if (!isOpen) return
    setResult(null)
    setUserOrder([])
    setLoading(false)
    setJd('')
    setJdOpen(false)
    setDiffOpen(false)
  }, [isOpen])

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleSuggest = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const body: ReorderSectionsRequest = { resume_latex: latex }
      if (careerStage) body.career_stage = careerStage
      if (jd.trim()) body.job_description = jd.trim()

      const res = await apiClient.reorderSections(body)
      setResult(res)
      setUserOrder(res.suggested_order)

      if (res.current_order.length === 0) {
        toast.info('No \\section{} blocks found — nothing to reorder')
      } else if (res.cached) {
        toast.success('Loaded from cache')
      } else {
        toast.success('AI suggestion ready')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Suggestion failed')
    } finally {
      setLoading(false)
    }
  }, [getLatex, careerStage, jd])

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (over && active.id !== over.id) {
      setUserOrder((prev) => {
        const oldIdx = prev.indexOf(String(active.id))
        const newIdx = prev.indexOf(String(over.id))
        return arrayMove(prev, oldIdx, newIdx)
      })
    }
  }

  async function handleApply() {
    if (!result) return

    const ordersMatch = JSON.stringify(userOrder) === JSON.stringify(result.suggested_order)

    if (ordersMatch) {
      // AI order unchanged — use the pre-computed latex directly (no extra round-trip)
      onApply(result.reordered_latex)
      toast.success('Section order applied')
      onClose()
      return
    }

    // User dragged sections to a custom order — use forced_order to bypass the LLM
    // and get the LaTeX reconstructed with the exact order the user chose.
    setLoading(true)
    try {
      const res = await apiClient.reorderSections({
        resume_latex: getLatex(),
        forced_order: userOrder,
      })
      onApply(res.reordered_latex)
      toast.success('Section order applied')
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Apply failed')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-xl rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* ── Header ── */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-violet-500/15">
              <Layers size={13} className="text-violet-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">AI Section Reordering</h2>
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
            AI recommends the optimal section order for your resume. Drag to adjust, then apply.
          </p>

          {/* ── Options ── */}
          <div className="space-y-3">
            {/* Career stage */}
            <div>
              <label className="mb-1 block text-[11px] font-medium text-zinc-500">
                Career stage (optional)
              </label>
              <select
                value={careerStage}
                onChange={(e) => setCareerStage(e.target.value as CareerStage)}
                className="w-full rounded-lg border border-white/[0.06] bg-black/30 px-3 py-2 text-[12px] text-zinc-200 focus:border-violet-500 focus:outline-none"
              >
                <option value="">Auto-detect</option>
                <option value="entry_level">Entry-level / Student</option>
                <option value="mid">Mid-level</option>
                <option value="senior">Senior</option>
                <option value="executive">Executive / Director</option>
              </select>
            </div>

            {/* JD accordion */}
            <div className="rounded-lg border border-white/[0.06] bg-black/20">
              <button
                onClick={() => setJdOpen((o) => !o)}
                className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
              >
                <span>Job description <span className="normal-case text-zinc-600">(optional — improves suggestion)</span></span>
                {jdOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              </button>
              {jdOpen && (
                <div className="px-3 pb-3">
                  <textarea
                    value={jd}
                    onChange={(e) => setJd(e.target.value)}
                    rows={5}
                    maxLength={10000}
                    placeholder="Paste the job description here…"
                    className="w-full resize-none rounded-lg border border-white/[0.06] bg-black/30 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 focus:border-violet-500 focus:outline-none"
                  />
                  <p className="mt-0.5 text-right text-[10px] text-zinc-700">
                    {jd.length.toLocaleString()} / 10,000
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ── Suggest button ── */}
          <button
            onClick={handleSuggest}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.06] disabled:opacity-50"
          >
            {loading ? (
              <><Loader2 size={12} className="animate-spin" /> Thinking…</>
            ) : (
              <><Sparkles size={12} className="text-violet-400" /> Suggest Section Order</>
            )}
          </button>

          {/* ── Results ── */}
          {result && result.current_order.length > 0 && (
            <div className="space-y-3">
              {/* Rationale */}
              <div className="rounded-lg border border-white/[0.06] bg-violet-500/[0.04] px-3 py-2">
                <p className="text-[11px] leading-relaxed text-zinc-400">{result.rationale}</p>
                {result.cached && (
                  <span className="mt-1 inline-block rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-500">
                    cached
                  </span>
                )}
              </div>

              {/* Two-column comparison */}
              <div className="grid grid-cols-2 gap-3">
                {/* Current order (static) */}
                <div>
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                    Current
                  </p>
                  <div className="space-y-0.5 rounded-lg border border-white/[0.06] bg-black/20 p-2">
                    {result.current_order.map((name, i) => (
                      <div
                        key={name}
                        className="flex items-center gap-1.5 rounded px-2 py-1.5"
                      >
                        <span className="w-4 shrink-0 text-[10px] text-zinc-700">{i + 1}</span>
                        <span className="truncate text-[12px] text-zinc-400">{name}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* AI suggestion (drag-and-drop) */}
                <div>
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                    AI Suggestion <span className="normal-case text-zinc-700">(drag to adjust)</span>
                  </p>
                  <div className="rounded-lg border border-white/[0.06] bg-black/20 p-1">
                    <DndContext
                      sensors={sensors}
                      collisionDetection={closestCenter}
                      onDragEnd={handleDragEnd}
                    >
                      <SortableContext items={userOrder} strategy={verticalListSortingStrategy}>
                        {userOrder.map((name, i) => (
                          <SortableRow
                            key={name}
                            id={name}
                            label={name}
                            index={i}
                            isSuggested
                            originalIndex={result.current_order.indexOf(name)}
                          />
                        ))}
                      </SortableContext>
                    </DndContext>
                  </div>
                </div>
              </div>

              {/* Diff preview */}
              <div className="rounded-lg border border-white/[0.06] bg-black/20">
                <button
                  onClick={() => setDiffOpen((o) => !o)}
                  className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
                >
                  <span>Diff preview <span className="normal-case text-zinc-700">(first 12 lines of each)</span></span>
                  {diffOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
                {diffOpen && (
                  <div className="grid grid-cols-2 gap-0 divide-x divide-white/[0.06] px-0 pb-3 pt-0">
                    <div className="px-3">
                      <p className="mb-1 text-[10px] text-zinc-600">Current</p>
                      <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-zinc-500">
                        {result.current_order
                          .map((n) => `\\section{${n}}`)
                          .join('\n...\n')
                          .split('\n')
                          .slice(0, 12)
                          .join('\n')}
                      </pre>
                    </div>
                    <div className="px-3">
                      <p className="mb-1 text-[10px] text-zinc-600">Reordered</p>
                      <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-zinc-500">
                        {userOrder
                          .map((n) => `\\section{${n}}`)
                          .join('\n...\n')
                          .split('\n')
                          .slice(0, 12)
                          .join('\n')}
                      </pre>
                    </div>
                  </div>
                )}
              </div>

              {/* Warning if order unchanged */}
              {JSON.stringify(userOrder) === JSON.stringify(result.current_order) && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.04] px-3 py-2">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-400" />
                  <p className="text-[11px] text-amber-400/80">
                    The AI suggestion matches your current order — no changes will be made.
                  </p>
                </div>
              )}

              {/* Apply button */}
              <button
                onClick={handleApply}
                disabled={loading || JSON.stringify(userOrder) === JSON.stringify(result.current_order)}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 py-2 text-xs font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {loading ? (
                  <><Loader2 size={12} className="animate-spin" /> Applying…</>
                ) : (
                  'Apply Reordering'
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
