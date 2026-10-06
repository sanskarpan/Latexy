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
  Code2,
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
import { applyMacroScript } from '@/lib/macros/macro-script-runner'
import { matchesShortcut, normalizeShortcut } from '@/lib/macros/macro-shortcuts'

type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

interface Props {
  editor: IStandaloneCodeEditor | null
  onMacrosChange?: (macros: MacroResponse[]) => void
  className?: string
}

// ── Edit / rename modal ────────────────────────────────────────────────────────

function EditModal({
  macro,
  onSave,
  onClose,
}: {
  macro: MacroResponse
  onSave: (name: string, description: string, shortcut: string, script: string) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState(macro.name)
  const [description, setDescription] = useState(macro.description ?? '')
  const [shortcut, setShortcut] = useState(macro.shortcut ?? '')
  const [script, setScript] = useState(macro.script ?? '')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const captureShortcut = (e: React.KeyboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const parts: string[] = []
    if (e.ctrlKey || e.metaKey) parts.push('ctrl')
    if (e.altKey) parts.push('alt')
    if (e.shiftKey) parts.push('shift')
    const key = e.code.match(/^Key([A-Z])$/)?.[1].toLowerCase()
      ?? e.code.match(/^Digit([0-9])$/)?.[1]
      ?? e.code.match(/^(F(?:[1-9]|1[0-9]|2[0-4]))$/)?.[1].toLowerCase()
      ?? e.key.toLowerCase()
    if (!['control', 'alt', 'shift', 'meta'].includes(key)) parts.push(key)
    if (parts.length > 1) setShortcut(parts.join('+'))
  }

  const handleSave = async () => {
    if (!name.trim()) return
    const normalizedShortcut = normalizeShortcut(shortcut)
    if (shortcut.trim() && !normalizedShortcut) {
      setSaveError('Shortcut is malformed or reserved by the editor/browser.')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      await onSave(name.trim(), description.trim(), normalizedShortcut ?? '', script)
      onClose()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to save macro'
      setSaveError(message)
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]">
      <div className="w-80 rounded-[var(--radius-lg)] border border-line bg-surface p-5 shadow-[var(--shadow-2)]">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[12px] font-semibold text-fg">Edit Macro</span>
          <button onClick={onClose} disabled={saving} className="text-fg-3 hover:text-fg-2 disabled:opacity-40">
            <X size={14} />
          </button>
        </div>
        {saveError && <div role="alert" className="mb-3 rounded-[var(--radius-md)] bg-err/10 px-2 py-1 text-[10px] text-err">{saveError}</div>}
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
            <label className="mb-1 block text-[10px] text-fg-3">Deterministic script (optional)</label>
            <textarea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              rows={4}
              spellCheck={false}
              aria-label="Edit macro script"
              placeholder={'prepend "Header"\nreplace "old" with "new" all'}
              className="w-full resize-y rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 font-mono text-[10px] text-fg outline-none focus:border-accent"
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
            {shortcut && (
              <button
                type="button"
                onClick={() => setShortcut('')}
                disabled={saving}
                className="mt-1 text-[9px] text-fg-3 underline hover:text-fg-2 disabled:opacity-40"
              >
                Clear shortcut
              </button>
            )}
            {shortcut.trim() && !normalizeShortcut(shortcut) && (
              <p role="alert" className="mt-1 text-[10px] text-err">
                Use a unique Ctrl-based shortcut that is not reserved by the editor/browser.
              </p>
            )}
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={saving}
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

export default function MacroLibraryPanel({ editor, onMacrosChange, className }: Props) {
  const [macros, setMacros] = useState<MacroResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [recordingName, setRecordingName] = useState('')
  const [scriptName, setScriptName] = useState('')
  const [scriptSource, setScriptSource] = useState('replace "old" with "new" all')
  const [creatingScript, setCreatingScript] = useState(false)
  const [scriptSaving, setScriptSaving] = useState(false)
  const [editingMacro, setEditingMacro] = useState<MacroResponse | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const mountedRef = useRef(true)
  const fetchGenerationRef = useRef(0)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MacroRecorder | null>(null)
  const playerRef = useRef<MacroPlayer | null>(null)
  const macrosRef = useRef<MacroResponse[]>([])
  const actionLockRef = useRef(false)
  const playMacroRef = useRef<(macro: MacroResponse) => void>(() => undefined)
  if (!recorderRef.current) recorderRef.current = new MacroRecorder()
  if (!playerRef.current) playerRef.current = new MacroPlayer()

  const onMacrosChangeRef = useRef(onMacrosChange)
  useEffect(() => {
    onMacrosChangeRef.current = onMacrosChange
  }, [onMacrosChange])

  const publishMacros = useCallback((next: MacroResponse[]) => {
    macrosRef.current = next
    setMacros(next)
    onMacrosChangeRef.current?.(next)
  }, [])

  const fetchMacros = useCallback(async () => {
    const generation = ++fetchGenerationRef.current
    setLoading(true)
    setLoadError(null)
    try {
      const data = await apiClient.getMacros()
      if (!mountedRef.current || generation !== fetchGenerationRef.current) return
      publishMacros(data)
    } catch (error) {
      if (!mountedRef.current || generation !== fetchGenerationRef.current) return
      setLoadError(error instanceof Error ? error.message : 'Failed to load macros')
    } finally {
      if (mountedRef.current && generation === fetchGenerationRef.current) setLoading(false)
    }
  }, [publishMacros])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      fetchGenerationRef.current += 1
      recorderRef.current?.cancelRecording()
    }
  }, [])

  useEffect(() => {
    fetchMacros()
  }, [fetchMacros])

  const startRecording = () => {
    if (actionLockRef.current) return
    if (!editor) {
      toast.error('Switch to Source mode to record macros')
      return
    }
    recorderRef.current!.startRecording(editor)
    setRecording(true)
    setTimeout(() => nameInputRef.current?.focus(), 50)
    toast('Recording started — perform your actions in the editor', { icon: '⏺' })
  }

  const stopRecording = async () => {
    if (actionLockRef.current) return
    actionLockRef.current = true
    const actions = recorderRef.current!.stopRecording()
    setRecording(false)
    if (actions.length === 0) {
      toast.error('No actions recorded')
      actionLockRef.current = false
      return
    }
    const name = recordingName.trim() || `Macro ${macrosRef.current.length + 1}`
    try {
      const macro = await apiClient.createMacro({
        name,
        actions: actions as unknown as Record<string, unknown>[],
      })
      if (!mountedRef.current) return
      publishMacros([macro, ...macrosRef.current])
      setRecordingName('')
      toast.success(`"${name}" saved (${actions.length} actions)`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save macro')
    } finally {
      actionLockRef.current = false
    }
  }

  const cancelRecording = () => {
    if (actionLockRef.current) return
    recorderRef.current!.cancelRecording()
    setRecording(false)
    setRecordingName('')
  }

  const createScript = async () => {
    if (actionLockRef.current) return
    actionLockRef.current = true
    const name = scriptName.trim() || `Script ${macrosRef.current.length + 1}`
    setScriptSaving(true)
    try {
      const macro = await apiClient.createMacro({ name, actions: [], script: scriptSource })
      if (!mountedRef.current) return
      publishMacros([macro, ...macrosRef.current])
      setScriptName('')
      setScriptSource('replace "old" with "new" all')
      setCreatingScript(false)
      toast.success(`"${name}" saved`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Script is invalid')
    } finally {
      setScriptSaving(false)
      actionLockRef.current = false
    }
  }

  const playMacro = async (macro: MacroResponse) => {
    if (actionLockRef.current) return
    if (macro.legacy_actions_available) {
      toast.error('This legacy macro is not executable; delete it and record a replacement.')
      return
    }
    if (!editor) {
      toast.error('Switch to Source mode to play macros')
      return
    }
    actionLockRef.current = true
    setPlayingId(macro.id)
    try {
      if (macro.script != null) {
        const result = await applyMacroScript(editor, (document) => apiClient.executeMacro(macro.id, {
          document,
          expected_script_version: macro.script_version,
        }))
        toast.success(`"${macro.name}" applied (${result.operation_count} operations)`)
        return
      }
      await playerRef.current!.play(
        {
          id: macro.id,
          name: macro.name,
          description: macro.description ?? undefined,
          shortcut: macro.shortcut ?? undefined,
          actions: macro.actions as unknown as MacroAction[],
        },
        editor,
      )
    } catch (error) {
      const status = typeof error === 'object' && error !== null && 'status' in error
        ? (error as { status?: number }).status
        : undefined
      toast.error(
        status === 409
          ? 'Macro is out of date; reload the macro and try again.'
          : error instanceof Error ? error.message : 'Macro playback failed',
      )
      if (status === 409 && mountedRef.current) void fetchMacros()
    } finally {
      if (mountedRef.current) setPlayingId(null)
      actionLockRef.current = false
    }
  }
  playMacroRef.current = playMacro

  const deleteMacro = async (macro: MacroResponse) => {
    if (actionLockRef.current) return
    actionLockRef.current = true
    setDeletingId(macro.id)
    try {
      await apiClient.deleteMacro(macro.id)
      if (!mountedRef.current) return
      publishMacros(macrosRef.current.filter((m) => m.id !== macro.id))
      toast.success(`"${macro.name}" deleted`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete macro')
    } finally {
      if (mountedRef.current) setDeletingId(null)
      actionLockRef.current = false
    }
  }

  // Keep shortcut registration alive while the panel is hidden in another tab.
  // The first macro wins on duplicates, and browser-reserved combinations are
  // intentionally ignored by normalizeShortcut().
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLInputElement || (target instanceof HTMLTextAreaElement && !target.classList.contains('inputarea'))) return
      const macro = macrosRef.current.find((candidate) => candidate.shortcut && matchesShortcut(event, candidate.shortcut))
      if (!macro) return
      event.preventDefault()
      event.stopPropagation()
      if (macro.legacy_actions_available) {
        toast.error('This legacy macro is not executable; delete it and record a replacement.')
        return
      }
      playMacroRef.current(macro)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const saveMacroEdit = async (name: string, description: string, shortcut: string, script: string) => {
    if (!editingMacro || actionLockRef.current) return
    actionLockRef.current = true
    try {
      const normalizedShortcut = normalizeShortcut(shortcut)
      if (shortcut.trim() && !normalizedShortcut) {
        throw new Error('Shortcut is malformed or reserved by the editor/browser.')
      }
      if (
        normalizedShortcut
        && macrosRef.current.some((macro) => macro.id !== editingMacro.id && macro.shortcut === normalizedShortcut)
      ) {
        throw new Error('That shortcut is already assigned to another macro.')
      }
      const body: Parameters<typeof apiClient.updateMacro>[1] = {
        name,
        description: description || null,
        shortcut: normalizedShortcut,
      }
      if (script !== (editingMacro.script ?? '')) {
        // A recorded macro can be converted to a script, but an empty script
        // must not erase its recorded actions and leave an unexecutable row.
        if (!script.trim()) {
          if (editingMacro.script != null) {
            throw new Error('A script must contain at least one operation; use recorded actions to convert back.')
          }
        } else {
          body.script = script
        }
        body.expected_script_version = editingMacro.script_version
      }
      const updated = await apiClient.updateMacro(editingMacro.id, body)
      if (!mountedRef.current) return
      publishMacros(macrosRef.current.map((m) => (m.id === updated.id ? updated : m)))
      toast.success('Macro updated')
      setEditingMacro(null)
    } finally {
      actionLockRef.current = false
    }
  }

  return (
    <div data-macro-library="true" className={`flex h-full flex-col gap-3 p-3 ${className ?? ''}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Keyboard size={11} className="text-fg-3" />
          <span className="text-[11px] font-semibold text-fg-2">Keyboard Macros</span>
        </div>
        {!recording && (
          <div className="flex gap-1">
            <button
              onClick={() => setCreatingScript((value) => !value)}
              disabled={actionLockRef.current}
              className="flex items-center gap-1 rounded-[var(--radius-md)] border border-line px-2 py-1 text-[9px] font-medium text-fg-2 transition hover:border-accent"
            >
              <Code2 size={9} />
              Script
            </button>
            <button
              onClick={startRecording}
              disabled={actionLockRef.current}
              className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-2 py-1 text-[9px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110"
            >
              <Plus size={9} />
              Record New
            </button>
          </div>
        )}
      </div>

      {creatingScript && !recording && (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
          <div className="mb-2 text-[10px] font-medium text-fg-2">New deterministic script</div>
          <input
            value={scriptName}
            onChange={(e) => setScriptName(e.target.value)}
            placeholder="Script name"
            className="mb-2 w-full rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[10px] text-fg outline-none focus:border-accent"
          />
          <textarea
            value={scriptSource}
            onChange={(e) => setScriptSource(e.target.value)}
            rows={4}
            spellCheck={false}
            aria-label="Macro script"
            className="w-full resize-y rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 font-mono text-[10px] text-fg outline-none focus:border-accent"
          />
          <p className="mt-1 text-[9px] text-fg-3">Commands: prepend, append, replace, delete-prefix, delete-suffix. No code execution or network access.</p>
          <div className="mt-2 flex justify-end gap-2">
            <button onClick={() => setCreatingScript(false)} className="px-2 py-1 text-[9px] text-fg-3">Cancel</button>
            <button onClick={() => void createScript()} disabled={scriptSaving || !scriptSource.trim()} className="rounded-[var(--radius-md)] bg-accent-soft px-2 py-1 text-[9px] text-accent-strong disabled:opacity-40">{scriptSaving ? 'Saving…' : 'Save Script'}</button>
          </div>
        </div>
      )}

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
        ) : loadError ? (
          <div role="alert" className="flex flex-col items-center gap-2 py-8 text-center text-[10px] text-err">
            <span>{loadError}</span>
            <button
              type="button"
              onClick={() => void fetchMacros()}
              className="rounded-[var(--radius-md)] border border-line px-2 py-1 font-medium text-fg-2 hover:bg-surface-2"
            >
              Retry
            </button>
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
                  {macro.script != null
                    ? `Script v${macro.script_version}`
                    : macro.legacy_actions_available
                      ? 'Legacy recording — replacement required'
                      : `${macro.actions.length} action${macro.actions.length !== 1 ? 's' : ''}`}
                </span>
                {macro.legacy_actions_available && (
                  <span className="text-[9px] text-warn" title="Delete this macro and record a replacement">
                    Not executable
                  </span>
                )}
                <div className="ml-auto flex items-center gap-1">
                  <button
                    onClick={() => playMacro(macro)}
                    disabled={macro.legacy_actions_available || playingId === macro.id || actionLockRef.current}
                    className="flex items-center gap-0.5 rounded-[var(--radius-md)] px-1.5 py-0.5 text-[9px] text-ok transition hover:bg-ok/10 disabled:opacity-40"
                    title={macro.legacy_actions_available
                      ? 'Delete this macro and record a replacement'
                      : 'Play macro'}
                  >
                    {playingId === macro.id ? (
                      <Loader2 size={9} className="animate-spin" />
                    ) : (
                      <Play size={9} />
                    )}
                  </button>
                  <button
                    onClick={() => setEditingMacro(macro)}
                    disabled={actionLockRef.current}
                    className="rounded-[var(--radius-md)] px-1.5 py-0.5 text-[9px] text-fg-3 transition hover:text-fg-2"
                    title="Edit macro"
                  >
                    <Edit2 size={9} />
                  </button>
                  <button
                    onClick={() => deleteMacro(macro)}
                    disabled={actionLockRef.current}
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
