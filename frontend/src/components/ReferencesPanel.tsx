'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, Check, ChevronDown, ChevronRight, Copy, ExternalLink, Loader2, Plus, PlusCircle, RefreshCw, Search, Unlink, X } from 'lucide-react'
import { apiClient, type BibTeXEntry, type ZoteroCollection, type ZoteroStatusResponse, type MendeleyStatusResponse } from '@/lib/api-client'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030'

interface ReferencesPanelProps {
  resumeId?: string
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
        ? 'bg-accent-soft text-accent-strong'
        : 'bg-surface-2 text-fg-2'
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
      className="ml-1 rounded p-0.5 text-fg-3 transition hover:text-fg-2"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
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
      <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/10 px-3 py-2.5">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 shrink-0 text-err">!</span>
          <div className="min-w-0">
            <div className="truncate text-[11px] font-medium text-fg-2">{entry.identifier}</div>
            <div className="mt-0.5 text-[11px] text-err">{entry.error}</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface">
      {/* Header */}
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2">
          <TypeBadge type={entry.source_type as 'doi' | 'arxiv' | null} />
          <div className="min-w-0 flex-1">
            {entry.title && (
              <div className="text-[12px] font-medium leading-snug text-fg">
                {entry.title}
              </div>
            )}
            {entry.authors && (
              <div className="mt-0.5 truncate text-[11px] text-fg-3">{entry.authors}</div>
            )}
            {entry.year && (
              <div className="mt-0.5 text-[10px] text-fg-3">{entry.year}</div>
            )}
          </div>
        </div>

        {/* Cite key row */}
        <div className="mt-2 flex items-center gap-1">
          <code className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-accent-strong">
            \cite{'{'}
            {entry.cite_key}
            {'}'}
          </code>
          <CopyButton text={`\\cite{${entry.cite_key}}`} />
          <button
            onClick={() => onInsertCiteKey(`\\cite{${entry.cite_key}}`)}
            className="ml-auto flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            title="Insert \cite{} at cursor"
          >
            <Plus className="h-3 w-3" />
            \cite
          </button>
        </div>
      </div>

      {/* BibTeX toggle */}
      <div className="border-t border-line">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[10px] text-fg-3 transition hover:text-fg-2"
        >
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          BibTeX
        </button>

