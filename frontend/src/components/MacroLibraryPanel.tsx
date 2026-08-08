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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]">
      <div className="w-80 rounded-[var(--radius-lg)] border border-line bg-surface p-5 shadow-[var(--shadow-2)]">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[12px] font-semibold text-fg">Edit Macro</span>
          <button onClick={onClose} className="text-fg-3 hover:text-fg-2">
            <X size={14} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-[10px] text-fg-3">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[11px] text-fg outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] text-fg-3">Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[11px] text-fg outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] text-fg-3">
              Shortcut (press keys to capture)
            </label>
            <input
              readOnly
              value={shortcut}
              onKeyDown={captureShortcut}
              placeholder="e.g. ctrl+shift+1"
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[11px] text-fg outline-none focus:border-accent"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-[var(--radius-md)] px-3 py-1 text-[10px] text-fg-3 hover:text-fg-2"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-3 py-1 text-[10px] text-accent-strong ring-1 ring-accent hover:brightness-110 disabled:opacity-40"
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
          <Keyboard size={11} className="text-fg-3" />
          <span className="text-[11px] font-semibold text-fg-2">Keyboard Macros</span>
        </div>
        {!recording && (
          <button
            onClick={startRecording}
            className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-2 py-1 text-[9px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110"
          >
            <Plus size={9} />
            Record New
          </button>
        )}
      </div>

      {/* Recording controls */}
      {recording && (
        <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/5 p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <Circle size={8} className="animate-pulse fill-err text-err" />
            <span className="text-[10px] font-medium text-err">Recording…</span>
          </div>
          <input
            ref={nameInputRef}
            value={recordingName}
            onChange={(e) => setRecordingName(e.target.value)}
            placeholder="Macro name (optional)"
            className="mb-2 w-full rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[10px] text-fg outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <button
              onClick={stopRecording}
              className="flex flex-1 items-center justify-center gap-1 rounded-[var(--radius-md)] bg-err/20 py-1 text-[9px] font-medium text-err ring-1 ring-err/20 hover:bg-err/30"
            >
              <Square size={9} />
              Stop & Save
            </button>
            <button
              onClick={cancelRecording}
              className="rounded-[var(--radius-md)] px-2 py-1 text-[9px] text-fg-3 hover:text-fg-2"
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
            <Loader2 size={14} className="animate-spin text-fg-3" />
          </div>
        ) : macros.length === 0 ? (
          <div className="py-8 text-center text-[10px] text-fg-3">
            No macros yet.
            <br />
            Click "Record New" to capture a sequence of editor actions.
          </div>
        ) : (
          macros.map((macro) => (
            <div
              key={macro.id}
              className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-2.5 transition hover:border-line-2"
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <span className="truncate text-[11px] font-medium text-fg">
                    {macro.name}
                  </span>
                  {macro.description && (
                    <p className="mt-0.5 truncate text-[9px] text-fg-3">{macro.description}</p>
                  )}
                </div>
                {macro.shortcut && (
                  <span className="shrink-0 rounded-[var(--radius-md)] bg-surface-2 px-1.5 py-0.5 font-mono text-[8px] text-fg-3">
                    {macro.shortcut}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-fg-3">
                  {macro.actions.length} action{macro.actions.length !== 1 ? 's' : ''}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    onClick={() => playMacro(macro)}
                    disabled={playingId === macro.id}
                    className="flex items-center gap-0.5 rounded-[var(--radius-md)] px-1.5 py-0.5 text-[9px] text-ok transition hover:bg-ok/10 disabled:opacity-40"
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
                    className="rounded-[var(--radius-md)] px-1.5 py-0.5 text-[9px] text-fg-3 transition hover:text-fg-2"
                    title="Edit macro"
                  >
                    <Edit2 size={9} />
                  </button>
                  <button
                    onClick={() => deleteMacro(macro)}
                    className="rounded-[var(--radius-md)] px-1.5 py-0.5 text-[9px] text-fg-3 transition hover:text-err"
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
