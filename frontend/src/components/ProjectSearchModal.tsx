'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, X, FileText, Clock } from 'lucide-react'
import { apiClient, type ResumeSearchResult, type SearchMatch } from '@/lib/api-client'

interface ProjectSearchModalProps {
  open: boolean
  onClose: () => void
}

function highlightLine(text: string, start: number, end: number): React.ReactNode {
  if (start >= end || start < 0 || end > text.length) return <span>{text}</span>
  return (
    <>
      <span>{text.slice(0, start)}</span>
      <mark className="bg-accent-soft text-accent-strong rounded-sm">{text.slice(start, end)}</mark>
      <span>{text.slice(end)}</span>
    </>
  )
}

function MatchSnippet({ match }: { match: SearchMatch }) {
  return (
    <div className="font-mono text-xs leading-5">
      {match.context_before.map((line, i) => (
        <div key={`b${i}`} className="text-fg-3 pl-2">{line || '\u00A0'}</div>
      ))}
      <div className="flex items-start gap-2 bg-surface-2 rounded px-2 py-0.5">
        <span className="text-fg-3 select-none shrink-0 w-8 text-right">{match.line_number}</span>
        <span className="text-fg-2 break-all">
          {highlightLine(match.line_content, match.highlight_start, match.highlight_end)}
        </span>
      </div>
      {match.context_after.map((line, i) => (
        <div key={`a${i}`} className="text-fg-3 pl-2">{line || '\u00A0'}</div>
      ))}
    </div>
  )
}

function ResultItem({
  result,
  selected,
  onSelect,
}: {
  result: ResumeSearchResult
  selected: boolean
  onSelect: (resumeId: string, lineNumber?: number) => void
}) {
  const date = new Date(result.updated_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  return (
    <div
      className={`px-4 py-3 cursor-pointer border-b border-line transition-colors ${selected ? 'bg-surface-2' : 'hover:bg-surface-2'}`}
      onClick={() => onSelect(result.resume_id, result.matches[0]?.line_number)}
    >
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-3.5 h-3.5 text-accent-strong shrink-0" />
        <span className="text-sm font-medium text-fg truncate flex-1">{result.resume_title}</span>
        <span className="flex items-center gap-1 text-xs text-fg-3 shrink-0">
          <Clock className="w-3 h-3" />
          {date}
        </span>
      </div>

      {result.matches.length > 0 && (
        <div className="space-y-1 ml-5">
          {result.matches.map((match, i) => (
            <div
              key={i}
              className="cursor-pointer"
              onClick={(e) => { e.stopPropagation(); onSelect(result.resume_id, match.line_number) }}
            >
              <MatchSnippet match={match} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ProjectSearchModal({ open, onClose }: ProjectSearchModalProps) {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ResumeSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery('')
      setResults([])
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await apiClient.searchResumes(q.trim())
      setResults(res.results)
      setSelectedIndex(0)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(val), 300)
  }

  const navigate = useCallback((resumeId: string, lineNumber?: number) => {
    onClose()
    const url = `/workspace/${resumeId}/edit${lineNumber ? `?line=${lineNumber}` : ''}`
    router.push(url)
  }, [router, onClose])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && results[selectedIndex]) {
      const r = results[selectedIndex]
      navigate(r.resume_id, r.matches[0]?.line_number)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-[var(--overlay)] backdrop-blur-sm" />

      <div
        className="relative z-10 w-full max-w-2xl bg-surface border border-line rounded-[var(--radius-lg)] shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-line">
          <Search className="w-4 h-4 text-fg-3 shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search across all resumes…"
            className="flex-1 bg-transparent text-sm text-fg placeholder:text-fg-3 outline-none"
          />
          {loading && (
            <div className="w-4 h-4 border-2 border-line border-t-accent rounded-full animate-spin shrink-0" />
          )}
          {!loading && query && (
            <button onClick={() => { setQuery(''); setResults([]) }} aria-label="Clear search" className="text-fg-3 hover:text-fg-2">
              <X className="w-4 h-4" />
            </button>
          )}
          <kbd className="hidden sm:block text-xs text-fg-3 border border-line rounded px-1.5 py-0.5">esc</kbd>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto">
          {results.length > 0 && (
            results.map((result, i) => (
              <ResultItem
                key={result.resume_id}
                result={result}
                selected={i === selectedIndex}
                onSelect={navigate}
              />
            ))
          )}

          {!loading && query.trim().length >= 2 && results.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-fg-3">
              <Search className="w-8 h-8 mb-3 opacity-40" />
              <p className="text-sm">No results for <span className="text-fg-3">"{query}"</span></p>
            </div>
          )}

          {!loading && query.trim().length < 2 && (
            <div className="flex flex-col items-center justify-center py-10 text-fg-3 text-xs">
              Type at least 2 characters to search
            </div>
          )}
        </div>

        {/* Footer */}
        {results.length > 0 && (
          <div className="px-4 py-2 border-t border-line flex items-center gap-4 text-xs text-fg-3">
            <span><kbd className="border border-line rounded px-1">↑↓</kbd> navigate</span>
            <span><kbd className="border border-line rounded px-1">↵</kbd> open</span>
            <span className="ml-auto">{results.length} resume{results.length !== 1 ? 's' : ''} matched</span>
          </div>
        )}
      </div>
    </div>
  )
}
