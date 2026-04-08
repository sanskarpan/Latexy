'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { BookUser, GitFork, ChevronDown, ChevronRight, Share2, X, Search, Zap, AlertTriangle, BarChart2, Download, Loader2, Tag, Pin, PinOff, Archive, ArchiveRestore, LayoutTemplate } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type DiffWithParentResponse, type JobApplication, type JobStateResponse, type ResumeResponse, type ResumeStats, type SemanticMatchResult } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'
import SemanticMatchModal from '@/components/ats/SemanticMatchModal'
import ExportDropdown from '@/components/ExportDropdown'
import DiffViewerModal from '@/components/DiffViewerModal'
import ShareResumeModal from '@/components/ShareResumeModal'
import ProjectSearchModal from '@/components/ProjectSearchModal'
import AddApplicationModal from '@/components/AddApplicationModal'
import QuickTailorModal from '@/components/QuickTailorModal'
import OnboardingFlow, { useOnboarding } from '@/components/onboarding/OnboardingFlow'
import GenerateReferencesModal from '@/components/GenerateReferencesModal'

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

  const [atsStats, setAtsStats] = useState<ResumeStats | null>(null)
  const [staleBannerDismissed, setStaleBannerDismissed] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)

  // Onboarding for new users
  const {
    isOnboardingOpen,
    hasCompletedOnboarding,
    startOnboarding,
    completeOnboarding,
    skipOnboarding,
  } = useOnboarding()

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

  // Quick Tailor modal state
  const [quickTailorResume, setQuickTailorResume] = useState<ResumeResponse | null>(null)

  // References modal state (Feature 70)
  const [referencesModalResume, setReferencesModalResume] = useState<ResumeResponse | null>(null)

  // Feature 39 — Tags, Pin, Archive
  const [activeTagFilter, setActiveTagFilter] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const [archivedResumes, setArchivedResumes] = useState<ResumeResponse[]>([])
  const [archivedLoading, setArchivedLoading] = useState(false)
  const [tagEditResumeId, setTagEditResumeId] = useState<string | null>(null)
  const [tagEditValue, setTagEditValue] = useState('')

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

  // Show onboarding for first-time users (localStorage flag not yet set)
  useEffect(() => {
    if (session && !hasCompletedOnboarding) {
      startOnboarding()
    }
  }, [session, hasCompletedOnboarding, startOnboarding])

  useEffect(() => {
    if (!session) return

    const fetchData = async () => {
      setIsLoading(true)
      try {
        const [resumesData, jobsData, statsData] = await Promise.all([
          apiClient.listResumes(),
          apiClient.listJobs(),
          apiClient.getResumeStats().catch(() => null),
        ])
        setResumes(Array.isArray(resumesData) ? resumesData : [])
        setJobs([...(jobsData.jobs || [])].sort((a, b) => b.last_updated - a.last_updated))
        if (statsData) setAtsStats(statsData)
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

  const filteredResumes = useMemo(() => {
    let result = resumes.filter((r) => r.title.toLowerCase().includes(searchQuery.toLowerCase()))
    if (activeTagFilter) result = result.filter((r) => r.tags?.includes(activeTagFilter))
    // Pinned resumes first
    return [...result].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0))
  }, [resumes, searchQuery, activeTagFilter])

  const allTags = useMemo(() => {
    const set = new Set<string>()
    resumes.forEach(r => r.tags?.forEach(t => set.add(t)))
    return Array.from(set).sort()
  }, [resumes])

  const templateResumes = useMemo(
    () => resumes.filter(r => r.is_template),
    [resumes]
  )

  const handleBulkExport = async (format: 'tex' | 'pdf' | 'docx') => {
    setExportLoading(true)
    setExportMenuOpen(false)
    try {
      const blob = await apiClient.bulkExport(format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const date = new Date().toISOString().slice(0, 10)
      a.download = `latexy-resumes-${date}.zip`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Download started')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExportLoading(false)
    }
  }

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

  // Feature 39 handlers
  const handlePin = useCallback(async (resumeId: string, isPinned: boolean) => {
    try {
      const updated = isPinned
        ? await apiClient.unpinResume(resumeId)
        : await apiClient.pinResume(resumeId)
      setResumes(prev => prev.map(r => r.id === resumeId ? { ...r, ...updated } : r))
    } catch {
      toast.error('Failed to update pin')
    }
  }, [])

  const handleArchive = useCallback(async (resumeId: string) => {
    try {
      await apiClient.archiveResume(resumeId)
      setResumes(prev => prev.filter(r => r.id !== resumeId))
      toast.success('Resume archived')
    } catch {
      toast.error('Failed to archive resume')
    }
  }, [])

  const handleUnarchive = useCallback(async (resumeId: string) => {
    try {
      const updated = await apiClient.unarchiveResume(resumeId)
      setArchivedResumes(prev => prev.filter(r => r.id !== resumeId))
      setResumes(prev => [updated, ...prev])
      toast.success('Resume restored')
    } catch {
      toast.error('Failed to unarchive resume')
    }
  }, [])

  const handleSaveTags = useCallback(async () => {
    if (!tagEditResumeId) return
    const tags = tagEditValue
      .split(',')
      .map(t => t.trim())
      .filter(Boolean)
      .slice(0, 10)
    try {
      const updated = await apiClient.updateResumeTags(tagEditResumeId, tags)
      setResumes(prev => prev.map(r => r.id === tagEditResumeId ? { ...r, ...updated } : r))
      setTagEditResumeId(null)
      toast.success('Tags updated')
    } catch {
      toast.error('Failed to update tags')
    }
  }, [tagEditResumeId, tagEditValue])

  const loadArchivedResumes = useCallback(async () => {
    setArchivedLoading(true)
    try {
      const data = await apiClient.listResumes(1, 50, true)
      setArchivedResumes(Array.isArray(data) ? data : [])
    } catch {
      toast.error('Failed to load archived resumes')
    } finally {
      setArchivedLoading(false)
    }
  }, [])

  // Variant count for a resume (from API + local grouping)
  const getVariantCount = useCallback((resume: ResumeResponse) => {
    return Math.max(resume.variant_count ?? 0, variantMap[resume.id]?.length ?? 0)
  }, [variantMap])

  const veryStaleResumes = useMemo(
    () => resumes.filter((r) => r.freshness_status === 'very_stale'),
    [resumes]
  )

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
          {resume.pinned && (
            <span className="flex items-center gap-0.5 rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-amber-300">
              <Pin size={8} />Pinned
            </span>
          )}
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
      <p
        className={`mt-2 text-xs ${
          resume.freshness_status === 'very_stale'
            ? 'text-rose-400'
            : resume.freshness_status === 'stale'
            ? 'text-amber-400'
            : 'text-zinc-500'
        }`}
        title={new Date(resume.updated_at).toLocaleString()}
      >
        {resume.days_since_updated != null && resume.days_since_updated > 0
          ? `Updated ${resume.days_since_updated}d ago`
          : `Updated today`}
      </p>

      {/* Tag chips */}
      {resume.tags && resume.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {resume.tags.map(tag => (
            <button
              key={tag}
              onClick={() => setActiveTagFilter(activeTagFilter === tag ? null : tag)}
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium transition ${
                activeTagFilter === tag
                  ? 'bg-violet-500/30 text-violet-200 ring-1 ring-violet-400/40'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300'
              }`}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6 grid grid-cols-3 gap-2 text-xs">
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
        <button
          onClick={() => setQuickTailorResume(resume)}
          className="flex items-center justify-center gap-1 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-2 font-semibold text-amber-300 transition hover:bg-amber-500/20"
        >
          <Zap size={11} />
          Tailor
        </button>
        <Link
          href={`/workspace/${resume.id}/cover-letter`}
          className="col-span-3 rounded-lg border border-violet-300/20 bg-violet-300/10 px-3 py-2 text-center font-semibold text-violet-200 transition hover:bg-violet-300/20"
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
      <div className="mt-2">
        <button
          onClick={() => setReferencesModalResume(resume)}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] py-2 text-xs font-semibold text-zinc-500 transition hover:bg-white/[0.06] hover:text-violet-300"
        >
          <BookUser size={11} />
          Generate References Page
        </button>
      </div>

      {/* Pin / Archive / Tag actions */}
      {!isVariant && (
        <div className="mt-2 flex gap-1.5 border-t border-white/[0.05] pt-2">
          <button
            onClick={() => handlePin(resume.id, !!resume.pinned)}
            title={resume.pinned ? 'Unpin' : 'Pin to top'}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-zinc-500 transition hover:bg-amber-500/10 hover:text-amber-300"
          >
            {resume.pinned ? <PinOff size={10} /> : <Pin size={10} />}
            {resume.pinned ? 'Unpin' : 'Pin'}
          </button>
          <button
            onClick={() => {
              setTagEditResumeId(resume.id)
              setTagEditValue(resume.tags?.join(', ') ?? '')
            }}
            title="Edit tags"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-zinc-500 transition hover:bg-violet-500/10 hover:text-violet-300"
          >
            <Tag size={10} />
            Tags
          </button>
          <button
            onClick={() => {
              if (confirm(`Archive "${resume.title}"? It will be hidden from the workspace.`)) {
                handleArchive(resume.id)
              }
            }}
            title="Archive resume"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-zinc-500 transition hover:bg-rose-500/10 hover:text-rose-400"
          >
            <Archive size={10} />
            Archive
          </button>
        </div>
      )}
    </article>
  )

  return (
    <div className="content-shell space-y-6">
      {/* Stale resume banner (Feature 48) */}
      {!staleBannerDismissed && veryStaleResumes.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-400/20 bg-amber-500/[0.07] px-4 py-3">
          <div className="flex items-center gap-2.5">
            <AlertTriangle size={14} className="shrink-0 text-amber-400" />
            <p className="text-[13px] text-amber-200">
              <strong>{veryStaleResumes.length}</strong>{' '}
              {veryStaleResumes.length === 1 ? "resume hasn't" : "resumes haven't"} been updated in 90+ days.
              Update {veryStaleResumes.length === 1 ? 'it' : 'them'} to stay competitive.
            </p>
          </div>
          <button
            onClick={() => setStaleBannerDismissed(true)}
            className="shrink-0 rounded-md p-1 text-amber-500 transition hover:bg-amber-500/10 hover:text-amber-300"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      )}

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

          {/* Export All dropdown (Feature 49) */}
          <div className="relative">
            <button
              onClick={() => setExportMenuOpen(o => !o)}
              disabled={exportLoading}
              className="btn-ghost flex items-center gap-1.5 px-3 py-2 text-xs"
            >
              {exportLoading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Download size={12} />
              )}
              <span className="hidden sm:inline">Export All</span>
              <ChevronDown size={11} />
            </button>
            {exportMenuOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-white/[0.08] bg-[#111] py-1 shadow-xl">
                {([
                  { format: 'tex', label: 'LaTeX Source (.zip)' },
                  { format: 'pdf', label: 'PDF Files (.zip)' },
                  { format: 'docx', label: 'Word Docs (.zip)' },
                ] as const).map(({ format, label }) => (
                  <button
                    key={format}
                    onClick={() => handleBulkExport(format)}
                    className="w-full px-3 py-2 text-left text-[12px] text-zinc-400 transition hover:bg-white/[0.05] hover:text-zinc-200"
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

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
                        <td className={`px-4 py-3 text-right text-sm ${
                          resume.freshness_status === 'very_stale' ? 'text-rose-400' :
                          resume.freshness_status === 'stale' ? 'text-amber-400' : 'text-zinc-400'
                        }`} title={new Date(resume.updated_at).toLocaleString()}>
                          {resume.days_since_updated != null && resume.days_since_updated > 0
                            ? `${resume.days_since_updated}d ago`
                            : 'Today'}
                        </td>
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
                              onClick={() => setQuickTailorResume(resume)}
                              className="flex items-center gap-1 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20"
                            >
                              <Zap size={11} />
                              Tailor
                            </button>
                            <button
                              onClick={() => openForkModal(resume.id, resume.title)}
                              className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-400 transition hover:border-white/20 hover:text-zinc-200"
                            >
                              <GitFork size={11} />
                              Fork
                            </button>
                            <button
                              onClick={() => setReferencesModalResume(resume)}
                              className="flex items-center gap-1 rounded-lg border border-white/[0.08] px-3 py-1.5 text-xs font-semibold text-zinc-400 transition hover:border-violet-400/30 hover:text-violet-300"
                            >
                              <BookUser size={11} />
                              Refs
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
                          <td className={`px-4 py-3 text-right text-sm ${
                            variant.freshness_status === 'very_stale' ? 'text-rose-400' :
                            variant.freshness_status === 'stale' ? 'text-amber-400' : 'text-zinc-500'
                          }`} title={new Date(variant.updated_at).toLocaleString()}>
                            {variant.days_since_updated != null && variant.days_since_updated > 0
                              ? `${variant.days_since_updated}d ago`
                              : 'Today'}
                          </td>
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

          {atsStats && atsStats.optimized_count > 0 && (
            <section className="surface-panel edge-highlight p-5">
              <div className="flex items-center gap-2 mb-3">
                <BarChart2 size={13} className="text-orange-300/70" />
                <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-300">ATS Scores</h3>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-lg font-bold tabular-nums text-orange-300">
                    {atsStats.avg_ats_score != null ? Math.round(atsStats.avg_ats_score) : '—'}
                  </p>
                  <p className="text-[10px] text-zinc-600 mt-0.5">Avg</p>
                </div>
                <div>
                  <p className="text-lg font-bold tabular-nums text-emerald-400">
                    {atsStats.best_ats_score != null ? Math.round(atsStats.best_ats_score) : '—'}
                  </p>
                  <p className="text-[10px] text-zinc-600 mt-0.5">Best</p>
                </div>
                <div>
                  <p className="text-lg font-bold tabular-nums text-zinc-200">
                    {atsStats.optimized_count}
                  </p>
                  <p className="text-[10px] text-zinc-600 mt-0.5">Optimized</p>
                </div>
              </div>
            </section>
          )}

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

      {quickTailorResume && (
        <QuickTailorModal
          resumeId={quickTailorResume.id}
          resumeTitle={quickTailorResume.title}
          onClose={() => setQuickTailorResume(null)}
          onDone={(forkId) => {
            setQuickTailorResume(null)
            // Refresh resume list so the new fork appears
            apiClient.listResumes().then((data) => {
              if (Array.isArray(data)) setResumes(data)
            }).catch(() => {})
          }}
        />
      )}

      {referencesModalResume && (
        <GenerateReferencesModal
          isOpen={true}
          onClose={() => setReferencesModalResume(null)}
          resumeId={referencesModalResume.id}
          resumeTitle={referencesModalResume.title}
        />
      )}

      <OnboardingFlow
        isOpen={isOnboardingOpen}
        onComplete={completeOnboarding}
        onSkip={skipOnboarding}
        userType="new"
      />
    </div>
  )
}
