'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import { X } from 'lucide-react'
import { apiClient, type CoverLetterListItem } from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function CoverLettersPage() {
  const { session, isPending: sessionLoading } = useRequireAuth()
  const [coverLetters, setCoverLetters] = useState<CoverLetterListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [isFetching, setIsFetching] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // Debounce the search query so we don't fire a request on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    if (!session) return
    let cancelled = false
    const fetchData = async () => {
      setIsFetching(true)
      try {
        const data = await apiClient.listCoverLetters(page, 20, debouncedSearch)
        if (cancelled) return
        setCoverLetters(data.cover_letters)
        setTotal(data.total)
        setTotalPages(data.pages)
      } catch {
        if (!cancelled) toast.error('Failed to load cover letters')
      } finally {
        if (!cancelled) {
          setIsFetching(false)
          setIsLoading(false)
        }
      }
    }
    fetchData()
    return () => {
      cancelled = true
    }
  }, [session, page, debouncedSearch])

  const handleDelete = async (id: string) => {
    setConfirmDeleteId(null)
    try {
      await apiClient.deleteCoverLetter(id)
      setCoverLetters((prev) => prev.filter((cl) => cl.id !== id))
      setTotal((prev) => prev - 1)
      toast.success('Cover letter deleted')
    } catch {
      toast.error('Failed to delete')
    }
  }

  const toneBadge = (tone: string) => {
    const colors: Record<string, string> = {
      formal: 'border-line bg-surface-2 text-fg-2',
      conversational: 'border-accent bg-accent-soft text-accent-strong',
      enthusiastic: 'border-warn/20 bg-warn/10 text-warn',
    }
    return colors[tone] || colors.formal
  }

  if (sessionLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="content-shell">
        <section className="mx-auto max-w-2xl rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center">
          <h1 className="text-2xl font-semibold text-fg">Sign in required</h1>
          <p className="mt-2 text-fg-2">Please sign in to view your cover letters.</p>
          <Link href="/login" className="mt-6 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110">
            Continue to Login
          </Link>
        </section>
      </div>
    )
  }

  return (
    <div className="content-shell space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Cover Letters</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Cover Letter Library</h1>
          <p className="mt-1 text-sm text-fg-2">
            All your generated cover letters across resumes.{' '}
            {total > 0 && <span className="text-accent-strong">{total} total</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
            Workspace
          </Link>
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative w-full max-w-md">
            <label htmlFor="cover-letter-search" className="sr-only">
              Search cover letters by company or role
            </label>
            <input
              id="cover-letter-search"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by company or role"
              aria-label="Search cover letters by company or role"
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 pr-24 text-sm text-fg outline-none transition focus:border-accent"
            />
            {isFetching && !isLoading && (
              <span
                aria-live="polite"
                className="pointer-events-none absolute right-9 top-1/2 -translate-y-1/2 font-ui text-[10px] uppercase tracking-[0.14em] text-fg-3"
              >
                Searching…
              </span>
            )}
            {searchQuery && !isFetching && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-[var(--radius-sm)] text-fg-3 transition hover:text-fg"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div className="flex rounded-[var(--radius-md)] border border-line bg-surface-2 p-1 text-xs">
            <button
              onClick={() => setViewMode('grid')}
              className={`rounded-[var(--radius-md)] px-3 py-1.5 uppercase tracking-[0.12em] transition ${
                viewMode === 'grid' ? 'bg-accent-soft text-accent-strong' : 'text-fg-2 hover:text-fg'
              }`}
            >
              Grid
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`rounded-[var(--radius-md)] px-3 py-1.5 uppercase tracking-[0.12em] transition ${
                viewMode === 'list' ? 'bg-accent-soft text-accent-strong' : 'text-fg-2 hover:text-fg'
              }`}
            >
              List
            </button>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="flex h-72 items-center justify-center rounded-[var(--radius-lg)] border border-line bg-surface">
          <LoadingSpinner />
        </div>
      ) : (
      <div className={isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
      {coverLetters.length === 0 ? (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface px-6 py-16 text-center">
          <h2 className="text-lg font-semibold text-fg">No cover letters yet</h2>
          <p className="mt-2 text-sm text-fg-2">
            {searchQuery
              ? `No results for "${searchQuery}".`
              : 'Generate your first cover letter from a resume in the Workspace.'}
          </p>
          {!searchQuery && (
            <Link href="/workspace" className="mt-5 inline-block rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110">
              Go to Workspace
            </Link>
          )}
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {coverLetters.map((cl) => (
            <article key={cl.id} className="flex flex-col rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs uppercase tracking-[0.14em] text-fg-3">Cover Letter</p>
                <span
                  className={`shrink-0 rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-semibold capitalize ring-1 ${toneBadge(cl.tone)}`}
                >
                  {cl.tone}
                </span>
              </div>
              <h3 className="mt-2 line-clamp-1 text-lg font-semibold text-fg">
                {cl.company_name || cl.role_title || 'Untitled'}
              </h3>
              {cl.role_title && cl.company_name && (
                <p className="mt-0.5 text-sm text-fg-2 line-clamp-1">{cl.role_title}</p>
              )}
              <p className="mt-2 text-xs text-fg-3">
                Resume:{' '}
                <Link
                  href={`/workspace/${cl.resume_id}/edit`}
                  className="text-accent-strong hover:brightness-110 transition"
                >
                  {cl.resume_title || 'Unknown'}
                </Link>
              </p>
              <p className="mt-1 text-xs text-fg-3">
                {new Date(cl.created_at).toLocaleDateString()}
              </p>

              <div className="mt-auto pt-4 flex gap-2 text-xs">
                <Link
                  href={`/workspace/${cl.resume_id}/cover-letter?cl=${cl.id}`}
                  className="flex-1 rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-2 text-center font-semibold text-accent-strong transition hover:brightness-110"
                >
                  View
                </Link>
                {confirmDeleteId === cl.id ? (
                  <>
                    <button
                      onClick={() => handleDelete(cl.id)}
                      aria-label={`Confirm delete cover letter for ${cl.company_name || cl.role_title || 'Untitled'}`}
                      className="rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-3 py-2 font-semibold text-err transition hover:bg-err/20"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(null)}
                      className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 font-semibold text-fg-2 transition hover:text-fg"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteId(cl.id)}
                    className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 font-semibold text-fg-2 transition hover:border-err/30 hover:bg-err/10 hover:text-err"
                  >
                    Delete
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-[0.14em] text-fg-3">
                <th className="px-4 py-3 font-semibold">Company / Role</th>
                <th className="px-4 py-3 font-semibold">Resume</th>
                <th className="px-4 py-3 font-semibold">Tone</th>
                <th className="px-4 py-3 font-semibold text-right">Date</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {coverLetters.map((cl) => (
                <tr key={cl.id}>
                  <td className="px-4 py-3">
                    <p className="text-sm font-medium text-fg">
                      {cl.company_name || cl.role_title || 'Untitled'}
                    </p>
                    {cl.role_title && cl.company_name && (
                      <p className="text-xs text-fg-3">{cl.role_title}</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/workspace/${cl.resume_id}/edit`}
                      className="text-sm text-accent-strong hover:brightness-110 transition"
                    >
                      {cl.resume_title || 'Unknown'}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-semibold capitalize ring-1 ${toneBadge(cl.tone)}`}
                    >
                      {cl.tone}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-fg-2">
                    {new Date(cl.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-2">
                      <Link
                        href={`/workspace/${cl.resume_id}/cover-letter?cl=${cl.id}`}
                        className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-1.5 text-xs font-semibold text-accent-strong transition hover:brightness-110"
                      >
                        View
                      </Link>
                      {confirmDeleteId === cl.id ? (
                        <>
                          <button
                            onClick={() => handleDelete(cl.id)}
                            aria-label={`Confirm delete cover letter for ${cl.company_name || cl.role_title || 'Untitled'}`}
                            className="rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-3 py-1.5 text-xs font-semibold text-err transition hover:bg-err/20"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:text-fg"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(cl.id)}
                          className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:border-err/30 hover:text-err"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
      </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:border-line-2 hover:text-fg disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-xs text-fg-3">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:border-line-2 hover:text-fg disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
