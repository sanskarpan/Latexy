'use client'

/**
 * Macro Library Panel — Feature 83.
 *
 * Props:
 *   editor — Monaco editor instance (or null when WYSIWYG mode is active)
 *   onMacrosChange — called whenever the macro list changes so the parent can
 *                    re-register shortcuts
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Circle,
  Edit2,
  Keyboard,
  Loader2,
  Play,
  Plus,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import type * as Monaco from 'monaco-editor'
import { apiClient, type MacroResponse } from '@/lib/api-client'
import { MacroRecorder } from '@/lib/macros/macro-recorder'
import { MacroPlayer } from '@/lib/macros/macro-player'
import type { MacroAction } from '@/lib/macros/macro-types'

type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

interface Props {
  editor: IStandaloneCodeEditor | null
  onMacrosChange?: (macros: MacroResponse[]) => void
}

// ── Edit / rename modal ────────────────────────────────────────────────────────

function EditModal({
  macro,
  onSave,
  onClose,
}: {
  macro: MacroResponse
  onSave: (name: string, description: string, shortcut: string) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState(macro.name)
  const [description, setDescription] = useState(macro.description ?? '')
  const [shortcut, setShortcut] = useState(macro.shortcut ?? '')
  const [saving, setSaving] = useState(false)

  const captureShortcut = (e: React.KeyboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const parts: string[] = []
    if (e.ctrlKey || e.metaKey) parts.push('ctrl')
    if (e.altKey) parts.push('alt')
    if (e.shiftKey) parts.push('shift')
    const key = e.key.toLowerCase()
    if (!['control', 'alt', 'shift', 'meta'].includes(key)) parts.push(key)
    if (parts.length > 1) setShortcut(parts.join('+'))
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave(name.trim(), description.trim(), shortcut)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-80 rounded-xl border border-white/[0.08] bg-zinc-900 p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[12px] font-semibold text-zinc-200">Edit Macro</span>
          <button onClick={onClose} className="text-zinc-600 hover:text-zinc-300">
            <X size={14} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-[10px] text-zinc-600">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-white/[0.06] bg-black/30 px-2 py-1 text-[11px] text-zinc-200 outline-none focus:border-violet-500/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] text-zinc-600">Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded border border-white/[0.06] bg-black/30 px-2 py-1 text-[11px] text-zinc-200 outline-none focus:border-violet-500/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] text-zinc-600">
              Shortcut (press keys to capture)
            </label>
            <input
              readOnly
              value={shortcut}
              onKeyDown={captureShortcut}
              placeholder="e.g. ctrl+shift+1"
              className="w-full rounded border border-white/[0.06] bg-black/30 px-2 py-1 text-[11px] text-zinc-200 outline-none focus:border-violet-500/30"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded px-3 py-1 text-[10px] text-zinc-600 hover:text-zinc-300"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="flex items-center gap-1 rounded bg-violet-500/20 px-3 py-1 text-[10px] text-violet-300 ring-1 ring-violet-400/20 hover:bg-violet-500/30 disabled:opacity-40"
          >
            {saving && <Loader2 size={10} className="animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const recorder = new MacroRecorder()
const player = new MacroPlayer()

export default function MacroLibraryPanel({ editor, onMacrosChange }: Props) {
  const [macros, setMacros] = useState<MacroResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [recording, setRecording] = useState(false)
  const [recordingName, setRecordingName] = useState('')
  const [editingMacro, setEditingMacro] = useState<MacroResponse | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)

  const fetchMacros = useCallback(async () => {
    try {
      const data = await apiClient.getMacros()
      setMacros(data)
      onMacrosChange?.(data)
    } catch {
      // silently ignore if not authenticated
    } finally {
      setLoading(false)
    }
  }, [onMacrosChange])

  useEffect(() => {
    fetchMacros()
  }, [fetchMacros])

  const startRecording = () => {
    if (!editor) {
      toast.error('Switch to Source mode to record macros')
      return
    }
    recorder.startRecording(editor)
    setRecording(true)
    setTimeout(() => nameInputRef.current?.focus(), 50)
    toast('Recording started — perform your actions in the editor', { icon: '⏺' })
  }

  const stopRecording = async () => {
    const actions = recorder.stopRecording()
    setRecording(false)
    if (actions.length === 0) {
      toast.error('No actions recorded')
      return
    }
    const name = recordingName.trim() || `Macro ${macros.length + 1}`
    try {
      const macro = await apiClient.createMacro({
        name,
        actions: actions as unknown as Record<string, unknown>[],
      })
      const updated = [macro, ...macros]
      setMacros(updated)
      onMacrosChange?.(updated)
      setRecordingName('')
      toast.success(`"${name}" saved (${actions.length} actions)`)
    } catch {
      toast.error('Failed to save macro')
    }
  }

  const cancelRecording = () => {
    recorder.cancelRecording()
    setRecording(false)
    setRecordingName('')
  }

  const playMacro = async (macro: MacroResponse) => {
    if (!editor) {
      toast.error('Switch to Source mode to play macros')
      return
    }
    setPlayingId(macro.id)
    try {
      await player.play(
        {
          id: macro.id,
          name: macro.name,
          description: macro.description ?? undefined,
          shortcut: macro.shortcut ?? undefined,
          actions: macro.actions as unknown as MacroAction[],
        },
        editor,
      )
    } catch {
      toast.error('Macro playback failed')
    } finally {
      setPlayingId(null)
    }
  }

  const deleteMacro = async (macro: MacroResponse) => {
    try {
      await apiClient.deleteMacro(macro.id)
      const updated = macros.filter((m) => m.id !== macro.id)
      setMacros(updated)
      onMacrosChange?.(updated)
      toast.success(`"${macro.name}" deleted`)
    } catch {
      toast.error('Failed to delete macro')
    }
  }

  const saveMacroEdit = async (name: string, description: string, shortcut: string) => {
    if (!editingMacro) return
    const updated = await apiClient.updateMacro(editingMacro.id, {
      name,
      description: description || undefined,
      shortcut: shortcut || undefined,
    })
    const list = macros.map((m) => (m.id === updated.id ? updated : m))
    setMacros(list)
    onMacrosChange?.(list)
    toast.success('Macro updated')
    setEditingMacro(null)
  }

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Keyboard size={11} className="text-zinc-500" />
          <span className="text-[11px] font-semibold text-zinc-300">Keyboard Macros</span>
        </div>
        {!recording && (
          <button
            onClick={startRecording}
            className="flex items-center gap-1 rounded bg-violet-500/15 px-2 py-1 text-[9px] font-medium text-violet-300 ring-1 ring-violet-400/20 transition hover:bg-violet-500/25"
          >
            <Plus size={9} />
            Record New
          </button>
        )}
      </div>

      {/* Recording controls */}
      {recording && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <Circle size={8} className="animate-pulse fill-red-400 text-red-400" />
            <span className="text-[10px] font-medium text-red-400">Recording…</span>
          </div>
          <input
            ref={nameInputRef}
            value={recordingName}
            onChange={(e) => setRecordingName(e.target.value)}
            placeholder="Macro name (optional)"
            className="mb-2 w-full rounded border border-white/[0.06] bg-black/30 px-2 py-1 text-[10px] text-zinc-200 outline-none focus:border-violet-500/30"
          />
          <div className="flex gap-2">
            <button
              onClick={stopRecording}
              className="flex flex-1 items-center justify-center gap-1 rounded bg-red-500/20 py-1 text-[9px] font-medium text-red-300 ring-1 ring-red-400/20 hover:bg-red-500/30"
            >
              <Square size={9} />
              Stop & Save
            </button>
            <button
              onClick={cancelRecording}
              className="rounded px-2 py-1 text-[9px] text-zinc-600 hover:text-zinc-400"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Macro list */}
      <div className="flex-1 space-y-1.5 overflow-y-auto">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 size={14} className="animate-spin text-zinc-700" />
          </div>
        ) : macros.length === 0 ? (
          <div className="py-8 text-center text-[10px] text-zinc-700">
            No macros yet.
            <br />
            Click "Record New" to capture a sequence of editor actions.
          </div>
        ) : (
          macros.map((macro) => (
            <div
              key={macro.id}
              className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-2.5 transition hover:border-white/[0.08]"
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <span className="truncate text-[11px] font-medium text-zinc-200">
                    {macro.name}
                  </span>
                  {macro.description && (
                    <p className="mt-0.5 truncate text-[9px] text-zinc-600">{macro.description}</p>
                  )}
                </div>
                {macro.shortcut && (
                  <span className="shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[8px] text-zinc-500">
                    {macro.shortcut}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-zinc-700">
                  {macro.actions.length} action{macro.actions.length !== 1 ? 's' : ''}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    onClick={() => playMacro(macro)}
                    disabled={playingId === macro.id}
                    className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] text-emerald-500 transition hover:bg-emerald-500/10 disabled:opacity-40"
                    title="Play macro"
                  >
                    {playingId === macro.id ? (
                      <Loader2 size={9} className="animate-spin" />
                    ) : (
                      <Play size={9} />
                    )}
                  </button>
                  <button
                    onClick={() => setEditingMacro(macro)}
                    className="rounded px-1.5 py-0.5 text-[9px] text-zinc-600 transition hover:text-zinc-300"
                    title="Edit macro"
                  >
                    <Edit2 size={9} />
                  </button>
                  <button
                    onClick={() => deleteMacro(macro)}
                    className="rounded px-1.5 py-0.5 text-[9px] text-zinc-700 transition hover:text-red-400"
                    title="Delete macro"
                  >
                    <Trash2 size={9} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Edit modal */}
      {editingMacro && (
        <EditModal
          macro={editingMacro}
          onSave={saveMacroEdit}
          onClose={() => setEditingMacro(null)}
        />
      )}
    </div>
  )
}
