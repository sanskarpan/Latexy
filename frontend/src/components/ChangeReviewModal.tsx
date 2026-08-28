'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Loader2, Pencil, RotateCcw, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ChangeHunk } from '@/lib/api-client'

/**
 * Per-change accept/reject/edit review (input-driven optimization, F2-P0).
 * "AI drafts, you direct and approve": segments the original→optimized diff into
 * discrete hunks, lets the user accept/reject/edit each one, then applies only
 * the accepted set and hands the reconstructed LaTeX back to the parent to load
 * into the editor and recompile.
 *
 * The apply is done client-agnostically via the server (deterministic
 * reconstruction), so a locally-edited ``new_text`` is honoured by sending the
 * edited hunk in the apply payload.
 */

type HunkState = {
  accepted: boolean
  newText: string // editable; defaults to hunk.new_text
  editing: boolean
}

const KIND_META: Record<ChangeHunk['kind'], { label: string; cls: string }> = {
  modified: { label: 'Modified', cls: 'bg-warn/15 text-warn ring-warn/20' },
  added: { label: 'Added', cls: 'bg-ok/15 text-ok ring-ok/20' },
  removed: { label: 'Removed', cls: 'bg-err/15 text-err ring-err/20' },
}

export default function ChangeReviewModal({
  originalLatex,
  optimizedLatex,
  changeReasons,
  onApply,
  onClose,
}: {
  originalLatex: string
  optimizedLatex: string
  changeReasons?: Array<{ section?: string; change_type?: string; reason?: string }>
  onApply: (latex: string) => boolean | void | Promise<boolean | void>
  onClose: () => void
}) {
  const [hunks, setHunks] = useState<ChangeHunk[] | null>(null)
  const [state, setState] = useState<Record<string, HunkState>>({})
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.segmentChanges({
          original_latex: originalLatex,
          optimized_latex: optimizedLatex,
          change_reasons: changeReasons,
        })
        if (cancelled) return
        setHunks(res.hunks)
        // Every change starts accepted (the optimized doc is the default), so
        // "Apply" with no edits reproduces the one-shot result.
        const init: Record<string, HunkState> = {}
        for (const h of res.hunks) init[h.id] = { accepted: true, newText: h.new_text, editing: false }
        setState(init)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to compute changes')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [originalLatex, optimizedLatex, changeReasons])

  const acceptedCount = useMemo(
    () => Object.values(state).filter((s) => s.accepted).length,
    [state]
  )

  const setAll = useCallback((accepted: boolean) => {
    setState((prev) => {
      const next: Record<string, HunkState> = {}
      for (const [id, s] of Object.entries(prev)) next[id] = { ...s, accepted }
      return next
    })
  }, [])

  const toggle = (id: string) =>
    setState((prev) => ({ ...prev, [id]: { ...prev[id], accepted: !prev[id].accepted } }))

  const startEdit = (id: string) =>
    setState((prev) => ({ ...prev, [id]: { ...prev[id], editing: true, accepted: true } }))

  const setEditText = (id: string, newText: string) =>
    setState((prev) => ({ ...prev, [id]: { ...prev[id], newText } }))

  const resetEdit = (id: string, original: string) =>
    setState((prev) => ({ ...prev, [id]: { ...prev[id], newText: original, editing: false } }))

  const handleApply = async () => {
    if (!hunks) return
    setApplying(true)
    try {
      // Send hunks with any locally-edited new_text so the server honours edits.
      const payloadHunks = hunks.map((h) => ({ ...h, new_text: state[h.id]?.newText ?? h.new_text }))
      const acceptedIds = hunks.filter((h) => state[h.id]?.accepted).map((h) => h.id)
      const res = await apiClient.applyChanges({
        original_latex: originalLatex,
        hunks: payloadHunks,
        accepted_ids: acceptedIds,
      })
      const applied = await onApply(res.latex)
      if (applied === false) return
      toast.success(
        acceptedIds.length === hunks.length
          ? 'Applied all changes'
          : `Applied ${acceptedIds.length} of ${hunks.length} changes`
      )
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to apply changes')
    } finally {
      setApplying(false)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.97, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97 }}
          className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-fg">Review changes</h2>
              <p className="mt-0.5 text-[11px] text-fg-3">
                Accept, reject, or edit each suggestion. Only accepted changes are applied.
              </p>
            </div>
            <button onClick={onClose} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg">
              <X size={16} />
            </button>
          </div>

          {/* Toolbar */}
          {hunks && hunks.length > 0 && (
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-2.5">
              <span className="text-[11px] text-fg-3">
                {acceptedCount} of {hunks.length} accepted
              </span>
              <div className="flex gap-2">
                <button onClick={() => setAll(true)} className="rounded-[var(--radius-md)] px-2 py-1 text-[11px] font-medium text-ok transition hover:bg-ok/10">
                  Accept all
                </button>
                <button onClick={() => setAll(false)} className="rounded-[var(--radius-md)] px-2 py-1 text-[11px] font-medium text-fg-2 transition hover:bg-surface-2">
                  Reject all
                </button>
              </div>
            </div>
          )}

          {/* Body */}
          <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-fg-3">
                <Loader2 size={16} className="animate-spin" /> Computing changes…
              </div>
            )}
            {error && !loading && (
              <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/10 px-4 py-3 text-sm text-err">{error}</div>
            )}
            {!loading && !error && hunks && hunks.length === 0 && (
              <div className="py-16 text-center text-sm text-fg-3">
                No substantive changes to review — the optimized result matches your resume.
              </div>
            )}
            {!loading && !error && hunks && hunks.length > 0 && (
              <ul className="space-y-3">
                {hunks.map((h) => {
                  const s = state[h.id]
                  if (!s) return null
                  const meta = KIND_META[h.kind]
                  return (
                    <li
                      key={h.id}
                      className={`rounded-[var(--radius-lg)] border p-3 transition ${
                        s.accepted ? 'border-line bg-surface' : 'border-line bg-transparent opacity-60'
                      }`}
                    >
                      <div className="mb-2 flex items-center gap-2">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${meta.cls}`}>
                          {meta.label}
                        </span>
                        {h.section && <span className="text-[11px] text-fg-3">{h.section}</span>}
                        <div className="ml-auto flex items-center gap-1">
                          <button
                            onClick={() => startEdit(h.id)}
                            title="Edit"
                            className="rounded-[var(--radius-md)] p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
                          >
                            <Pencil size={12} />
                          </button>
                          <button
                            onClick={() => toggle(h.id)}
                            title={s.accepted ? 'Reject' : 'Accept'}
                            className={`rounded-[var(--radius-md)] p-1 transition ${
                              s.accepted ? 'text-ok hover:bg-ok/10' : 'text-fg-3 hover:bg-surface-2'
                            }`}
                          >
                            {s.accepted ? <Check size={13} /> : <X size={13} />}
                          </button>
                        </div>
                      </div>

                      {/* Diff preview */}
                      {h.original_text.trim() && (
                        <pre className="mb-1 overflow-x-auto whitespace-pre-wrap rounded-[var(--radius-md)] bg-err/[0.06] px-2 py-1 text-[11px] leading-relaxed text-err">
                          <code>- {h.original_text.trim()}</code>
                        </pre>
                      )}
                      {s.editing ? (
                        <div>
                          <textarea
                            value={s.newText}
                            onChange={(e) => setEditText(h.id, e.target.value)}
                            className="scrollbar-subtle h-24 w-full resize-none rounded-[var(--radius-md)] border border-accent/30 bg-bg px-2 py-1 text-[11px] leading-relaxed text-fg outline-none focus:border-accent"
                          />
                          <button
                            onClick={() => resetEdit(h.id, h.new_text)}
                            className="mt-1 flex items-center gap-1 text-[10px] text-fg-3 transition hover:text-fg-2"
                          >
                            <RotateCcw size={10} /> Reset to suggestion
                          </button>
                        </div>
                      ) : (
                        s.newText.trim() && (
                          <pre className="overflow-x-auto whitespace-pre-wrap rounded-[var(--radius-md)] bg-ok/[0.06] px-2 py-1 text-[11px] leading-relaxed text-ok">
                            <code>+ {s.newText.trim()}</code>
                          </pre>
                        )
                      )}

                      {h.rationale && (
                        <p className="mt-1.5 text-[10px] italic text-fg-3">{h.rationale}</p>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-line px-5 py-3.5">
            <button onClick={onClose} className="text-xs font-semibold text-fg-2 transition hover:text-fg">
              Cancel
            </button>
            <button
              onClick={handleApply}
              disabled={applying || loading || !hunks || hunks.length === 0}
              className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {applying ? 'Applying…' : `Apply ${acceptedCount} change${acceptedCount === 1 ? '' : 's'}`}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
