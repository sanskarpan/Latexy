'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiClient, type JobStateResponse, type ResumeResponse, type SemanticMatchResult } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'
import SemanticMatchModal from '@/components/ats/SemanticMatchModal'
import ExportDropdown from '@/components/ExportDropdown'

export default function WorkspacePage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const router = useRouter()
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [jobs, setJobs] = useState<JobStateResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [matchModalOpen, setMatchModalOpen] = useState(false)
  const [matchResults, setMatchResults] = useState<SemanticMatchResult[]>([])
  const [isMatchLoading, setIsMatchLoading] = useState(false)
  const [matchError, setMatchError] = useState<string | null>(null)

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
        const [resumesData, jobsData] = await Promise.all([apiClient.listResumes(), apiClient.listJobs()])
        setResumes(Array.isArray(resumesData) ? resumesData : [])
        setJobs([...(jobsData.jobs || [])].sort((a, b) => b.last_updated - a.last_updated))
      } catch (error) {
        if (process.env.NODE_ENV === 'development') {
          console.error('Failed to fetch workspace data', error)
        }
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [session])

  const filteredResumes = useMemo(
    () => resumes.filter((resume) => resume.title.toLowerCase().includes(searchQuery.toLowerCase())),
    [resumes, searchQuery]
  )

  const matchMap = useMemo(() => {
    const m: Record<string, SemanticMatchResult> = {}
    for (const r of matchResults) m[r.resume_id] = r
    return m
  }, [matchResults])

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
          <p className="mt-2 text-zinc-400">Please sign in to access your workspace and resumes.</p>
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
          <p className="overline">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Resume Library</h1>
          <p className="mt-1 text-sm text-zinc-400">Create, edit, and optimize resumes from a single workspace.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/workspace/history" className="btn-ghost px-4 py-2 text-xs">
            Run History
          </Link>
          <button
            onClick={() => setMatchModalOpen(true)}
            className="rounded-lg border border-violet-400/20 bg-violet-500/10 px-4 py-2 text-xs font-semibold text-violet-200 transition hover:bg-violet-500/20"
          >
            Match to Job
          </button>
          <Link href="/workspace/new" className="btn-accent px-4 py-2 text-xs">
            New Resume
          </Link>
        </div>
      </section>

      <section className="surface-panel edge-highlight p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search resume titles"
            className="w-full max-w-md rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40"
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

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section>
          {isLoading ? (
            <div className="surface-panel edge-highlight flex h-72 items-center justify-center">
              <LoadingSpinner />
            </div>
          ) : filteredResumes.length === 0 ? (
            <div className="surface-panel edge-highlight px-6 py-16 text-center">
              <h2 className="text-lg font-semibold text-white">No resumes found</h2>
              <p className="mt-2 text-sm text-zinc-400">
                {searchQuery ? `No results for "${searchQuery}".` : 'Create your first resume to start your pipeline.'}
              </p>
              {!searchQuery && (
                <Link href="/workspace/new" className="btn-accent mt-5 px-4 py-2 text-xs">
                  Create Resume
                </Link>
              )}
            </div>
          ) : viewMode === 'grid' ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {filteredResumes.map((resume) => (
                <article key={resume.id} className="surface-card edge-highlight flex flex-col p-5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Resume</p>
                    {matchMap[resume.id] && matchMap[resume.id].similarity_score != null && (
                      <span className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-bold tabular-nums ring-1 ${
                        (matchMap[resume.id].similarity_score as number) >= 0.8
                          ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-400/20'
                          : (matchMap[resume.id].similarity_score as number) >= 0.6
                          ? 'bg-amber-500/10 text-amber-300 ring-amber-400/20'
                          : 'bg-rose-500/10 text-rose-300 ring-rose-400/20'
                      }`}>
                        {Math.round((matchMap[resume.id].similarity_score as number) * 100)}% match
                      </span>
                    )}
                  </div>
                  <h3 className="mt-2 line-clamp-2 text-lg font-semibold text-white">{resume.title}</h3>
                  <p className="mt-2 text-xs text-zinc-500">Updated {new Date(resume.updated_at).toLocaleDateString()}</p>

                  <div className="mt-6 flex flex-wrap gap-2 text-xs">
                    <Link
                      href={`/workspace/${resume.id}/edit`}
                      className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-center font-semibold text-zinc-200 transition hover:bg-white/10"
                    >
                      Edit
                    </Link>
                    <Link
                      href={`/workspace/${resume.id}/optimize`}
                      className="flex-1 rounded-lg border border-orange-300/20 bg-orange-300/10 px-3 py-2 text-center font-semibold text-orange-200 transition hover:bg-orange-300/20"
                    >
                      Optimize
                    </Link>
                    <Link
                      href={`/workspace/${resume.id}/cover-letter`}
                      className="rounded-lg border border-violet-300/20 bg-violet-300/10 px-3 py-2 text-center font-semibold text-violet-200 transition hover:bg-violet-300/20"
                    >
                      CL
                    </Link>
                  </div>
                  <div className="mt-2">
                    <ExportDropdown resumeId={resume.id} variant="card" />
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="surface-panel edge-highlight overflow-hidden">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.03] text-[11px] uppercase tracking-[0.14em] text-zinc-500">
                    <th className="px-4 py-3 font-semibold">Title</th>
                    {matchResults.length > 0 && <th className="px-4 py-3 font-semibold text-right">Match</th>}
                    <th className="px-4 py-3 font-semibold text-right">Updated</th>
                    <th className="px-4 py-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10">
                  {filteredResumes.map((resume) => (
                    <tr key={resume.id}>
                      <td className="px-4 py-3">
                        <Link href={`/workspace/${resume.id}/edit`} className="text-sm font-medium text-white transition hover:text-orange-200">
                          {resume.title}
                        </Link>
                      </td>
                      {matchResults.length > 0 && (
                        <td className="px-4 py-3 text-right">
                          {matchMap[resume.id] && matchMap[resume.id].similarity_score != null ? (
                            <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold tabular-nums ring-1 ${
                              (matchMap[resume.id].similarity_score as number) >= 0.8
                                ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-400/20'
                                : (matchMap[resume.id].similarity_score as number) >= 0.6
                                ? 'bg-amber-500/10 text-amber-300 ring-amber-400/20'
                                : 'bg-rose-500/10 text-rose-300 ring-rose-400/20'
                            }`}>
                              {Math.round((matchMap[resume.id].similarity_score as number) * 100)}%
                            </span>
                          ) : (
                            <span className="text-zinc-700">—</span>
                          )}
                        </td>
                      )}
                      <td className="px-4 py-3 text-right text-sm text-zinc-400">{new Date(resume.updated_at).toLocaleDateString()}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex gap-2 items-center">
                          <Link
                            href={`/workspace/${resume.id}/edit`}
                            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white"
                          >
                            Edit
                          </Link>
                          <Link
                            href={`/workspace/${resume.id}/optimize`}
                            className="rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-1.5 text-xs font-semibold text-orange-200 transition hover:bg-orange-300/20"
                          >
                            Optimize
                          </Link>
                          <Link
                            href={`/workspace/${resume.id}/cover-letter`}
                            className="rounded-lg border border-violet-300/25 bg-violet-300/10 px-3 py-1.5 text-xs font-semibold text-violet-200 transition hover:bg-violet-300/20"
                          >
                            CL
                          </Link>
                          <ExportDropdown resumeId={resume.id} variant="toolbar" />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="surface-panel edge-highlight p-5">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-300">Recent Activity</h2>
            {jobs.length === 0 ? (
              <p className="mt-3 text-sm text-zinc-500">No recent runs yet.</p>
            ) : (
              <div className="mt-4 space-y-3">
                {jobs.slice(0, 5).map((job, index) => (
                  <div key={job.job_id ?? `${job.last_updated}-${index}`} className="rounded-lg border border-white/10 bg-black/25 p-3">
                    <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">{job.stage || 'Pipeline'}</p>
                    <p className="mt-1 text-sm capitalize text-zinc-200">{job.status}</p>
                    <p className="mt-1 text-xs text-zinc-500">{new Date(job.last_updated * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
                  </div>
                ))}
              </div>
            )}
            {jobs.length > 0 && (
              <Link href="/workspace/history" className="mt-4 inline-block text-xs font-semibold uppercase tracking-[0.12em] text-orange-200 transition hover:text-orange-100">
                View Full History
              </Link>
            )}
          </section>

          <section className="surface-panel edge-highlight p-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-300">Workflow Tip</h3>
            <p className="mt-2 text-sm text-zinc-400">
              Run one baseline compile before optimization so you can compare output and quality signals more clearly.
            </p>
          </section>
        </aside>
      </div>

      <SemanticMatchModal
        isOpen={matchModalOpen}
        onClose={() => setMatchModalOpen(false)}
        onMatch={async (jd) => {
          setIsMatchLoading(true)
          setMatchError(null)
          try {
            const res = await apiClient.semanticMatch({ job_description: jd })
            if (res.success) setMatchResults(res.results)
            else throw new Error(res.message)
          } catch (err) {
            setMatchError(err instanceof Error ? err.message : 'Match failed')
          } finally {
            setIsMatchLoading(false)
          }
        }}
        results={matchResults}
        isLoading={isMatchLoading}
        error={matchError}
      />
    </div>
  )
}
