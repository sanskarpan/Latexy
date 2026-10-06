'use client'

import { useState } from 'react'
import { Check, Lightbulb, Plus, X } from 'lucide-react'
import type { Suggestion } from '@/lib/suggestions'

interface SuggestionsPanelProps {
  suggestions: Suggestion[]
  canSuggest: boolean
  canResolve: boolean
  canReject: (suggestion: Suggestion) => boolean
  modeEnabled: boolean
  onToggleMode: () => void
  onCreate: (findText: string, replacementText: string) => void
  onAccept: (id: string) => void
  onReject: (id: string) => void
  error: string | null
  onRetry: () => void
}

export default function SuggestionsPanel({
  suggestions,
  canSuggest,
  canResolve,
  canReject,
  modeEnabled,
  onToggleMode,
  onCreate,
  onAccept,
  onReject,
  error,
  onRetry,
}: SuggestionsPanelProps) {
  const [findText, setFindText] = useState('')
  const [replacementText, setReplacementText] = useState('')
  const pending = suggestions.filter((item) => item.status === 'pending')
  const visible = suggestions.filter((item) => item.status === 'pending' || item.status === 'conflicted')

  return (
    <section className="flex h-full flex-col overflow-hidden" aria-label="Suggestions">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Lightbulb size={15} className="text-accent-strong" />
            <h2 className="text-sm font-semibold text-fg">Suggestions</h2>
          </div>
          <button
            type="button"
            onClick={onToggleMode}
            disabled={!canSuggest}
            aria-pressed={modeEnabled}
            className="rounded px-2 py-1 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/25 disabled:opacity-40"
          >
            {modeEnabled ? 'Suggesting on' : 'Turn on'}
          </button>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
          Suggestions are drafts only. They never change the shared document until an owner or editor accepts one.
        </p>
        {!canSuggest && <p className="mt-1 text-[10px] text-warn">Viewers cannot suggest.</p>}
        {canSuggest && !canResolve && <p className="mt-1 text-[10px] text-fg-3">Owners and editors accept or reject proposals.</p>}
      </div>

      {error && (
        <div role="alert" className="m-3 flex items-center gap-2 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-[11px] text-danger">
          <span className="flex-1">{error}</span>
          <button type="button" onClick={onRetry} className="font-semibold underline">Retry</button>
        </div>
      )}

      {canSuggest && modeEnabled && (
        <div className="border-b border-line px-4 py-3">
          <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3" htmlFor="suggestion-find">Existing text</label>
          <textarea id="suggestion-find" value={findText} onChange={(event) => setFindText(event.target.value)} rows={2} className="mt-1 w-full resize-none rounded border border-line bg-surface-2 p-2 text-[11px] text-fg outline-none focus:border-accent" placeholder="Text to propose changing" />
          <label className="mt-2 block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3" htmlFor="suggestion-replacement">Suggested replacement</label>
          <textarea id="suggestion-replacement" value={replacementText} onChange={(event) => setReplacementText(event.target.value)} rows={2} className="mt-1 w-full resize-none rounded border border-line bg-surface-2 p-2 text-[11px] text-fg outline-none focus:border-accent" placeholder="Replacement text" />
          <button type="button" onClick={() => { onCreate(findText, replacementText); setFindText(''); setReplacementText('') }} disabled={!findText} className="mt-2 flex items-center gap-1 rounded bg-accent/20 px-2 py-1 text-[10px] font-semibold text-accent-strong disabled:opacity-40">
            <Plus size={11} /> Create suggestion
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <p className="p-6 text-center text-xs text-fg-3">No pending suggestions</p>
        ) : visible.map((suggestion) => (
          <div key={suggestion.id} className="border-b border-line px-4 py-3">
            <div className="flex items-center justify-between gap-2 text-[10px] text-fg-3">
              <span>{suggestion.authorName}</span>
              <span>{new Date(suggestion.createdAt).toLocaleString()}</span>
            </div>
            <p className="mt-2 rounded bg-danger/10 p-2 font-mono text-[10px] text-fg-2">− {suggestion.originalText}</p>
            <p className="mt-1 rounded bg-ok/10 p-2 font-mono text-[10px] text-fg-2">+ {suggestion.replacementText || '(remove text)'}</p>
            {suggestion.status === 'conflicted' ? (
              <p className="mt-2 text-[10px] font-medium text-warn">Conflicted — {suggestion.conflictReason ?? 'review the current source before creating a new suggestion'}</p>
            ) : (
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={() => onAccept(suggestion.id)} disabled={!canResolve} className="flex items-center gap-1 rounded px-2 py-1 text-[10px] font-semibold text-ok ring-1 ring-ok/20 disabled:opacity-40"><Check size={11} /> Accept</button>
                <button type="button" onClick={() => onReject(suggestion.id)} disabled={!canReject(suggestion)} className="flex items-center gap-1 rounded px-2 py-1 text-[10px] font-semibold text-err ring-1 ring-err/20 disabled:opacity-40"><X size={11} /> Reject</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
