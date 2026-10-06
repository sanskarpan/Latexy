'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, MessageSquare, Send, X } from 'lucide-react'
import { apiClient, type DocumentAssistantTurn } from '@/lib/api-client'

interface ProposedEdit {
  target_text: string
  replacement_text: string
}

interface DocumentAssistantPanelProps {
  isOpen: boolean
  resumeId: string
  documentLatex: string
  selectedText?: string
  onApply: (nextLatex: string) => void
  onClose: () => void
}

export default function DocumentAssistantPanel({
  isOpen,
  resumeId,
  documentLatex,
  selectedText,
  onApply,
  onClose,
}: DocumentAssistantPanelProps) {
  const [turns, setTurns] = useState<DocumentAssistantTurn[]>([])
  const [message, setMessage] = useState('')
  const [proposal, setProposal] = useState<ProposedEdit | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  useEffect(() => {
    if (!isOpen) requestId.current += 1
  }, [isOpen])

  if (!isOpen) return null

  const send = async () => {
    const prompt = message.trim()
    if (!prompt || loading) return
    const id = ++requestId.current
    const history = turns.slice(-10)
    setTurns(current => [...current, { role: 'user', content: prompt }])
    setMessage('')
    setProposal(null)
    setError(null)
    setLoading(true)
    try {
      const response = await apiClient.askDocumentAssistant({
        resume_id: resumeId,
        latex_content: documentLatex,
        message: prompt,
        history,
        selected_text: selectedText?.trim() || undefined,
      })
      if (requestId.current !== id) return
      setTurns(current => [...current, { role: 'assistant', content: response.message }])
      setProposal(response.proposed_edit)
    } catch (caught) {
      if (requestId.current !== id) return
      setError(caught instanceof Error ? caught.message : 'The document assistant could not respond.')
    } finally {
      if (requestId.current === id) setLoading(false)
    }
  }

  const targetOccurrences = proposal
    ? documentLatex.split(proposal.target_text).length - 1
    : 0
  const proposalIsCurrent = proposal !== null && targetOccurrences === 1

  return (
    <aside
      aria-label="Document assistant"
      className="fixed inset-y-0 right-0 z-[70] flex w-full max-w-md flex-col border-l border-line bg-bg shadow-[var(--shadow-2)]"
    >
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageSquare size={15} className="text-accent-strong" />
          <div>
            <h2 className="text-sm font-semibold text-fg">Document Assistant</h2>
            <p className="text-[10px] text-fg-3">Reviews the current LaTeX; edits always require approval</p>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close document assistant" className="rounded p-1 text-fg-3 hover:bg-surface-2">
          <X size={15} />
        </button>
      </header>

      <div aria-live="polite" className="flex-1 space-y-3 overflow-y-auto p-4">
        {turns.length === 0 && (
          <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3 text-xs leading-relaxed text-fg-2">
            Ask about structure, wording, missing information, or a focused revision. The assistant cannot save or change the document without your approval.
          </div>
        )}
        {turns.map((turn, index) => (
          <div key={`${turn.role}-${index}`} className={`rounded-[var(--radius-md)] px-3 py-2 text-xs leading-relaxed ${
            turn.role === 'user' ? 'ml-8 bg-accent-soft text-fg' : 'mr-8 border border-line bg-surface text-fg-2'
          }`}>
            {turn.content}
          </div>
        ))}
        {loading && <div className="flex items-center gap-2 text-xs text-fg-3"><Loader2 size={13} className="animate-spin" /> Reviewing the document…</div>}
        {error && <div role="alert" className="rounded border border-err/20 bg-err/10 p-2 text-xs text-err">{error}</div>}
        {proposal && (
          <section aria-label="Proposed edit" className="space-y-2 rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-accent-strong">Proposed edit</p>
            <div>
              <p className="text-[10px] text-fg-3">Replace</p>
              <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap text-[11px] text-err">{proposal.target_text}</pre>
            </div>
            <div>
              <p className="text-[10px] text-fg-3">With</p>
              <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap text-[11px] text-ok">{proposal.replacement_text}</pre>
            </div>
            {!proposalIsCurrent && <p className="text-[10px] text-warn">The target changed or is no longer unique. Ask for a fresh proposal.</p>}
            <button
              type="button"
              disabled={!proposalIsCurrent}
              onClick={() => {
                if (!proposalIsCurrent) return
                onApply(documentLatex.replace(proposal.target_text, proposal.replacement_text))
                setProposal(null)
                setTurns(current => [...current, { role: 'assistant', content: 'Applied the approved edit.' }])
              }}
              className="flex items-center gap-1.5 rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-50"
            >
              <Check size={12} /> Apply edit
            </button>
          </section>
        )}
      </div>

      <form
        className="border-t border-line p-3"
        onSubmit={event => { event.preventDefault(); void send() }}
      >
        <label htmlFor="document-assistant-message" className="sr-only">Message the document assistant</label>
        <div className="flex items-end gap-2">
          <textarea
            id="document-assistant-message"
            value={message}
            onChange={event => setMessage(event.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="Ask about this document…"
            className="min-h-20 flex-1 resize-none rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
          <button type="submit" disabled={!message.trim() || loading} aria-label="Send message" className="rounded-[var(--radius-md)] bg-accent p-2.5 text-accent-fg disabled:opacity-50">
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
      </form>
    </aside>
  )
}
