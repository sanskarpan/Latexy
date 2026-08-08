'use client'

import { useState } from 'react'
import { BookOpen, Loader2, Plus } from 'lucide-react'
import { apiClient, type PublicationOut } from '@/lib/api-client'

const PUB_TYPES = [
  { key: 'journal', label: 'Journal' },
  { key: 'conference', label: 'Conference' },
  { key: 'preprint', label: 'Preprint' },
  { key: 'book_chapter', label: 'Book Chapter' },
] as const

interface PublicationsPanelProps {
  insertAtCursor: (text: string) => void
}

export default function PublicationsPanel({ insertAtCursor }: PublicationsPanelProps) {
  const [orcidId, setOrcidId] = useState('')
  const [yearFrom, setYearFrom] = useState('')
  const [yearTo, setYearTo] = useState('')
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [publications, setPublications] = useState<PublicationOut[]>([])
  const [selectedPubs, setSelectedPubs] = useState<Set<number>>(new Set())
  const [latexSection, setLatexSection] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasFetched, setHasFetched] = useState(false)

  const toggleType = (key: string) => {
    setSelectedTypes(prev =>
      prev.includes(key) ? prev.filter(t => t !== key) : [...prev, key]
    )
  }

  const togglePub = (idx: number) => {
    setSelectedPubs(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const selectAll = () =>
    setSelectedPubs(new Set(publications.map((_, i) => i)))

  const deselectAll = () => setSelectedPubs(new Set())

  const handleFetch = async () => {
    const id = orcidId.trim()
    if (!id) return
    setIsLoading(true)
    setError(null)
    setPublications([])
    setSelectedPubs(new Set())
    setLatexSection('')
    setHasFetched(false)
    try {
      const data = await apiClient.generatePublications({
        source: 'orcid',
        identifier: id,
        year_from: yearFrom ? parseInt(yearFrom, 10) : undefined,
        year_to: yearTo ? parseInt(yearTo, 10) : undefined,
        pub_types: selectedTypes.length > 0 ? selectedTypes : undefined,
      })
      setPublications(data.publications)
      setLatexSection(data.latex_section)
      setSelectedPubs(new Set(data.publications.map((_, i) => i)))
      setHasFetched(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch publications')
    } finally {
      setIsLoading(false)
    }
  }

  const handleInsert = () => {
    const selected = publications.filter((_, i) => selectedPubs.has(i))
    if (selected.length === 0) return
    // Use backend-generated latex if all pubs are selected, else build from selection
    const section =
      selected.length === publications.length && latexSection
        ? latexSection
        : buildLatexFromSelected(selected)
    insertAtCursor('\n' + section + '\n')
  }

  const buildLatexFromSelected = (pubs: PublicationOut[]): string => {
    const items = pubs.map(p => {
      const authorStr = p.authors.length > 0 ? p.authors.join(', ') + '.' : ''
      const titleStr = `\`\`${p.title}.''`
      const venueStr = p.venue ? `\\textit{${p.venue}}` : ''
      const yearStr = p.year ? String(p.year) : ''
      const doiStr = p.doi ? ` \\href{https://doi.org/${p.doi}}{${p.doi}}` : ''
      const parts = [authorStr, titleStr, venueStr, yearStr].filter(Boolean)
      let entry = parts.join(' ')
      if (parts.length > 0) entry = entry.replace(/\.$/, '') + '.'
      return `  \\item ${entry}${doiStr}`
    })
    return `\\section{Publications}\n\\begin{enumerate}\n${items.join('\n')}\n\\end{enumerate}`
  }

  const pubTypeLabel = (pub_type: string) =>
    PUB_TYPES.find(t => t.key === pub_type)?.label ?? pub_type

  return (
    <div className="space-y-5">
      {/* ORCID ID input */}
      <div>
        <label className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
          ORCID iD
        </label>
        <input
          type="text"
          value={orcidId}
          onChange={e => setOrcidId(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleFetch() }}
          placeholder="0000-0000-0000-0000"
          className="w-full rounded-[var(--radius-lg)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent font-mono"
        />
        <p className="mt-1 text-[11px] text-fg-3">
          Find your ORCID iD at orcid.org — it's free and identifies you across publications.
        </p>
      </div>

      {/* Filters row */}
      <div className="flex flex-wrap gap-4">
        {/* Year range */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-3">Year:</span>
          <input
            type="number"
            value={yearFrom}
            onChange={e => setYearFrom(e.target.value)}
            placeholder="From"
            min={1900}
            max={2100}
            className="w-20 rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-xs text-fg outline-none transition focus:border-accent"
          />
          <span className="text-xs text-fg-3">–</span>
          <input
            type="number"
            value={yearTo}
            onChange={e => setYearTo(e.target.value)}
            placeholder="To"
            min={1900}
            max={2100}
            className="w-20 rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-xs text-fg outline-none transition focus:border-accent"
          />
        </div>

        {/* Publication type checkboxes */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-fg-3">Types:</span>
          {PUB_TYPES.map(t => (
            <label key={t.key} className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={selectedTypes.includes(t.key)}
                onChange={() => toggleType(t.key)}
                className="accent-accent"
              />
              <span className="text-xs text-fg-2">{t.label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Fetch button */}
      <button
        onClick={handleFetch}
        disabled={isLoading || !orcidId.trim()}
        className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2.5 text-sm font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
        {isLoading ? 'Fetching…' : 'Fetch Publications'}
      </button>

      {error && (
        <div className="rounded-[var(--radius-md)] border border-err/20 bg-err/10 px-4 py-3 text-sm text-err">
          {error}
        </div>
      )}

      {hasFetched && publications.length === 0 && (
        <p className="text-sm text-fg-3">
          No publications found for this ORCID iD with the current filters.
        </p>
      )}

      {publications.length > 0 && (
        <div className="space-y-3">
          {/* Selection controls */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-fg-2">
              {selectedPubs.size} of {publications.length} selected
            </span>
            <div className="flex gap-3">
              <button onClick={selectAll} className="text-[11px] text-accent-strong hover:brightness-110 transition">
                Select all
              </button>
              <button onClick={deselectAll} className="text-[11px] text-fg-3 hover:text-fg-2 transition">
                Deselect all
              </button>
            </div>
          </div>

          {/* Publication list */}
          <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
            {publications.map((pub, i) => (
              <label
                key={i}
                className={`flex cursor-pointer items-start gap-3 rounded-[var(--radius-md)] border p-3 transition ${
                  selectedPubs.has(i)
                    ? 'border-accent bg-accent-soft'
                    : 'border-line bg-surface-2 hover:border-line-2'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedPubs.has(i)}
                  onChange={() => togglePub(i)}
                  className="mt-0.5 shrink-0 accent-accent"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold leading-snug text-fg">{pub.title}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {pub.venue && (
                      <span className="text-[10px] italic text-fg-3">{pub.venue}</span>
                    )}
                    {pub.year && (
                      <span className="text-[10px] text-fg-3">{pub.year}</span>
                    )}
                    <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-3 ring-1 ring-line">
                      {pubTypeLabel(pub.pub_type)}
                    </span>
                    {pub.doi && (
                      <span className="text-[10px] font-mono text-fg-3">{pub.doi}</span>
                    )}
                  </div>
                </div>
              </label>
            ))}
          </div>

          {/* Insert button */}
          <button
            onClick={handleInsert}
            disabled={selectedPubs.size === 0}
            className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={14} />
            Insert Publications Section ({selectedPubs.size})
          </button>
        </div>
      )}
    </div>
  )
}
