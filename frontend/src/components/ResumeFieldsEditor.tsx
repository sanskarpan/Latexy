'use client'

import { useEffect, useRef, useState } from 'react'
import type { ResumeEngineDocument, ResumeEngineNode } from '@/lib/resume-engine-types'

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
export default function ResumeFieldsEditor({ document, currentSourceHash, selectedNode, onSelect, onSave, readOnly, error }: {
  document: ResumeEngineDocument | null; currentSourceHash: string | null; selectedNode: string | null
  onSelect: (nodeId: string) => void; onSave: (node: ResumeEngineNode, text: string) => Promise<void>
  readOnly: boolean; error: string | null
}) {
  const eligible = document?.source_sha256 === currentSourceHash && !readOnly
  const nodes = document?.nodes.filter((node) => node.editable) ?? []
  const active = nodes.find((node) => node.node_id === selectedNode)
  return <div className="h-full space-y-5 overflow-auto bg-surface p-5">
    <div><h2 className="text-base font-semibold text-fg">Edit your resume</h2>
      <p className="mt-1 text-xs leading-relaxed text-fg-3">Choose a field here or click a highlighted field on your PDF. Your finished PDF uses the same layout you see.</p></div>
    {error && <p role="alert" className="text-xs text-err">{error}</p>}
    {!document && !error && <p className="text-sm text-fg-3">Loading your resume fields…</p>}
    {document && !eligible && <p role="status" className="rounded-lg bg-surface-2 p-3 text-xs text-fg-2">{readOnly ? 'This resume is read-only for your account.' : 'Save the current resume before editing fields. This protects your newer changes.'}</p>}
    {active && <EditableField key={`${active.node_id}:${active.node_revision}`} node={active} disabled={!eligible} onSave={onSave} />}
    <div className="space-y-2">{nodes.map((node) => <button type="button" key={node.node_id} disabled={!eligible}
      onClick={() => onSelect(node.node_id)} aria-pressed={node.node_id === selectedNode}
      className={`w-full rounded-lg border p-3 text-left transition disabled:opacity-50 ${selectedNode === node.node_id ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50'}`}>
      <span className="block text-[10px] font-medium uppercase tracking-wide text-fg-3">{node.section} · {node.kind.replace(/_/g, ' ')}</span>
      <span className="mt-1 block text-xs leading-relaxed text-fg-2">{node.text || 'Add text'}</span>
    </button>)}</div>
    {document && !nodes.length && <p className="text-sm leading-relaxed text-fg-3">This document uses a layout that cannot be edited safely through fields yet. Your original document and PDF remain intact.</p>}
  </div>
}
