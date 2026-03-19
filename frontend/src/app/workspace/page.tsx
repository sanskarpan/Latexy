'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { GitFork, ChevronDown, ChevronRight, Share2, X, Search } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type DiffWithParentResponse, type JobApplication, type JobStateResponse, type ResumeResponse, type SemanticMatchResult } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'
import SemanticMatchModal from '@/components/ats/SemanticMatchModal'
import ExportDropdown from '@/components/ExportDropdown'
import DiffViewerModal from '@/components/DiffViewerModal'
import ShareResumeModal from '@/components/ShareResumeModal'
import ProjectSearchModal from '@/components/ProjectSearchModal'
import AddApplicationModal from '@/components/AddApplicationModal'

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

  // Project search modal
  const [projectSearchOpen, setProjectSearchOpen] = useState(false)

  // Add to tracker modal
  const [trackerModalResumeId, setTrackerModalResumeId] = useState<string | null>(null)
  const trackerModalResume = trackerModalResumeId
    ? resumes.find((r) => r.id === trackerModalResumeId) ?? null
    : null

  // Cmd+Shift+F global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setProjectSearchOpen(true)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // Share modal state
  const [shareModalResumeId, setShareModalResumeId] = useState<string | null>(null)
  const shareModalResume = useMemo(
    () => resumes.find(r => r.id === shareModalResumeId) ?? null,
    [resumes, shareModalResumeId]
  )

  // Variant state
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set())
  const [forkModalResumeId, setForkModalResumeId] = useState<string | null>(null)
  const [forkTitle, setForkTitle] = useState('')
  const [isForking, setIsForking] = useState(false)
  const [diffData, setDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [diffVariantId, setDiffVariantId] = useState<string | null>(null)

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

  // Group resumes into masters (no parent) and variants
  const { masterResumes, variantMap } = useMemo(() => {
    const masters = filteredResumes.filter(r => !r.parent_resume_id)
    const vMap: Record<string, ResumeResponse[]> = {}
    filteredResumes.filter(r => r.parent_resume_id).forEach(r => {
      vMap[r.parent_resume_id!] ??= []
      vMap[r.parent_resume_id!].push(r)
    })
    return { masterResumes: masters, variantMap: vMap }
  }, [filteredResumes])

  const matchMap = useMemo(() => {
    const m: Record<string, SemanticMatchResult> = {}
    for (const r of matchResults) m[r.resume_id] = r
    return m
  }, [matchResults])

  const toggleExpand = useCallback((parentId: string) => {
    setExpandedParents(prev => {
      const s = new Set(prev)
      s.has(parentId) ? s.delete(parentId) : s.add(parentId)
      return s
    })
  }, [])

  const handleFork = useCallback(async (resumeId: string, title: string) => {
    setIsForking(true)
    try {
      const newResume = await apiClient.forkResume(resumeId, title || undefined)
      setForkModalResumeId(null)
      setForkTitle('')
      router.push(`/workspace/${newResume.id}/edit`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create variant')
    } finally {
      setIsForking(false)
    }
  }, [router])

  const handleCompareWithParent = useCallback(async (resumeId: string) => {
    try {
      const data = await apiClient.getResumeDiffWithParent(resumeId)
      setDiffData(data)
      setDiffVariantId(resumeId)
      setShowDiffModal(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load diff')
    }
  }, [])

  const handleDiffRestore = useCallback(async (latex: string) => {
    if (!diffVariantId) return
    try {
      await apiClient.updateResume(diffVariantId, { latex_content: latex })
      toast.success('Variant updated')
      setShowDiffModal(false)
    } catch {
      toast.error('Failed to update variant')
    }
  }, [diffVariantId])

  const openForkModal = useCallback((resumeId: string, resumeTitle: string) => {
    setForkModalResumeId(resumeId)
    setForkTitle(`${resumeTitle} — Variant`)
  }, [])

  // Variant count for a resume (from API + local grouping)
  const getVariantCount = useCallback((resume: ResumeResponse) => {
    return Math.max(resume.variant_count ?? 0, variantMap[resume.id]?.length ?? 0)
  }, [variantMap])

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

  // Shared card renderer for both master and variant resumes
  const renderResumeCard = (resume: ResumeResponse, isVariant = false, parentTitle?: string) => (
    <article key={resume.id} className={`surface-card edge-highlight flex flex-col p-5 ${isVariant ? 'border-l-2 border-l-orange-500/20' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">
            {isVariant ? 'Variant' : 'Resume'}
          </p>
          {!isVariant && getVariantCount(resume) > 0 && (
            <button
              onClick={() => toggleExpand(resume.id)}
              className="flex items-center gap-1 rounded-md bg-orange-500/10 px-2 py-0.5 text-[10px] font-semibold text-orange-300 ring-1 ring-orange-400/20 transition hover:bg-orange-500/20"
            >
              <GitFork size={10} />
              {getVariantCount(resume)}
              {expandedParents.has(resume.id) ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            </button>
          )}
        </div>
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
      {isVariant && parentTitle && (
        <p className="mt-0.5 text-[10px] text-zinc-500">Variant of: {parentTitle}</p>
      )}
      <p className="mt-2 text-xs text-zinc-500">Updated {new Date(resume.updated_at).toLocaleDateString()}</p>

      <div className="mt-6 grid grid-cols-2 gap-2 text-xs">
        <Link
          href={`/workspace/${resume.id}/edit`}
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-center font-semibold text-zinc-200 transition hover:bg-white/10"
        >
          Edit
        </Link>
        <Link
          href={`/workspace/${resume.id}/optimize`}
          className="rounded-lg border border-orange-300/20 bg-orange-300/10 px-3 py-2 text-center font-semibold text-orange-200 transition hover:bg-orange-300/20"
        >
          Optimize
        </Link>
        <Link
          href={`/workspace/${resume.id}/cover-letter`}
          className="col-span-2 rounded-lg border border-violet-300/20 bg-violet-300/10 px-3 py-2 text-center font-semibold text-violet-200 transition hover:bg-violet-300/20"
        >
          Cover Letter
        </Link>
      </div>
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => openForkModal(resume.id, resume.title)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-semibold text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-200"
        >
          <GitFork size={11} />
          Fork
        </button>
        <button
          onClick={() => setShareModalResumeId(resume.id)}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
            resume.share_token
              ? 'border-sky-400/25 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20'
              : 'border-white/10 bg-white/[0.03] text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200'
          }`}
        >
          <Share2 size={11} />
          Share
        </button>
        {isVariant && resume.parent_resume_id && (
          <button
            onClick={() => handleCompareWithParent(resume.id)}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-violet-400/20 bg-violet-500/[0.06] px-3 py-2 text-xs font-semibold text-violet-300 transition hover:bg-violet-500/10"
          >
            Compare
          </button>
        )}
        <button
          onClick={() => setTrackerModalResumeId(resume.id)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-sky-400/20 bg-sky-500/[0.06] px-3 py-2 text-xs font-semibold text-sky-300 transition hover:bg-sky-500/10"
        >
          Track
        </button>
      </div>
      <div className="mt-2">
        <ExportDropdown resumeId={resume.id} variant="card" />
      </div>
    </article>
  )

  return (
    <div className="content-shell space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="overline">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Resume Library</h1>
          <p className="mt-1 text-sm text-zinc-400">Create, edit, and optimize resumes from a single workspace.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setProjectSearchOpen(true)}
            title="Search resumes (⌘⇧F)"
            className="btn-ghost px-3 py-2 text-xs flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Search</span>
          </button>
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
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {masterResumes.map((resume) => (
                  <div key={resume.id}>
                    {renderResumeCard(resume)}
                    {expandedParents.has(resume.id) && variantMap[resume.id] && (
                      <div className="ml-6 mt-2 space-y-3 border-l-2 border-orange-500/20 pl-4">
                        {variantMap[resume.id].map((variant) => renderResumeCard(variant, true, resume.title))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
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
                  {masterResumes.map((resume) => (
                    <>
                      <tr key={resume.id}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {getVariantCount(resume) > 0 && (
                              <button
                                onClick={() => toggleExpand(resume.id)}
                                className="flex items-center gap-1 text-orange-400 transition hover:text-orange-300"
                              >
                                {expandedParents.has(resume.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              </button>
                            )}
                            <Link href={`/workspace/${resume.id}/edit`} className="text-sm font-medium text-white transition hover:text-orange-200">
                              {resume.title}
                            </Link>
                            {getVariantCount(resume) > 0 && (
                              <span className="flex items-center gap-1 rounded-md bg-orange-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-orange-300">
                                <GitFork size={9} />{getVariantCount(resume)}
                              </span>
                            )}
                          </div>
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
                            <button
                              onClick={() => openForkModal(resume.id, resume.title)}
                              className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-400 transition hover:border-white/20 hover:text-zinc-200"
                            >
                              <GitFork size={11} />
                              Fork
                            </button>
                            <ExportDropdown resumeId={resume.id} variant="toolbar" />
                          </div>
                        </td>
                      </tr>
                      {expandedParents.has(resume.id) && variantMap[resume.id]?.map((variant) => (
                        <tr key={variant.id} className="bg-white/[0.01]">
                          <td className="py-3 pl-12 pr-4">
                            <div className="flex items-center gap-2">
                              <GitFork size={11} className="text-orange-500/50" />
                              <Link href={`/workspace/${variant.id}/edit`} className="text-sm font-medium text-zinc-300 transition hover:text-orange-200">
                                {variant.title}
                              </Link>
                              <span className="text-[10px] text-zinc-600">variant</span>
                            </div>
                          </td>
                          {matchResults.length > 0 && (
                            <td className="px-4 py-3 text-right">
                              <span className="text-zinc-700">—</span>
                            </td>
                          )}
                          <td className="px-4 py-3 text-right text-sm text-zinc-500">{new Date(variant.updated_at).toLocaleDateString()}</td>
                          <td className="px-4 py-3 text-right">
                            <div className="inline-flex gap-2 items-center">
                              <Link
                                href={`/workspace/${variant.id}/edit`}
                                className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white"
                              >
                                Edit
                              </Link>
                              <button
                                onClick={() => handleCompareWithParent(variant.id)}
                                className="rounded-lg border border-violet-400/20 bg-violet-500/[0.06] px-3 py-1.5 text-xs font-semibold text-violet-300 transition hover:bg-violet-500/10"
                              >
                                Compare
                              </button>
                              <button
                                onClick={() => openForkModal(variant.id, variant.title)}
                                className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-400 transition hover:border-white/20 hover:text-zinc-202"
                              >
                                <GitFork size={11} />
                                Fork
                              </button>
                              <ExportDropdown resumeId={variant.id} variant="toolbar" />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </>
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
              Use <strong className="text-zinc-300">Fork</strong> to create role-specific variants of a resume. Edit each variant independently, then compare with the parent to review changes.
            </p>
          </section>
        </aside>
      </div>

      {/* Fork modal */}
      {forkModalResumeId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setForkModalResumeId(null)}>
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-white">Create Variant</h3>
              <button onClick={() => setForkModalResumeId(null)} className="rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300">
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-zinc-500 mb-4">This creates a linked copy you can customize for a specific role.</p>
            <input
              type="text"
              value={forkTitle}
              onChange={e => setForkTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !isForking) handleFork(forkModalResumeId, forkTitle); if (e.key === 'Escape') setForkModalResumeId(null) }}
              placeholder="Variant title"
              autoFocus
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-orange-300/40 mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setForkModalResumeId(null)}
                className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
              >
                Cancel
              </button>
              <button
                onClick={() => handleFork(forkModalResumeId, forkTitle)}
                disabled={isForking}
                className="btn-accent px-4 py-2 text-xs disabled:opacity-50"
              >
                {isForking ? 'Creating...' : 'Create Variant'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Diff modal */}
      {showDiffModal && diffData && (
        <DiffViewerModal
          resumeId=""
          checkpointA={null}
          checkpointB={null}
          onRestore={handleDiffRestore}
          onClose={() => setShowDiffModal(false)}
          parentLatex={diffData.parent_latex}
          parentTitle={diffData.parent_title}
          variantLatex={diffData.variant_latex}
          variantTitle={diffData.variant_title}
        />
      )}

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

      <ProjectSearchModal
        open={projectSearchOpen}
        onClose={() => setProjectSearchOpen(false)}
      />

      {shareModalResumeId && shareModalResume && (
        <ShareResumeModal
          resumeId={shareModalResumeId}
          resumeTitle={shareModalResume.title}
          initialShareToken={shareModalResume.share_token}
          initialShareUrl={shareModalResume.share_url}
          onClose={() => setShareModalResumeId(null)}
          onShareTokenChange={(token, url) => {
            setResumes(prev =>
              prev.map(r =>
                r.id === shareModalResumeId
                  ? { ...r, share_token: token, share_url: url }
                  : r
              )
            )
          }}
        />
      )}

      {trackerModalResumeId && (
        <AddApplicationModal
          onClose={() => setTrackerModalResumeId(null)}
          onCreated={(_app: JobApplication) => setTrackerModalResumeId(null)}
          prefillResumeId={trackerModalResumeId}
          prefillResumeTitle={trackerModalResume?.title}
        />
      )}
    </div>
  )
}
