'use client'

import { useState, useRef, useCallback } from 'react'
import { BookOpen, Search, Copy, Check, ChevronDown, ChevronRight, Loader2, Plus, PlusCircle } from 'lucide-react'
import { apiClient, type BibTeXEntry } from '@/lib/api-client'

interface ReferencesPanelProps {
  onInsertBibTeX: (bibtex: string) => void
  onInsertCiteKey: (citeKey: string) => void
}

// Detect type of a single line of text
function detectLineType(line: string): 'doi' | 'arxiv' | null {
  const trimmed = line.trim()
  if (!trimmed) return null
  if (/^10\.\d{4,}\//.test(trimmed) || /doi\.org\//i.test(trimmed)) return 'doi'
  if (/^\d{4}\.\d{4,}(v\d+)?$/.test(trimmed) || /arxiv\.org\//i.test(trimmed)) return 'arxiv'
  return null
}

function TypeBadge({ type }: { type: 'doi' | 'arxiv' | null }) {
  if (!type) return null
  return (
    <span className={`ml-2 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
      type === 'doi'
        ? 'bg-sky-500/15 text-sky-400'
        : 'bg-violet-500/15 text-violet-400'
    }`}>
      {type}
    </span>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).catch(() => null)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={copy}
      className="ml-1 rounded p-0.5 text-white/30 transition hover:text-white/60"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  )
}

function EntryCard({
  entry,
  onInsertBibTeX,
  onInsertCiteKey,
}: {
  entry: BibTeXEntry
  onInsertBibTeX: (bibtex: string) => void
  onInsertCiteKey: (key: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  if (entry.error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2.5">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 shrink-0 text-red-400">!</span>
          <div className="min-w-0">
            <div className="truncate text-[11px] font-medium text-white/60">{entry.identifier}</div>
            <div className="mt-0.5 text-[11px] text-red-400">{entry.error}</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-white/[0.07] bg-white/[0.03]">
      {/* Header */}
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2">
          <TypeBadge type={entry.source_type as 'doi' | 'arxiv' | null} />
          <div className="min-w-0 flex-1">
            {entry.title && (
              <div className="text-[12px] font-medium leading-snug text-white/85">
                {entry.title}
              </div>
            )}
            {entry.authors && (
              <div className="mt-0.5 truncate text-[11px] text-white/40">{entry.authors}</div>
            )}
            {entry.year && (
              <div className="mt-0.5 text-[10px] text-white/30">{entry.year}</div>
            )}
          </div>
        </div>

        {/* Cite key row */}
        <div className="mt-2 flex items-center gap-1">
          <code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-amber-300/80">
            \cite{'{'}
            {entry.cite_key}
            {'}'}
          </code>
          <CopyButton text={`\\cite{${entry.cite_key}}`} />
          <button
            onClick={() => onInsertCiteKey(`\\cite{${entry.cite_key}}`)}
            className="ml-auto flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-white/40 transition hover:bg-white/[0.06] hover:text-white/70"
            title="Insert \cite{} at cursor"
          >
            <Plus className="h-3 w-3" />
            \cite
          </button>
        </div>
      </div>

      {/* BibTeX toggle */}
      <div className="border-t border-white/[0.05]">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[10px] text-white/30 transition hover:text-white/50"
        >
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          BibTeX
        </button>

        {expanded && entry.bibtex && (
          <div className="border-t border-white/[0.05] px-3 pb-2.5 pt-2">
            <pre className="max-h-40 overflow-auto rounded bg-black/40 p-2 text-[10px] leading-relaxed text-white/60 ring-1 ring-white/[0.06]">
              {entry.bibtex}
            </pre>
            <div className="mt-2 flex items-center justify-end gap-2">
              <CopyButton text={entry.bibtex} />
              <button
                onClick={() => onInsertBibTeX(entry.bibtex!)}
                className="flex items-center gap-1 rounded-md bg-emerald-500/15 px-2.5 py-1 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-400/25 transition hover:bg-emerald-500/25"
              >
                <PlusCircle className="h-3 w-3" />
                Insert BibTeX
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ReferencesPanel({ onInsertBibTeX, onInsertCiteKey }: ReferencesPanelProps) {
  const [input, setInput] = useState('')
  const [entries, setEntries] = useState<BibTeXEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [fetched, setFetched] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const lines = input.split('\n').filter(l => l.trim())

  const handleFetch = useCallback(async () => {
    if (!lines.length || loading) return
    setLoading(true)
    setFetched(false)
    try {
      const resp = await apiClient.fetchReferences(lines)
      setEntries(resp.entries)
      setFetched(true)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [lines, loading])

  const handleInsertAll = () => {
    const allBibtex = entries
      .filter(e => e.bibtex)
      .map(e => e.bibtex!)
      .join('\n\n')
    if (allBibtex) onInsertBibTeX('\n' + allBibtex)
  }

  const successCount = entries.filter(e => e.bibtex).length

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-white/[0.05] px-3 py-2.5">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/40">
          <BookOpen className="h-3.5 w-3.5" />
          BibTeX Import
        </div>
        <p className="mt-1 text-[10px] leading-snug text-white/25">
          Paste DOIs or arXiv IDs, one per line
        </p>
      </div>

      {/* Input area */}
      <div className="shrink-0 border-b border-white/[0.05] p-3">
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') handleFetch()
            }}
            placeholder={`10.1145/3386569.3392408\n1706.03762\nhttps://doi.org/10.1145/...`}
            rows={4}
            className="w-full resize-none rounded-lg bg-black/30 p-2.5 font-mono text-[11px] text-white/70 placeholder:text-white/20 ring-1 ring-white/[0.08] outline-none focus:ring-white/[0.15] transition"
          />
          {/* Per-line type badges (overlay) */}
          {input && (
            <div className="pointer-events-none absolute right-2 top-2 flex flex-col gap-[1px]">
              {input.split('\n').map((line, i) => {
                const t = detectLineType(line)
                return (
                  <div key={i} className="flex h-[18px] items-center">
                    <TypeBadge type={t} />
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <button
          onClick={handleFetch}
          disabled={!lines.length || loading}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-sky-500/20 py-1.5 text-[11px] font-medium text-sky-300 ring-1 ring-sky-400/25 transition hover:bg-sky-500/30 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Fetching…
            </>
          ) : (
            <>
              <Search className="h-3.5 w-3.5" />
              Fetch {lines.length > 0 ? `${lines.length} reference${lines.length !== 1 ? 's' : ''}` : 'references'}
            </>
          )}
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-3">
        {fetched && entries.length === 0 && (
          <p className="text-center text-[11px] text-white/25">No results</p>
        )}

        {entries.length > 0 && (
          <div className="space-y-2">
            {entries.map((entry, i) => (
              <EntryCard
                key={i}
                entry={entry}
                onInsertBibTeX={bibtex => onInsertBibTeX('\n' + bibtex)}
                onInsertCiteKey={onInsertCiteKey}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer: Insert All */}
      {successCount > 1 && (
        <div className="shrink-0 border-t border-white/[0.05] p-3">
          <button
            onClick={handleInsertAll}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-500/15 py-1.5 text-[11px] font-medium text-emerald-300 ring-1 ring-emerald-400/25 transition hover:bg-emerald-500/25"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            Insert All ({successCount}) BibTeX entries
          </button>
        </div>
      )}
    </div>
  )
}
