'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { X, RotateCcw, Maximize2, Minimize2 } from 'lucide-react'
import { DiffEditor } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'
import { toast } from 'sonner'
import type { CheckpointEntry } from '@/lib/api-client'
import { apiClient } from '@/lib/api-client'

interface DiffViewerModalProps {
  resumeId: string
  checkpointA: CheckpointEntry | null   // older (left)
  checkpointB: CheckpointEntry | null   // newer (right) — null = current resume
  currentLatex?: string                 // used when checkpointB is null
  onRestore: (latex: string) => void
  onClose: () => void
  // Parent-diff mode (variant comparison)
  parentLatex?: string
  parentTitle?: string
  variantLatex?: string
  variantTitle?: string
}

interface DiffStats {
  added: number
  removed: number
  changed: number
}

function makeLabel(cp: CheckpointEntry): string {
  if (cp.checkpoint_label) return cp.checkpoint_label
  const type = cp.is_auto_save ? 'Auto-save' : 'AI Optimization'
  return `${type} — ${new Date(cp.created_at).toLocaleString()}`
}

export default function DiffViewerModal({
  resumeId,
  checkpointA,
  checkpointB,
  currentLatex,
  onRestore,
  onClose,
  parentLatex,
  parentTitle,
  variantLatex,
  variantTitle,
}: DiffViewerModalProps) {
  const isParentDiffMode = parentLatex !== undefined
  const [leftLatex, setLeftLatex] = useState<string | null>(null)
  const [rightLatex, setRightLatex] = useState<string | null>(null)
  const [leftLabel, setLeftLabel] = useState('')
  const [rightLabel, setRightLabel] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [diffStats, setDiffStats] = useState<DiffStats | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  // confirmRestore holds the latex string to restore once user confirms
  const [confirmRestore, setConfirmRestore] = useState<string | null>(null)

  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const diffEditorRef = useRef<editor.IStandaloneDiffEditor | null>(null)

  // Clean up diff editor models before React unmounts the component
  useEffect(() => {
    return () => {
      const ed = diffEditorRef.current
      if (ed) {
        try {
          ed.setModel(null)
        } catch {
          // Ignore — already disposed
        }
        diffEditorRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (isParentDiffMode) {
      setLeftLatex(parentLatex!)
      setLeftLabel(parentTitle ?? 'Parent')
      setRightLatex(variantLatex ?? '')
      setRightLabel(variantTitle ?? 'Variant')
      setLoading(false)
      return
    }

    if (!checkpointA) return

    let cancelled = false
    setLoading(true)
    setError(false)
    setDiffStats(null)
    const promises: Promise<void>[] = []

    promises.push(
      apiClient.getCheckpointContent(resumeId, checkpointA.id).then((data) => {
        if (cancelled) return
        setLeftLatex(data.optimized_latex)
        setLeftLabel(makeLabel(checkpointA))
      })
    )

    if (checkpointB) {
      promises.push(
        apiClient.getCheckpointContent(resumeId, checkpointB.id).then((data) => {
          if (cancelled) return
          setRightLatex(data.optimized_latex)
          setRightLabel(makeLabel(checkpointB))
        })
      )
    } else {
      setRightLatex(currentLatex ?? '')
      setRightLabel('Current version')
    }

    Promise.all(promises)
      .catch(() => {
        if (!cancelled) {
          setError(true)
          toast.error('Failed to load version content')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [checkpointA, checkpointB, resumeId, currentLatex, isParentDiffMode, parentLatex, parentTitle, variantLatex, variantTitle])

  // Close on Escape (but not when confirm dialog is open)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (confirmRestore !== null) {
          setConfirmRestore(null)
        } else {
          onCloseRef.current()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [confirmRestore])

  const handleRestoreLeft = useCallback(() => {
    if (leftLatex) setConfirmRestore(leftLatex)
  }, [leftLatex])

  const handleRestoreRight = useCallback(() => {
    if (rightLatex) setConfirmRestore(rightLatex)
  }, [rightLatex])

  const confirmAndRestore = useCallback(() => {
    if (confirmRestore !== null) {
      onRestore(confirmRestore)
      setConfirmRestore(null)
    }
  }, [confirmRestore, onRestore])

  const computeDiffStats = useCallback((ed: editor.IStandaloneDiffEditor) => {
    const changes = ed.getLineChanges()
    if (!changes) return
    let added = 0
    let removed = 0
    for (const change of changes) {
      if (change.modifiedEndLineNumber > 0) {
        added += change.modifiedEndLineNumber - change.modifiedStartLineNumber + 1
      }
      if (change.originalEndLineNumber > 0) {
        removed += change.originalEndLineNumber - change.originalStartLineNumber + 1
      }
    }
    setDiffStats({ added, removed, changed: changes.length })
  }, [])

  if (!checkpointA && !isParentDiffMode) return null

  const modalClasses = isFullscreen
    ? 'relative flex h-screen w-screen flex-col bg-zinc-950'
    : 'relative flex h-[85vh] w-[95vw] max-w-7xl flex-col rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className={modalClasses}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-white">Compare Versions</h2>
            {diffStats && (
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-emerald-400">+{diffStats.added}</span>
                <span className="text-rose-400">−{diffStats.removed}</span>
                <span className="text-zinc-600">·</span>
                <span className="text-zinc-500">{diffStats.changed} section{diffStats.changed !== 1 ? 's' : ''} changed</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRestoreLeft}
              disabled={!leftLatex}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
            >
              <RotateCcw size={12} />
              {isParentDiffMode ? 'Restore to Parent' : 'Restore Left'}
            </button>
            <button
              onClick={handleRestoreRight}
              disabled={!rightLatex || (!checkpointB && !isParentDiffMode)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
            >
              <RotateCcw size={12} />
              {isParentDiffMode ? 'Keep Variant' : 'Restore Right'}
            </button>
            <button
              onClick={() => setIsFullscreen((v) => !v)}
              className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-white"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-white"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Labels */}
        <div className="grid grid-cols-2 border-b border-white/5 text-[11px]">
          <div className="truncate border-r border-white/5 px-4 py-1.5 text-zinc-500">
            {leftLabel}
          </div>
          <div className="truncate px-4 py-1.5 text-zinc-500">
            {rightLabel}
          </div>
        </div>

        {/* Diff editor */}
        <div className="relative flex-1 overflow-hidden">
          {loading ? (
            <div className="flex h-full items-center justify-center">
              <div className="flex items-center gap-2 text-xs text-zinc-500">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-700 border-t-orange-300" />
                Loading versions…
              </div>
            </div>
          ) : error ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-xs text-rose-400">Failed to load version content. Please close and try again.</p>
            </div>
          ) : (
            <DiffEditor
              original={leftLatex ?? ''}
              modified={rightLatex ?? ''}
              language="latex"
              theme="vs-dark"
              onMount={(ed) => {
                diffEditorRef.current = ed
                // Compute stats on first diff render and on every subsequent update
                ed.onDidUpdateDiff(() => computeDiffStats(ed))
              }}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: 'on',
                renderSideBySide: true,
                scrollBeyondLastLine: false,
                wordWrap: 'on',
              }}
            />
          )}

          {/* Restore confirmation overlay */}
          {confirmRestore !== null && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-[2px]">
              <div className="w-80 rounded-xl border border-white/10 bg-zinc-900 p-5 shadow-2xl">
                <p className="text-sm font-semibold text-zinc-100">Restore this version?</p>
                <p className="mt-1.5 text-xs text-zinc-500">
                  This will replace your current editor content. You can undo after closing.
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    onClick={() => setConfirmRestore(null)}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-400 transition hover:border-white/20 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmAndRestore}
                    className="rounded-lg bg-orange-500/20 px-3 py-1.5 text-xs font-semibold text-orange-200 ring-1 ring-orange-400/20 transition hover:bg-orange-500/30"
                  >
                    Restore
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
