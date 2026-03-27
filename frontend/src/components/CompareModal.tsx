'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize2, Minimize2, RotateCcw, X } from 'lucide-react'
import { DiffEditor } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

interface DiffStats {
  added: number
  removed: number
  changed: number
}

interface Props {
  originalLatex: string
  optimizedLatex: string
  onClose: () => void
  /** If provided, shows a "Restore Original" button */
  onRestore?: (latex: string) => void
}

export default function CompareModal({ originalLatex, optimizedLatex, onClose, onRestore }: Props) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [diffStats, setDiffStats] = useState<DiffStats | null>(null)
  const diffEditorRef = useRef<editor.IStandaloneDiffEditor | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  // Clean up diff editor models on unmount
  useEffect(() => {
    return () => {
      const ed = diffEditorRef.current
      if (ed) {
        try {
          ed.setModel(null)
        } catch {
          // already disposed
        }
        diffEditorRef.current = null
      }
    }
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const computeDiffStats = useCallback((ed: editor.IStandaloneDiffEditor) => {
    const changes = ed.getLineChanges()
    if (!changes) return
    let added = 0
    let removed = 0
    for (const change of changes) {
      if (change.modifiedEndLineNumber > 0)
        added += change.modifiedEndLineNumber - change.modifiedStartLineNumber + 1
      if (change.originalEndLineNumber > 0)
        removed += change.originalEndLineNumber - change.originalStartLineNumber + 1
    }
    setDiffStats({ added, removed, changed: changes.length })
  }, [])

  const modalClasses = isFullscreen
    ? 'relative flex h-screen w-screen flex-col bg-zinc-950'
    : 'relative flex h-[85vh] w-[95vw] max-w-7xl flex-col rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className={modalClasses}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-white">Before / After Optimization</h2>
            {diffStats && (
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-emerald-400">+{diffStats.added}</span>
                <span className="text-rose-400">−{diffStats.removed}</span>
                <span className="text-zinc-600">·</span>
                <span className="text-zinc-500">
                  {diffStats.changed} section{diffStats.changed !== 1 ? 's' : ''} changed
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {onRestore && (
              <button
                onClick={() => onRestore(originalLatex)}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-white"
              >
                <RotateCcw size={12} />
                Restore Original
              </button>
            )}
            <button
              type="button"
              onClick={() => setIsFullscreen((v) => !v)}
              className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-white"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
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

        {/* Column labels */}
        <div className="grid grid-cols-2 border-b border-white/5 text-[11px]">
          <div className="truncate border-r border-white/5 px-4 py-1.5 text-zinc-500">
            Before Optimization
          </div>
          <div className="truncate px-4 py-1.5 text-zinc-500">After Optimization</div>
        </div>

        {/* Diff editor */}
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <DiffEditor
            original={originalLatex}
            modified={optimizedLatex}
            language="latex"
            theme="vs-dark"
            onMount={(ed) => {
              diffEditorRef.current = ed
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
        </div>
      </div>
    </div>
  )
}
