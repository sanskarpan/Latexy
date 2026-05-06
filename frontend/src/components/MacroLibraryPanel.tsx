'use client'

/**
 * Keyboard Macro Library Panel (Feature 83F)
 *
 * Shows saved macros, lets the user record new ones, replay existing ones,
 * and delete unwanted ones.  Passed the current Monaco editor ref so
 * MacroRecorder / MacroPlayer can hook directly into the editor instance.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Keyboard, Play, Square, Trash2, Plus, Loader2 } from 'lucide-react'
import type * as Monaco from 'monaco-editor'
import { toast } from 'sonner'
import { apiClient, type MacroDetail, type MacroSummary } from '@/lib/api-client'
import { MacroRecorder } from '@/lib/macros/macro-recorder'
import { MacroPlayer } from '@/lib/macros/macro-player'
import type { MacroAction } from '@/lib/macros/macro-types'
import type { LaTeXEditorRef } from '@/components/LaTeXEditor'

interface Props {
  editorRef: React.RefObject<LaTeXEditorRef | null>
}

export default function MacroLibraryPanel({ editorRef }: Props) {
  const [macros, setMacros] = useState<MacroSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [recording, setRecording] = useState(false)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const recorderRef = useRef<MacroRecorder | null>(null)
  const playerRef = useRef<MacroPlayer>(new MacroPlayer())

  // ── Load macros on mount ────────────────────────────────────────────────────

  const fetchMacros = useCallback(async () => {
    try {
      const data = await apiClient.getMacros()
      setMacros(data)
    } catch {
      // unauthenticated or network error — silently empty list
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMacros()
  }, [fetchMacros])

  // ── Recording ───────────────────────────────────────────────────────────────

  const getMonacoEditor = (): Monaco.editor.IStandaloneCodeEditor | null => {
    return editorRef.current?.getEditor() ?? null
  }

  const handleToggleRecord = useCallback(async () => {
    if (recording) {
      // Stop and save
      const actions = recorderRef.current?.stop() ?? []
      recorderRef.current = null
      setRecording(false)

      if (actions.length === 0) {
        toast.error('No actions recorded')
        return
      }

      const name = window.prompt('Name this macro:', `Macro ${macros.length + 1}`)
      if (!name?.trim()) return

      try {
        const created = await apiClient.createMacro({
          name: name.trim(),
          actions: actions as unknown[],
        })
        setMacros((prev) => [
          {
            id: created.id,
            name: created.name,
            description: created.description,
            shortcut: created.shortcut,
            created_at: created.created_at,
            updated_at: created.updated_at,
          },
          ...prev,
        ])
        toast.success(`Macro "${name.trim()}" saved`)
      } catch {
        toast.error('Failed to save macro')
      }
    } else {
      // Start recording
      const editor = getMonacoEditor()
      if (!editor) {
        toast.error('Editor not ready')
        return
      }
      const recorder = new MacroRecorder(editor)
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
      toast.info('Recording… click Stop when done')
    }
  }, [recording, macros.length, editorRef]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Playback ────────────────────────────────────────────────────────────────

  const handlePlay = useCallback(
    async (macroId: string) => {
      if (playerRef.current.isPlaying) {
        toast.error('Already playing a macro')
        return
      }
      const editor = getMonacoEditor()
      if (!editor) {
        toast.error('Editor not ready')
        return
      }

      setPlayingId(macroId)
      try {
        const detail: MacroDetail = await apiClient.getMacro(macroId)
        await playerRef.current.play(detail.actions as MacroAction[], editor)
      } catch (err) {
        toast.error('Macro playback failed')
        console.error(err)
      } finally {
        setPlayingId(null)
      }
    },
    [editorRef], // eslint-disable-line react-hooks/exhaustive-deps
  )

  // ── Deletion ────────────────────────────────────────────────────────────────

  const handleDelete = useCallback(async (macroId: string, name: string) => {
    if (!window.confirm(`Delete macro "${name}"?`)) return
    setDeletingId(macroId)
    try {
      await apiClient.deleteMacro(macroId)
      setMacros((prev) => prev.filter((m) => m.id !== macroId))
      toast.success('Macro deleted')
    } catch {
      toast.error('Failed to delete macro')
    } finally {
      setDeletingId(null)
    }
  }, [])

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Macros
        </span>
        <button
          onClick={handleToggleRecord}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition ${
            recording
              ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30'
              : 'bg-violet-500/20 text-violet-300 hover:bg-violet-500/30'
          }`}
        >
          {recording ? (
            <>
              <Square size={11} />
              Stop
            </>
          ) : (
            <>
              <Plus size={11} />
              Record
            </>
          )}
        </button>
      </div>

      {/* Recording indicator */}
      {recording && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-400" />
          <span className="text-[11px] text-red-300">Recording in progress…</span>
        </div>
      )}

      {/* Macro list */}
      {loading ? (
        <div className="flex flex-col items-center gap-2 py-8 text-zinc-600">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-[11px]">Loading macros…</span>
        </div>
      ) : macros.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-10 text-zinc-600">
          <Keyboard size={28} strokeWidth={1.5} />
          <p className="text-center text-[11px] leading-relaxed">
            No macros yet.
            <br />
            Click <strong className="text-zinc-400">Record</strong> to capture editor actions.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {macros.map((macro) => (
            <li
              key={macro.id}
              className="group flex items-start gap-2 rounded-lg border border-white/[0.04] bg-white/[0.02] px-3 py-2.5 transition hover:border-white/[0.08] hover:bg-white/[0.04]"
            >
              <div className="flex-1 min-w-0">
                <p className="truncate text-[12px] font-medium text-zinc-200">{macro.name}</p>
                {macro.description && (
                  <p className="mt-0.5 truncate text-[10px] text-zinc-500">{macro.description}</p>
                )}
                {macro.shortcut && (
                  <kbd className="mt-1 inline-block rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400">
                    {macro.shortcut}
                  </kbd>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                {/* Play button */}
                <button
                  onClick={() => handlePlay(macro.id)}
                  disabled={playingId !== null || recording}
                  title="Play macro"
                  className="rounded p-1 text-zinc-500 transition hover:bg-emerald-500/20 hover:text-emerald-300 disabled:pointer-events-none disabled:opacity-40"
                >
                  {playingId === macro.id ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Play size={13} />
                  )}
                </button>

                {/* Delete button */}
                <button
                  onClick={() => handleDelete(macro.id, macro.name)}
                  disabled={deletingId === macro.id || recording}
                  title="Delete macro"
                  className="rounded p-1 text-zinc-500 transition hover:bg-red-500/20 hover:text-red-300 disabled:pointer-events-none disabled:opacity-40"
                >
                  {deletingId === macro.id ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Trash2 size={13} />
                  )}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
