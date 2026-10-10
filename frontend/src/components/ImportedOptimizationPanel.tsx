'use client'

import { useState } from 'react'

/** Whole-document candidates stay separate; custom layouts cannot claim field-level proof. */
export default function ImportedOptimizationPanel({ jobDescription, setJobDescription, disabled, running, candidate,
  changes, onRun, onPreview, onApply, onDiscard }: {
  jobDescription: string; setJobDescription: (value: string) => void; disabled: boolean; running: boolean; candidate: boolean
  changes: Array<{ section: string; reason: string }>; onRun: () => void; onPreview: () => void; onApply: () => void; onDiscard: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  return <div className="h-full space-y-4 overflow-auto p-4">
    <h2 className="text-base font-semibold">Review a custom resume</h2>
    <p className="text-xs leading-relaxed text-fg-3">This layout supports manual editing of recognized fields. Field-by-field AI suggestions require a supported resume template.</p>
    <button type="button" onClick={() => setExpanded((value) => !value)} className="text-xs font-semibold text-accent-strong">{expanded ? 'Hide advanced review' : 'Use advanced whole-document review'}</button>
    {expanded && <>
      <p className="rounded-lg border border-warn/30 p-3 text-xs text-fg-2">Advanced review creates a separate PDF candidate for your custom layout. Review the entire PDF before applying it. Your current resume stays intact until you accept.</p>
      <label className="block text-xs font-semibold">Target job<textarea rows={6} value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} maxLength={20000}
        placeholder="Paste the job description" className="mt-2 w-full rounded-lg border border-line bg-surface p-3 text-sm font-normal" /></label>
      <button disabled={disabled || running} onClick={onRun} className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50">{running ? 'Preparing review…' : 'Start advanced review'}</button>
    </>}
    {candidate && <div className="space-y-3 rounded-lg border border-accent/30 p-3">
      <p className="text-xs font-semibold">A separate PDF candidate is ready</p>
      <button onClick={onPreview} className="text-xs font-semibold text-accent-strong">Review candidate PDF</button>
      {changes.length > 0 && <p className="text-xs text-fg-3">{changes.length} suggested improvements are ready to review in the PDF.</p>}
      <div className="flex gap-2"><button disabled={disabled || running} onClick={onApply} className="rounded bg-accent px-3 py-2 text-xs text-accent-fg disabled:opacity-50">Accept complete candidate</button>
        <button disabled={running} onClick={onDiscard} className="rounded border border-line px-3 py-2 text-xs disabled:opacity-50">Discard</button></div>
    </div>}
  </div>
}
