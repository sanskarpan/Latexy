'use client'

import { useEffect, useRef, useState } from 'react'
import type { ResumeEngineDocument, ResumeEngineNode } from '@/lib/resume-engine-types'
import { moveResumeSibling } from '@/lib/resume-structure'

function EditableField({ node, onSave, disabled }: {
  node: ResumeEngineNode; onSave: (node: ResumeEngineNode, text: string) => Promise<void>; disabled: boolean
}) {
  const [text, setText] = useState(node.text)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { inputRef.current?.focus() }, [])
  return <form className="space-y-3" onSubmit={async (event) => {
    event.preventDefault()
    if (saving || disabled || text === node.text) return
    setSaving(true); setError(null)
    try { await onSave(node, text) }
    catch { setError('This field could not be saved. Another edit may have changed it. Refresh the resume and try again.') }
    finally { setSaving(false) }
  }}>
    <label className="block text-xs font-medium text-fg-2" htmlFor="resume-field-edit">{node.section} · {node.kind.replace(/_/g, ' ')}</label>
    <textarea ref={inputRef} id="resume-field-edit" value={text} onChange={(event) => setText(event.target.value)}
      rows={5} maxLength={4000} disabled={disabled || saving}
      className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm leading-relaxed text-fg focus:border-accent focus:outline-none" />
    <button type="submit" disabled={disabled || saving || text === node.text}
      className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">
      {saving ? 'Saving…' : 'Save field'}
    </button>
    {error && <p role="alert" className="text-xs text-err">{error}</p>}
  </form>
}

/** Plain fields only. Unsupported source is preserved without exposing code. */
export default function ResumeFieldsEditor({ document, currentSourceHash, selectedNode, onSelect, onSave, onReorder, readOnly, error }: {
  document: ResumeEngineDocument | null; currentSourceHash: string | null; selectedNode: string | null
  onSelect: (nodeId: string) => void; onSave: (node: ResumeEngineNode, text: string) => Promise<void>
  onReorder?: (containerId: string, orderedIds: string[]) => Promise<void>
  readOnly: boolean; error: string | null
}) {
  const eligible = document?.source_sha256 === currentSourceHash && !readOnly
  const nodes = document?.nodes.filter((node) => node.editable) ?? []
  const active = nodes.find((node) => node.node_id === selectedNode)
  const [moving, setMoving] = useState(false)
  const movingRef = useRef(false)
  const [structureError, setStructureError] = useState<string | null>(null)
  const containers = document?.source_mode === 'managed' ? document.containers ?? [] : []
  const immediate = active && containers.find((container) => container.container_id === active.container_id)
  const entry = active?.entry_id && containers.find((container) => container.kind === 'entries' && container.section === active.section && container.ordered_child_ids.includes(active.entry_id!))
  const section = active && containers.find((container) => container.kind === 'sections' && container.ordered_child_ids.includes(active.section))
  const controls = [immediate && active?.order_child_id ? { container: immediate, child: active.order_child_id } : null,
    entry && active?.entry_id ? { container: entry, child: active.entry_id } : null,
    section && active ? { container: section, child: active.section } : null]
    .filter((item, index, all) => item && all.findIndex((other) => other?.container.container_id === item.container.container_id) === index)
  return <div className="h-full space-y-5 overflow-auto bg-surface p-5">
    <div><h2 className="text-base font-semibold text-fg">Edit your resume</h2>
      <p className="mt-1 text-xs leading-relaxed text-fg-3">Choose a field here or click a highlighted field on your PDF. Your finished PDF uses the same layout you see.</p></div>
    {error && <p role="alert" className="text-xs text-err">{error}</p>}
    {!document && !error && <p className="text-sm text-fg-3">Loading your resume fields…</p>}
    {document && !eligible && <p role="status" className="rounded-lg bg-surface-2 p-3 text-xs text-fg-2">{readOnly ? 'This resume is read-only for your account.' : 'Save the current resume before editing fields. This protects your newer changes.'}</p>}
    {active && <EditableField key={`${active.node_id}:${active.node_revision}`} node={active} disabled={!eligible || moving} onSave={onSave} />}
    {onReorder && controls.length > 0 && <section aria-label="Resume ordering" className="space-y-3 rounded-lg border border-line p-3">
      <h3 className="text-xs font-semibold text-fg">Arrange your resume</h3>
      {controls.map((item) => {
        if (!item) return null
        const { container, child } = item
        const visible = container.kind === 'sections'
          ? container.ordered_child_ids.filter((id) => document?.nodes.some((node) => node.kind === 'section_heading' && node.section === id))
          : container.ordered_child_ids
        const label = container.kind === 'sections' ? 'section' : container.kind === 'entries' ? 'entry' : 'item'
        return <div key={container.container_id} className="space-y-1">
          <p className="text-[11px] text-fg-3">{container.label}</p>
          <div className="flex gap-2">{([-1, 1] as const).map((direction) => {
            const ordered = moveResumeSibling(container.ordered_child_ids, child, direction, visible)
            return <button key={direction} type="button" disabled={!eligible || moving || !ordered}
              onClick={async () => {
                if (!ordered || movingRef.current) return
                movingRef.current = true; setMoving(true); setStructureError(null)
                try { await onReorder(container.container_id, ordered) }
                catch { setStructureError('The order could not be saved. Another edit may have changed this resume. Refresh and try again.') }
                finally { movingRef.current = false; setMoving(false) }
              }} className="rounded-lg border border-line px-3 py-2 text-xs text-fg disabled:opacity-40">
              Move {label} {direction < 0 ? 'up' : 'down'}
            </button>
          })}</div>
        </div>
      })}
      {moving && <p role="status" className="text-xs text-fg-3">Saving order…</p>}
      {structureError && <p role="alert" className="text-xs text-err">{structureError}</p>}
    </section>}
    <div className="space-y-2">{nodes.map((node) => <button type="button" key={node.node_id} disabled={!eligible || moving}
      onClick={() => onSelect(node.node_id)} aria-pressed={node.node_id === selectedNode}
      className={`w-full rounded-lg border p-3 text-left transition disabled:opacity-50 ${selectedNode === node.node_id ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50'}`}>
      <span className="block text-[10px] font-medium uppercase tracking-wide text-fg-3">{node.section} · {node.kind.replace(/_/g, ' ')}</span>
      <span className="mt-1 block text-xs leading-relaxed text-fg-2">{node.text || 'Add text'}</span>
    </button>)}</div>
    {document && !nodes.length && <p className="text-sm leading-relaxed text-fg-3">This document uses a layout that cannot be edited safely through fields yet. Your original document and PDF remain intact.</p>}
  </div>
}