        {expanded && entry.bibtex && (
          <div className="border-t border-line px-3 pb-2.5 pt-2">
            <pre className="max-h-40 overflow-auto rounded bg-bg p-2 text-[10px] leading-relaxed text-fg-2 ring-1 ring-line">
              {entry.bibtex}
            </pre>
            <div className="mt-2 flex items-center justify-end gap-2">
              <CopyButton text={entry.bibtex} />
              <button
                onClick={() => onInsertBibTeX(entry.bibtex!)}
                className="flex items-center gap-1 rounded-[var(--radius-md)] bg-ok/15 px-2.5 py-1 text-[10px] font-medium text-ok ring-1 ring-ok/25 transition hover:bg-ok/25"
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

// ── Zotero import section ─────────────────────────────────────────────────

function ZoteroSection({
  resumeId,
  onBibTeXImported,
}: {
  resumeId?: string
  onBibTeXImported: (bibtex: string, count: number) => void
}) {
  const [status, setStatus] = useState<ZoteroStatusResponse | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [collections, setCollections] = useState<ZoteroCollection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<string>('')
  const [collectionsLoading, setCollectionsLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    apiClient.getZoteroStatus()
      .then(setStatus)
      .catch(() => setStatus({ connected: false, username: null, user_id: null }))
      .finally(() => setStatusLoading(false))
  }, [])

  // Listen for OAuth popup completing
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'zotero:connected') {
        setStatusLoading(true)
        apiClient.getZoteroStatus()
          .then(s => { setStatus(s); setSuccess('Zotero connected!') })
          .catch(() => null)
          .finally(() => setStatusLoading(false))
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [])

  const handleConnect = () => {
    window.open(`${API_BASE}/zotero/connect`, '_blank', 'width=600,height=700,popup=1')
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Zotero?')) return
    try {
      await apiClient.disconnectZotero()
      setStatus({ connected: false, username: null, user_id: null })
      setCollections([])
      setSuccess(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to disconnect')
    }
  }

  const loadCollections = async () => {
    setCollectionsLoading(true)
    setError(null)
    try {
      const data = await apiClient.getZoteroCollections()
      setCollections(data.collections)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load collections')
    } finally {
      setCollectionsLoading(false)
    }
  }

  const handleImport = async () => {
    if (!resumeId) {
      setError('Open a resume first to import references into it.')
      return
    }
    setImporting(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await apiClient.importFromZotero(resumeId, selectedCollection || undefined)
      onBibTeXImported(result.bibtex, result.entries_count)
      setSuccess(`Imported ${result.entries_count} entries from Zotero`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  if (statusLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-fg-3">
        <Loader2 className="h-3 w-3 animate-spin" /> Checking Zotero…
      </div>
    )
  }

  return (
    <div className="border-t border-line">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-[11px] font-semibold text-fg-2 transition hover:text-fg"
      >
        <span className="flex items-center gap-2">
          <span className="flex h-4 w-4 items-center justify-center rounded bg-accent-soft text-[8px] font-bold text-accent-strong">Z</span>
          Zotero
          {status?.connected && (
            <span className="rounded bg-ok/15 px-1 py-0.5 text-[9px] text-ok">connected</span>
          )}
        </span>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>

      {expanded && (
        <div className="space-y-2 px-3 pb-3">
          {success && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-2 py-1.5 text-[10px] text-ok">{success}</p>
          )}
          {error && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-2 py-1.5 text-[10px] text-err">{error}</p>
          )}

          {!status?.connected ? (
            <button
              onClick={handleConnect}
              className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110"
            >
              <ExternalLink className="h-3 w-3" />
              Connect Zotero
            </button>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-fg-2">@{status.username}</span>
                <button
                  onClick={handleDisconnect}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-fg-3 transition hover:text-err"
                >
                  <Unlink className="h-3 w-3" />
                  Disconnect
                </button>
              </div>

              {/* Collection picker */}
              <div className="flex items-center gap-1">
                <select
                  value={selectedCollection}
                  onChange={e => setSelectedCollection(e.target.value)}
                  className="flex-1 rounded-[var(--radius-md)] bg-bg px-2 py-1 text-[11px] text-fg-2 ring-1 ring-line outline-none"
                >
                  <option value="">All items</option>
                  {collections.map(c => (
                    <option key={c.key} value={c.key}>{c.name}</option>
                  ))}
                </select>
                <button
                  onClick={loadCollections}
                  disabled={collectionsLoading}
                  className="rounded-[var(--radius-md)] p-1 text-fg-3 transition hover:text-fg-2 disabled:opacity-40"
                  title="Refresh collections"
                >
                  <RefreshCw className={`h-3 w-3 ${collectionsLoading ? 'animate-spin' : ''}`} />
                </button>
              </div>

              <button
                onClick={handleImport}
                disabled={importing || !resumeId}
                className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlusCircle className="h-3 w-3" />}
                {importing ? 'Importing…' : 'Import BibTeX'}
              </button>
              {!resumeId && (
                <p className="text-center text-[10px] text-fg-3">Open a resume to import</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Mendeley import section ───────────────────────────────────────────────

function MendeleySection({
  resumeId,
  onBibTeXImported,
}: {
  resumeId?: string
  onBibTeXImported: (bibtex: string, count: number) => void
}) {
  const [status, setStatus] = useState<MendeleyStatusResponse | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    apiClient.getMendeleyStatus()
      .then(setStatus)
      .catch(() => setStatus({ connected: false, name: null }))
      .finally(() => setStatusLoading(false))
  }, [])

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'mendeley:connected') {
        setStatusLoading(true)
        apiClient.getMendeleyStatus()
          .then(s => { setStatus(s); setSuccess('Mendeley connected!') })
          .catch(() => null)
          .finally(() => setStatusLoading(false))
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [])

  const handleConnect = () => {
    window.open(`${API_BASE}/mendeley/connect`, '_blank', 'width=600,height=700,popup=1')
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Mendeley?')) return
    try {
      await apiClient.disconnectMendeley()
      setStatus({ connected: false, name: null })
      setSuccess(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to disconnect')
    }
  }

  const handleImport = async () => {
    if (!resumeId) {
      setError('Open a resume first to import references into it.')
      return
    }
    setImporting(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await apiClient.importFromMendeley(resumeId)
      onBibTeXImported(result.bibtex, result.entries_count)
      setSuccess(`Imported ${result.entries_count} entries from Mendeley`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  if (statusLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-fg-3">
        <Loader2 className="h-3 w-3 animate-spin" /> Checking Mendeley…
      </div>
    )
  }

  return (
    <div className="border-t border-line">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-[11px] font-semibold text-fg-2 transition hover:text-fg"
      >
        <span className="flex items-center gap-2">
          <span className="flex h-4 w-4 items-center justify-center rounded bg-accent-soft text-[8px] font-bold text-accent-strong">M</span>
          Mendeley
          {status?.connected && (
            <span className="rounded bg-ok/15 px-1 py-0.5 text-[9px] text-ok">connected</span>
          )}
        </span>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>

      {expanded && (
        <div className="space-y-2 px-3 pb-3">
          {success && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-2 py-1.5 text-[10px] text-ok">{success}</p>
          )}
          {error && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-2 py-1.5 text-[10px] text-err">{error}</p>
          )}

          {!status?.connected ? (
            <button
              onClick={handleConnect}
              className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110"
            >
              <ExternalLink className="h-3 w-3" />
              Connect Mendeley
            </button>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-fg-2">{status.name ?? 'Connected'}</span>
                <button
                  onClick={handleDisconnect}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-fg-3 transition hover:text-err"
                >
                  <Unlink className="h-3 w-3" />
                  Disconnect
                </button>
              </div>

              <button
                onClick={handleImport}
                disabled={importing || !resumeId}
                className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {importing ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlusCircle className="h-3 w-3" />}
                {importing ? 'Importing…' : 'Import All BibTeX'}
              </button>
              {!resumeId && (
                <p className="text-center text-[10px] text-fg-3">Open a resume to import</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── ORCID import section ──────────────────────────────────────────────────

/** Strip https://orcid.org/ prefix and return bare ORCID ID, or the input unchanged. */
function normalizeOrcidInput(raw: string): string {
  const m = raw.match(/orcid\.org\/(\d{4}-\d{4}-\d{4}-[\dXx]{4})/i)
  return m ? m[1] : raw.trim()
}

function isValidOrcid(id: string): boolean {
  return /^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$/i.test(id)
}

function OrcidSection({
  onInsertBibTeX,
  onInsertCiteKey,
}: {
  onInsertBibTeX: (bibtex: string) => void
  onInsertCiteKey: (key: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [entries, setEntries] = useState<BibTeXEntry[]>([])
  const [fetched, setFetched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const orcidId = normalizeOrcidInput(input)
  const valid = isValidOrcid(orcidId)

  const handleFetch = async () => {
    if (!valid || loading) return
    setLoading(true)
    setFetched(false)
    setError(null)
    setEntries([])
    try {
      const resp = await apiClient.fetchOrcidPublications(orcidId)
      setEntries(resp.entries)
      setFetched(true)
      if (resp.entries.length === 0) setError('No publications found on this ORCID profile.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch ORCID publications')
      setFetched(true)
    } finally {
      setLoading(false)
    }
  }

  const handleInsertAll = () => {
    const allBibtex = entries.filter(e => e.bibtex).map(e => e.bibtex!).join('\n\n')
    if (allBibtex) onInsertBibTeX('\n' + allBibtex)
  }

  return (
    <div className="border-t border-line">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-[11px] font-semibold text-fg-2 transition hover:text-fg"
      >
        <span className="flex items-center gap-2">
          <span className="flex h-4 w-4 items-center justify-center rounded bg-accent-soft text-[7px] font-black text-accent-strong">iD</span>
          ORCID
        </span>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>

      {expanded && (
        <div className="space-y-2 px-3 pb-3">
          <p className="text-[10px] leading-snug text-fg-3">
            Fetch publications from a public ORCID profile
          </p>

          <div className="flex gap-1.5">
            <input
              type="text"
              value={input}
              onChange={e => { setInput(e.target.value); setFetched(false); setEntries([]) }}
              onKeyDown={e => e.key === 'Enter' && handleFetch()}
              placeholder="0000-0001-2345-6789"
              className="flex-1 rounded-[var(--radius-md)] bg-bg px-2.5 py-1.5 font-mono text-[11px] text-fg placeholder:text-fg-3 ring-1 ring-line outline-none focus:ring-line-2 transition"
            />
            <button
              onClick={handleFetch}
              disabled={!valid || loading}
              className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-2.5 py-1.5 text-[11px] font-medium text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
            </button>
          </div>

          {input && !valid && (
            <p className="text-[10px] text-warn">Format: 0000-0001-2345-6789</p>
          )}

          {error && <p className="text-[10px] text-err">{error}</p>}

          {entries.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] text-fg-3">{entries.length} publication{entries.length !== 1 ? 's' : ''} found</p>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {entries.map((entry, i) => (
                  <EntryCard
                    key={i}
                    entry={entry}
                    onInsertBibTeX={bib => onInsertBibTeX('\n' + bib)}
                    onInsertCiteKey={onInsertCiteKey}
                  />
                ))}
              </div>
              {entries.length > 1 && (
                <button
                  onClick={handleInsertAll}
                  className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/10 py-1.5 text-[10px] font-medium text-ok ring-1 ring-ok/20 transition hover:bg-ok/20"
                >
                  <PlusCircle className="h-3 w-3" />
                  Insert All ({entries.filter(e => e.bibtex).length}) BibTeX entries
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Imported library entries ──────────────────────────────────────────────

function LibrarySection({
  bibtex,
  onInsertBibTeX,
  onInsertCiteKey,
  onClear,
}: {
  bibtex: string
  onInsertBibTeX: (b: string) => void
  onInsertCiteKey: (k: string) => void
  onClear: () => void
}) {
  const [expanded, setExpanded] = useState(true)

  // Parse bibtex into rough entries by splitting on @type{
  const entries = bibtex
    .split(/(?=@\w+\s*\{)/)
    .map(e => e.trim())
    .filter(Boolean)

  if (!entries.length) return null

  // Extract cite key and type from each entry
  const parsed = entries.map(raw => {
    const match = raw.match(/^@(\w+)\s*\{([^,\s]+)/)
    return {
      type: match?.[1] ?? 'misc',
      key: match?.[2] ?? '?',
      raw,
    }
  })

  return (
    <div className="border-t border-line">
      <div className="flex w-full items-center justify-between px-3 py-2.5 text-[11px] font-semibold text-fg-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex flex-1 items-center gap-2 transition hover:text-fg text-left"
        >
          <BookOpen className="h-3.5 w-3.5" />
          Imported Library ({entries.length})
        </button>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onClear()}
            className="rounded p-0.5 text-fg-3 transition hover:text-err"
            title="Clear imported library"
          >
            <X className="h-3 w-3" />
          </button>
          <button onClick={() => setExpanded(!expanded)} className="rounded p-0.5 transition hover:text-fg">
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="max-h-64 overflow-y-auto px-3 pb-3 space-y-1.5">
          {parsed.map((p, i) => (
            <div key={i} className="flex items-center justify-between gap-2 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5">
              <div className="min-w-0 flex-1">
                <span className="rounded bg-accent-soft px-1 py-0.5 text-[9px] text-accent-strong mr-1.5">@{p.type}</span>
                <code className="text-[11px] text-accent-strong">{p.key}</code>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => onInsertCiteKey(`\\cite{${p.key}}`)}
                  className="rounded px-1.5 py-0.5 text-[9px] text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
                  title="Insert \cite{key}"
                >
                  \cite
                </button>
                <button
                  onClick={() => onInsertBibTeX('\n' + p.raw)}
                  className="rounded px-1.5 py-0.5 text-[9px] text-ok transition hover:bg-ok/10 hover:text-ok"
                  title="Insert full BibTeX entry"
                >
                  BibTeX
                </button>
              </div>
            </div>
          ))}

          <button
            onClick={() => onInsertBibTeX('\n' + bibtex)}
            className="mt-1 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/10 py-1.5 text-[10px] font-medium text-ok ring-1 ring-ok/20 transition hover:bg-ok/20"
          >
            <PlusCircle className="h-3 w-3" />
            Insert All ({entries.length}) entries
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────

export default function ReferencesPanel({ resumeId, onInsertBibTeX, onInsertCiteKey }: ReferencesPanelProps) {
  const [input, setInput] = useState('')
  const [entries, setEntries] = useState<BibTeXEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [fetched, setFetched] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [importedBibTeX, setImportedBibTeX] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Hydrate saved BibTeX from resume metadata on mount
  useEffect(() => {
    if (!resumeId) return
    apiClient.getResume(resumeId)
      .then(resume => {
        const bibtex = resume.metadata?.bibtex
        if (typeof bibtex === 'string' && bibtex) setImportedBibTeX(bibtex)
      })
      .catch(() => {})
  }, [resumeId])

  const lines = input.split('\n').filter(l => l.trim())

  const handleFetch = useCallback(async () => {
    if (!lines.length || loading) return
    setLoading(true)
    setFetched(false)
    setFetchError(null)
    try {
      const resp = await apiClient.fetchReferences(lines)
      setEntries(resp.entries)
      setFetched(true)
    } catch (err) {
      setEntries([])
      setFetched(true)
      setFetchError(err instanceof Error ? err.message : 'Failed to fetch references')
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
      <div className="shrink-0 border-b border-line px-3 py-2.5">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-3">
          <BookOpen className="h-3.5 w-3.5" />
          BibTeX Import
        </div>
        <p className="mt-1 text-[10px] leading-snug text-fg-3">
          Paste DOIs or arXiv IDs, one per line
        </p>
      </div>

      {/* Input area */}
      <div className="shrink-0 border-b border-line p-3">
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
            className="w-full resize-none rounded-[var(--radius-md)] bg-bg p-2.5 font-mono text-[11px] text-fg placeholder:text-fg-3 ring-1 ring-line outline-none focus:ring-line-2 transition"
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
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent py-1.5 text-[11px] font-medium text-accent-fg ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
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

      {/* Scrollable area: DOI/arXiv results + Zotero + Mendeley + Library */}
      <div className="flex-1 overflow-y-auto">
        {/* DOI/arXiv results */}
        <div className="p-3">
          {fetchError ? (
            <p className="text-center text-[11px] text-err">{fetchError}</p>
          ) : fetched && entries.length === 0 ? (
            <p className="text-center text-[11px] text-fg-3">No results</p>
          ) : null}

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

        {/* Zotero import */}
        <ZoteroSection
          resumeId={resumeId}
          onBibTeXImported={(bib, _count) => setImportedBibTeX(bib)}
        />

        {/* Mendeley import */}
        <MendeleySection
          resumeId={resumeId}
          onBibTeXImported={(bib, _count) => setImportedBibTeX(bib)}
        />

        {/* ORCID publications */}
        <OrcidSection
          onInsertBibTeX={onInsertBibTeX}
          onInsertCiteKey={onInsertCiteKey}
        />

        {/* Imported library */}
        {importedBibTeX && (
          <LibrarySection
            bibtex={importedBibTeX}
            onInsertBibTeX={onInsertBibTeX}
            onInsertCiteKey={onInsertCiteKey}
            onClear={() => {
              setImportedBibTeX('')
              if (resumeId) apiClient.clearResumeBibTeX(resumeId).catch(() => {})
            }}
          />
        )}
      </div>

      {/* Footer: Insert All DOI/arXiv results */}
      {successCount > 1 && (
        <div className="shrink-0 border-t border-line p-3">
          <button
            onClick={handleInsertAll}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-ok/15 py-1.5 text-[11px] font-medium text-ok ring-1 ring-ok/25 transition hover:bg-ok/25"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            Insert All ({successCount}) BibTeX entries
          </button>
        </div>
      )}
    </div>
  )
}
