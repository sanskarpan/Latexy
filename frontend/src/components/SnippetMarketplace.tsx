'use client'

/**
 * Snippet Marketplace browser — Feature 82.
 *
 * Props: onInsert(content) — called when user installs / inserts a snippet.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Download,
  ThumbsUp,
  Star,
  Search,
  ChevronDown,
  Loader2,
  Package,
  Eye,
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type SnippetResponse } from '@/lib/api-client'
import SnippetPreviewModal from './SnippetPreviewModal'

// ── Types ─────────────────────────────────────────────────────────────────────

type Category = 'all' | 'header' | 'experience' | 'skills' | 'education' | 'misc'
type SortOrder = 'popular' | 'newest' | 'official'

const CATEGORIES: { id: Category; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'header', label: 'Header' },
  { id: 'experience', label: 'Experience' },
  { id: 'skills', label: 'Skills' },
  { id: 'education', label: 'Education' },
  { id: 'misc', label: 'Misc' },
]

// ── Snippet card ──────────────────────────────────────────────────────────────

function SnippetCard({
  snippet,
  onPreview,
  onInstall,
  onUpvote,
}: {
  snippet: SnippetResponse
  onPreview: () => void
  onInstall: () => void
  onUpvote: () => void
}) {
  return (
    <div className="group rounded-lg border border-white/[0.05] bg-white/[0.02] p-3 transition hover:border-white/[0.08]">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {snippet.is_official && (
              <Star size={10} className="shrink-0 text-amber-400" fill="currentColor" />
            )}
            <span className="truncate text-[11px] font-semibold text-zinc-200">
              {snippet.title}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-2 text-[10px] text-zinc-600">
            {snippet.description}
          </p>
        </div>
        <span className="shrink-0 rounded bg-white/[0.04] px-1.5 py-0.5 text-[9px] capitalize text-zinc-600">
          {snippet.category}
        </span>
      </div>

      {snippet.tags.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {snippet.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded bg-violet-500/10 px-1 py-0.5 text-[8px] text-violet-500"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className="flex items-center gap-0.5 text-[9px] text-zinc-700">
          <Download size={9} />
          {snippet.installs_count}
        </span>
        <span className="flex items-center gap-0.5 text-[9px] text-zinc-700">
          <ThumbsUp size={9} />
          {snippet.upvotes_count}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={onUpvote}
            className={`rounded p-1 text-[10px] transition ${
              snippet.upvoted_by_me
                ? 'text-violet-400 hover:text-violet-300'
                : 'text-zinc-700 hover:text-zinc-400'
            }`}
            title={snippet.upvoted_by_me ? 'Remove upvote' : 'Upvote'}
          >
            <ThumbsUp size={10} fill={snippet.upvoted_by_me ? 'currentColor' : 'none'} />
          </button>
          <button
            onClick={onPreview}
            className="flex items-center gap-0.5 rounded px-1.5 py-1 text-[9px] text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <Eye size={10} />
            Preview
          </button>
          <button
            onClick={onInstall}
            className={`flex items-center gap-0.5 rounded px-1.5 py-1 text-[9px] font-medium transition ${
              snippet.installed_by_me
                ? 'text-emerald-500 hover:text-emerald-300'
                : 'bg-violet-500/15 text-violet-300 ring-1 ring-violet-400/20 hover:bg-violet-500/25'
            }`}
          >
            <Package size={10} />
            {snippet.installed_by_me ? 'Installed' : 'Install'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface SnippetMarketplaceProps {
  onInsert: (content: string) => void
}

export default function SnippetMarketplace({ onInsert }: SnippetMarketplaceProps) {
  const [category, setCategory] = useState<Category>('all')
  const [sort, setSort] = useState<SortOrder>('popular')
  const [query, setQuery] = useState('')
  const [snippets, setSnippets] = useState<SnippetResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [previewSnippet, setPreviewSnippet] = useState<SnippetResponse | null>(null)
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(
    async (reset = false) => {
      setLoading(true)
      const off = reset ? 0 : offset
      try {
        const data = await apiClient.listSnippets({
          category: category === 'all' ? undefined : category,
          q: query.trim() || undefined,
          sort,
          offset: off,
          limit: 20,
        })
        setSnippets((prev) => (reset ? data : [...prev, ...data]))
        setOffset(off + data.length)
        setHasMore(data.length === 20)
      } catch {
        toast.error('Failed to load snippets')
      } finally {
        setLoading(false)
      }
    },
    [category, sort, query, offset],
  )

  // Reload on filter change
  useEffect(() => {
    setOffset(0)
    load(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, sort])

  // Debounced search
  const handleSearch = (q: string) => {
    setQuery(q)
    if (searchTimeout.current) clearTimeout(searchTimeout.current)
    searchTimeout.current = setTimeout(() => {
      setOffset(0)
      load(true)
    }, 300)
  }

  const handleInstall = async (snippet: SnippetResponse) => {
    try {
      await apiClient.installSnippet(snippet.id)
      onInsert(snippet.content)
      setSnippets((prev) =>
        prev.map((s) =>
          s.id === snippet.id
            ? { ...s, installed_by_me: true, installs_count: s.installs_count + 1 }
            : s,
        ),
      )
      toast.success(`"${snippet.title}" inserted at cursor`)
    } catch {
      toast.error('Failed to install snippet')
    }
  }

  const handleUpvote = async (snippet: SnippetResponse) => {
    try {
      await apiClient.upvoteSnippet(snippet.id)
      setSnippets((prev) =>
        prev.map((s) =>
          s.id === snippet.id
            ? {
                ...s,
                upvoted_by_me: !s.upvoted_by_me,
                upvotes_count: s.upvoted_by_me
                  ? Math.max(0, s.upvotes_count - 1)
                  : s.upvotes_count + 1,
              }
            : s,
        ),
      )
    } catch {
      toast.error('Failed to toggle upvote')
    }
  }

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      {/* Search */}
      <div className="relative">
        <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600" />
        <input
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder="Search snippets…"
          className="w-full rounded-lg border border-white/[0.06] bg-black/30 py-1.5 pl-7 pr-3 text-[11px] text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-violet-500/30"
        />
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-1">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setCategory(cat.id)}
            className={`rounded px-2 py-0.5 text-[10px] font-medium transition ${
              category === cat.id
                ? 'bg-violet-500/20 text-violet-300 ring-1 ring-violet-400/20'
                : 'text-zinc-600 hover:text-zinc-400'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Sort */}
      <div className="flex items-center gap-2">
        <span className="text-[9px] text-zinc-700">Sort:</span>
        {(['popular', 'newest', 'official'] as SortOrder[]).map((s) => (
          <button
            key={s}
            onClick={() => setSort(s)}
            className={`text-[9px] capitalize transition ${
              sort === s ? 'font-semibold text-zinc-300' : 'text-zinc-700 hover:text-zinc-500'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Snippet list */}
      <div className="flex-1 space-y-2 overflow-y-auto">
        {loading && snippets.length === 0 ? (
          <div className="flex justify-center py-8">
            <Loader2 size={16} className="animate-spin text-zinc-700" />
          </div>
        ) : snippets.length === 0 ? (
          <div className="py-8 text-center text-[11px] text-zinc-700">
            No snippets found. Try a different search.
          </div>
        ) : (
          <>
            {snippets.map((snippet) => (
              <SnippetCard
                key={snippet.id}
                snippet={snippet}
                onPreview={() => setPreviewSnippet(snippet)}
                onInstall={() => handleInstall(snippet)}
                onUpvote={() => handleUpvote(snippet)}
              />
            ))}
            {hasMore && (
              <button
                onClick={() => load()}
                disabled={loading}
                className="w-full py-2 text-[10px] text-zinc-700 transition hover:text-zinc-400 disabled:opacity-40"
              >
                {loading ? <Loader2 size={12} className="mx-auto animate-spin" /> : 'Load more'}
              </button>
            )}
          </>
        )}
      </div>

      {/* Preview modal */}
      {previewSnippet && (
        <SnippetPreviewModal
          snippet={previewSnippet}
          onInsert={(content) => {
            onInsert(content)
            setPreviewSnippet(null)
          }}
          onClose={() => setPreviewSnippet(null)}
        />
      )}
    </div>
  )
}
