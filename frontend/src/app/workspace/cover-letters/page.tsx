'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { apiClient, type CoverLetterListItem } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function CoverLettersPage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const router = useRouter()
  const [coverLetters, setCoverLetters] = useState<CoverLetterListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  useEffect(() => {
    if (!sessionLoading && !session) {
      router.push('/login')
    }
  }, [session, sessionLoading, router])

  useEffect(() => {
    if (!session) return
    const fetchData = async () => {
      setIsLoading(true)
      try {
        const data = await apiClient.listCoverLetters(page, 20, searchQuery)
        setCoverLetters(data.cover_letters)
        setTotal(data.total)
        setTotalPages(data.pages)
      } catch {
        toast.error('Failed to load cover letters')
      } finally {
        setIsLoading(false)
      }
    }
    fetchData()
  }, [session, page, searchQuery])

  const handleDelete = async (id: string) => {
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
      formal: 'border-zinc-400/20 bg-zinc-500/10 text-zinc-300',
      conversational: 'border-blue-400/20 bg-blue-500/10 text-blue-300',
      enthusiastic: 'border-amber-400/20 bg-amber-500/10 text-amber-300',
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
        <section className="surface-panel edge-highlight mx-auto max-w-2xl p-8 text-center">
          <h1 className="text-2xl font-semibold text-white">Sign in required</h1>
          <p className="mt-2 text-zinc-400">Please sign in to view your cover letters.</p>
          <Link href="/login" className="btn-accent mt-6">
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
          <p className="overline">Cover Letters</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Cover Letter Library</h1>
          <p className="mt-1 text-sm text-zinc-400">
            All your generated cover letters across resumes.{' '}
            {total > 0 && <span className="text-violet-300">{total} total</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/workspace" className="btn-ghost px-4 py-2 text-xs">
            Workspace
          </Link>
        </div>
      </section>

      <section className="surface-panel edge-highlight p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value)
              setPage(1)
            }}
            placeholder="Search by company or role"
            className="w-full max-w-md rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-violet-300/40"
          />
          <div className="flex rounded-lg border border-white/10 bg-white/5 p-1 text-xs">
            <button
              onClick={() => setViewMode('grid')}
              className={`rounded-md px-3 py-1.5 uppercase tracking-[0.12em] transition ${
                viewMode === 'grid' ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Grid
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`rounded-md px-3 py-1.5 uppercase tracking-[0.12em] transition ${
                viewMode === 'list' ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              List
            </button>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="surface-panel edge-highlight flex h-72 items-center justify-center">
          <LoadingSpinner />
        </div>
      ) : coverLetters.length === 0 ? (
        <div className="surface-panel edge-highlight px-6 py-16 text-center">
          <h2 className="text-lg font-semibold text-white">No cover letters yet</h2>
          <p className="mt-2 text-sm text-zinc-400">
            {searchQuery
              ? `No results for "${searchQuery}".`
              : 'Generate your first cover letter from a resume in the Workspace.'}
          </p>
          {!searchQuery && (
            <Link href="/workspace" className="btn-accent mt-5 inline-block px-4 py-2 text-xs">
              Go to Workspace
            </Link>
          )}
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {coverLetters.map((cl) => (
            <article key={cl.id} className="surface-card edge-highlight flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Cover Letter</p>
                <span
                  className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize ring-1 ${toneBadge(cl.tone)}`}
                >
                  {cl.tone}
                </span>
              </div>
              <h3 className="mt-2 line-clamp-1 text-lg font-semibold text-white">
                {cl.company_name || cl.role_title || 'Untitled'}
              </h3>
              {cl.role_title && cl.company_name && (
                <p className="mt-0.5 text-sm text-zinc-400 line-clamp-1">{cl.role_title}</p>
              )}
              <p className="mt-2 text-xs text-zinc-500">
                Resume:{' '}
                <Link
                  href={`/workspace/${cl.resume_id}/edit`}
                  className="text-violet-300 hover:text-violet-200 transition"
                >
                  {cl.resume_title || 'Unknown'}
                </Link>
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {new Date(cl.created_at).toLocaleDateString()}
              </p>

              <div className="mt-auto pt-4 flex gap-2 text-xs">
                <Link
                  href={`/workspace/${cl.resume_id}/cover-letter`}
                  className="flex-1 rounded-lg border border-violet-300/20 bg-violet-300/10 px-3 py-2 text-center font-semibold text-violet-200 transition hover:bg-violet-300/20"
                >
                  View
                </Link>
                <button
                  onClick={() => handleDelete(cl.id)}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 font-semibold text-zinc-400 transition hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-300"
                >
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="surface-panel edge-highlight overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/10 bg-white/[0.03] text-[11px] uppercase tracking-[0.14em] text-zinc-500">
                <th className="px-4 py-3 font-semibold">Company / Role</th>
                <th className="px-4 py-3 font-semibold">Resume</th>
                <th className="px-4 py-3 font-semibold">Tone</th>
                <th className="px-4 py-3 font-semibold text-right">Date</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {coverLetters.map((cl) => (
                <tr key={cl.id}>
                  <td className="px-4 py-3">
                    <p className="text-sm font-medium text-white">
                      {cl.company_name || cl.role_title || 'Untitled'}
                    </p>
                    {cl.role_title && cl.company_name && (
                      <p className="text-xs text-zinc-500">{cl.role_title}</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/workspace/${cl.resume_id}/edit`}
                      className="text-sm text-violet-300 hover:text-violet-200 transition"
                    >
                      {cl.resume_title || 'Unknown'}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize ring-1 ${toneBadge(cl.tone)}`}
                    >
                      {cl.tone}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-zinc-400">
                    {new Date(cl.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-2">
                      <Link
                        href={`/workspace/${cl.resume_id}/cover-letter`}
                        className="rounded-lg border border-violet-300/25 bg-violet-300/10 px-3 py-1.5 text-xs font-semibold text-violet-200 transition hover:bg-violet-300/20"
                      >
                        View
                      </Link>
                      <button
                        onClick={() => handleDelete(cl.id)}
                        className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-400 transition hover:border-rose-400/30 hover:text-rose-300"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-xs text-zinc-500">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
