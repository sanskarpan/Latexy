'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { X, RotateCcw } from 'lucide-react'
import { DiffEditor, type Monaco } from '@monaco-editor/react'
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
}: DiffViewerModalProps) {
  const [leftLatex, setLeftLatex] = useState<string | null>(null)
  const [rightLatex, setRightLatex] = useState<string | null>(null)
  const [leftLabel, setLeftLabel] = useState('')
  const [rightLabel, setRightLabel] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const diffEditorRef = useRef<editor.IStandaloneDiffEditor | null>(null)

  // Clean up diff editor models before React unmounts the component
  // This prevents "TextModel got disposed before DiffEditorWidget model got reset"
  useEffect(() => {
    return () => {
      const ed = diffEditorRef.current
      if (ed) {
        try {
          // Reset the diff editor's model to null before disposal
          ed.setModel(null)
        } catch {
          // Ignore — already disposed
        }
        diffEditorRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!checkpointA) return

    let cancelled = false
    setLoading(true)
    setError(false)
    const promises: Promise<void>[] = []

    // Fetch left side (checkpointA)
    promises.push(
      apiClient.getCheckpointContent(resumeId, checkpointA.id).then((data) => {
        if (cancelled) return
        setLeftLatex(data.optimized_latex)
        setLeftLabel(makeLabel(checkpointA))
      })
    )

    // Fetch right side
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
  }, [checkpointA, checkpointB, resumeId, currentLatex])

  // Close on Escape — use ref to avoid re-registering on every render
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleRestoreLeft = useCallback(() => {
    if (leftLatex) onRestore(leftLatex)
  }, [leftLatex, onRestore])

  const handleRestoreRight = useCallback(() => {
    if (rightLatex) onRestore(rightLatex)
  }, [rightLatex, onRestore])

  if (!checkpointA) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="relative flex h-[85vh] w-[95vw] max-w-7xl flex-col rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Compare Versions</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRestoreLeft}
              disabled={!leftLatex}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
            >
              <RotateCcw size={12} />
              Restore Left
            </button>
            <button
              onClick={handleRestoreRight}
              disabled={!rightLatex || !checkpointB}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
            >
              <RotateCcw size={12} />
              Restore Right
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
        <div className="flex-1 overflow-hidden">
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
              onMount={(editor) => { diffEditorRef.current = editor }}
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
        </div>
      </div>
    </div>
  )
}
