'use client'

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { BookUser, GitFork, GitMerge, ChevronDown, ChevronRight, Share2, X, Search, Zap, AlertTriangle, BarChart2, Download, Loader2, Tag, Pin, PinOff, Archive, ArchiveRestore, LayoutTemplate, Globe, Send, MoreHorizontal, Pencil, Sparkles, FileText, Languages, Briefcase, Trash2, ArrowUpDown } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type DiffWithParentResponse, type JobApplication, type JobResultResponse, type JobStateResponse, type ResumeResponse, type ResumeStats, type SemanticMatchResult, type TranslateResumeResponse } from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
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
import ApplyModal from '@/components/ApplyModal'

// ── Translation languages (Feature 44) ────────────────────────────────────
const TRANSLATE_LANGUAGES = [
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
  { code: 'es', name: 'Spanish' },
  { code: 'it', name: 'Italian' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'nl', name: 'Dutch' },
  { code: 'ru', name: 'Russian' },
  { code: 'zh', name: 'Chinese (Simplified)' },
  { code: 'ja', name: 'Japanese' },
  { code: 'ko', name: 'Korean' },
  { code: 'ar', name: 'Arabic' },
  { code: 'hi', name: 'Hindi' },
  { code: 'pl', name: 'Polish' },
  { code: 'sv', name: 'Swedish' },
  { code: 'da', name: 'Danish' },
  { code: 'fi', name: 'Finnish' },
  { code: 'no', name: 'Norwegian' },
  { code: 'tr', name: 'Turkish' },
  { code: 'cs', name: 'Czech' },
  { code: 'ro', name: 'Romanian' },
  { code: 'hu', name: 'Hungarian' },
  { code: 'uk', name: 'Ukrainian' },
  { code: 'id', name: 'Indonesian' },
  { code: 'vi', name: 'Vietnamese' },
]

export default function WorkspacePage() {
  const { session, isPending: sessionLoading } = useRequireAuth()
  const router = useRouter()
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [jobs, setJobs] = useState<JobStateResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [sortBy, setSortBy] = useState<'updated' | 'name' | 'freshness' | 'match'>('updated')
  const [openCardMenu, setOpenCardMenu] = useState<string | null>(null)
  const [matchModalOpen, setMatchModalOpen] = useState(false)
  const [matchResults, setMatchResults] = useState<SemanticMatchResult[]>([])
  const [isMatchLoading, setIsMatchLoading] = useState(false)
  const [matchError, setMatchError] = useState<string | null>(null)

  const [atsStats, setAtsStats] = useState<ResumeStats | null>(null)
  const [staleBannerDismissed, setStaleBannerDismissed] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [exportMenuFlipUp, setExportMenuFlipUp] = useState(false)
  const exportMenuTriggerRef = useRef<HTMLButtonElement>(null)
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

  // Quick Apply modal (Feature 87)
  const [applyModalResume, setApplyModalResume] = useState<ResumeResponse | null>(null)

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
  const [archiveConfirmResume, setArchiveConfirmResume] = useState<ResumeResponse | null>(null)
  const [isArchiving, setIsArchiving] = useState(false)
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null)
  const [jobResultCache, setJobResultCache] = useState<Record<string, JobResultResponse | null>>({})
  const [jobResultLoading, setJobResultLoading] = useState<string | null>(null)

  // Variant state
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set())
  const [forkModalResumeId, setForkModalResumeId] = useState<string | null>(null)
  const [forkTitle, setForkTitle] = useState('')
  const [isForking, setIsForking] = useState(false)
  const [translateModalResumeId, setTranslateModalResumeId] = useState<string | null>(null)
  const [translateSelectedLang, setTranslateSelectedLang] = useState('fr')
  const [isTranslating, setIsTranslating] = useState(false)
  const [isGeneratingPortfolio, setIsGeneratingPortfolio] = useState<string | null>(null)
  const [portfolioUrls, setPortfolioUrls] = useState<Record<string, string>>({})
  const [diffData, setDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [diffVariantId, setDiffVariantId] = useState<string | null>(null)

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
    const scoreMap = new Map(matchResults.map((m) => [m.resume_id, m.similarity_score ?? -1]))
    // Pinned resumes always first, then the chosen sort order.
    return [...result].sort((a, b) => {
      const pinDiff = (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0)
      if (pinDiff !== 0) return pinDiff
      switch (sortBy) {
        case 'name':
          return a.title.localeCompare(b.title)
        case 'freshness':
          // Stalest first — surfaces resumes that need refreshing.
          return (b.days_since_updated ?? 0) - (a.days_since_updated ?? 0)
        case 'match':
          return (scoreMap.get(b.id) ?? -1) - (scoreMap.get(a.id) ?? -1)
        case 'updated':
        default:
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      }
    })
  }, [resumes, searchQuery, activeTagFilter, sortBy, matchResults])

  const isFiltered = searchQuery.trim().length > 0 || activeTagFilter !== null

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

  // Export only the currently visible (search/tag filtered) resumes.
  // The bulk endpoint exports everything, so we export each filtered
  // resume individually to respect the active filter.
  const handleFilteredExport = async (format: 'tex' | 'pdf' | 'docx') => {
    const targets = filteredResumes
    if (targets.length === 0) return
    setExportLoading(true)
    setExportMenuOpen(false)
    try {
      for (const resume of targets) {
        const blob = await apiClient.exportResume(resume.id, format)
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        const safeName = resume.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase() || 'resume'
        a.download = `${safeName}.${format}`
        a.click()
        URL.revokeObjectURL(url)
      }
      toast.success(`Exported ${targets.length} resume${targets.length === 1 ? '' : 's'}`)
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

  const handleTranslate = useCallback(async (resumeId: string, langCode: string) => {
    const lang = TRANSLATE_LANGUAGES.find(l => l.code === langCode)
    if (!lang) return
    setIsTranslating(true)
    try {
      const result: TranslateResumeResponse = await apiClient.translateResume({
        resume_id: resumeId,
        target_language: lang.name,
        language_code: langCode,
      })
      setTranslateModalResumeId(null)
      toast.success('Translation created', {
        description: `Opening ${lang.name} variant…`,
        action: {
          label: 'Open',
          onClick: () => router.push(`/workspace/${result.variant_resume_id}/edit`),
        },
      })
      router.push(`/workspace/${result.variant_resume_id}/edit`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Translation failed')
    } finally {
      setIsTranslating(false)
    }
  }, [router])

  const handleGeneratePortfolio = useCallback(async (resumeId: string) => {
    setIsGeneratingPortfolio(resumeId)
    try {
      const result = await apiClient.generatePortfolioSite(resumeId)
      setPortfolioUrls(prev => ({ ...prev, [resumeId]: result.portfolio_url }))
      toast.success('Portfolio site generated', {
        description: 'Your portfolio page is ready.',
        action: { label: 'View', onClick: () => window.open(result.portfolio_url, '_blank') },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Portfolio generation failed')
    } finally {
      setIsGeneratingPortfolio(null)
    }
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
    setIsArchiving(true)
    try {
      await apiClient.archiveResume(resumeId)
      setResumes(prev => prev.filter(r => r.id !== resumeId))
      toast.success('Resume archived')
      setArchiveConfirmResume(null)
    } catch {
      toast.error('Failed to archive resume')
    } finally {
      setIsArchiving(false)
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

  const handleDeletePermanently = useCallback(async (resumeId: string) => {
    try {
      await apiClient.deleteResume(resumeId)
      setArchivedResumes(prev => prev.filter(r => r.id !== resumeId))
      toast.success('Resume deleted permanently')
    } catch {
      toast.error('Failed to delete resume')
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

  // Clicking a Recent Activity row expands it in place with the run's
  // result (PDF link / ATS score / error), so a specific recent run is
  // actionable instead of a dead end.
  const handleToggleJobDetail = useCallback(async (jobId: string) => {
    setExpandedJobId(prev => (prev === jobId ? null : jobId))
    if (jobResultCache[jobId] !== undefined) return
    setJobResultLoading(jobId)
    try {
      const result = await apiClient.getJobResult(jobId)
      setJobResultCache(prev => ({ ...prev, [jobId]: result }))
    } catch {
      setJobResultCache(prev => ({ ...prev, [jobId]: null }))
    } finally {
      setJobResultLoading(null)
    }
  }, [jobResultCache])

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
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface mx-auto max-w-2xl p-8 text-center">
          <h1 className="text-2xl font-semibold text-fg">Sign in required</h1>
          <p className="mt-2 text-fg-2">Please sign in to access your workspace and resumes.</p>
          <Link href="/login" className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 mt-6">
            Continue to Login
          </Link>
        </section>
      </div>
    )
  }

  // Shared overflow (…) menu — used by both grid cards and list rows so
  // switching view mode never removes capabilities.
  const renderActionMenu = (resume: ResumeResponse, isVariant = false) => (
    <div className="relative">
      <button
        onClick={() => setOpenCardMenu(openCardMenu === resume.id ? null : resume.id)}
        aria-label="More actions"
        aria-expanded={openCardMenu === resume.id}
        className="grid h-9 w-9 place-items-center rounded-[var(--radius-md)] border border-line bg-surface-2 text-fg-2 transition hover:text-fg hover:brightness-110"
      >
        <MoreHorizontal size={16} />
      </button>
      {openCardMenu === resume.id && (
        <>
          <button
            aria-hidden
            tabIndex={-1}
            onClick={() => setOpenCardMenu(null)}
            className="fixed inset-0 z-40 cursor-default"
          />
          <div className="absolute right-0 top-10 z-50 w-56 rounded-[var(--radius-md)] border border-line bg-surface py-1 shadow-[var(--shadow-2)]">
            <button onClick={() => { setOpenCardMenu(null); setQuickTailorResume(resume) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <Zap size={13} className="text-fg-3" /> Tailor to a job
            </button>
            <Link href={`/workspace/${resume.id}/cover-letter`} onClick={() => setOpenCardMenu(null)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <FileText size={13} className="text-fg-3" /> Cover letter
            </Link>
            <button onClick={() => { setOpenCardMenu(null); openForkModal(resume.id, resume.title) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <GitFork size={13} className="text-fg-3" /> Fork a variant
            </button>
            {isVariant && resume.parent_resume_id && (
              <button onClick={() => { setOpenCardMenu(null); handleCompareWithParent(resume.id) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
                <GitMerge size={13} className="text-fg-3" /> Compare with parent
              </button>
            )}
            <button onClick={() => { setOpenCardMenu(null); setTranslateModalResumeId(resume.id); setTranslateSelectedLang('fr') }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <Languages size={13} className="text-fg-3" /> Translate
            </button>
            <button onClick={() => { setOpenCardMenu(null); portfolioUrls[resume.id] ? window.open(portfolioUrls[resume.id], '_blank', 'noopener,noreferrer') : handleGeneratePortfolio(resume.id) }} disabled={isGeneratingPortfolio === resume.id} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg disabled:opacity-50">
              {isGeneratingPortfolio === resume.id ? <Loader2 size={13} className="animate-spin text-fg-3" /> : <Globe size={13} className="text-fg-3" />}
              {portfolioUrls[resume.id] ? 'View portfolio' : 'Portfolio site'}
            </button>
            <button onClick={() => { setOpenCardMenu(null); setShareModalResumeId(resume.id) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <Share2 size={13} className="text-fg-3" /> {resume.share_token ? 'Manage share link' : 'Share'}
            </button>
            <button
              onClick={() => { setOpenCardMenu(null); setApplyModalResume(resume) }}
              title="Fill out and submit an application for a specific job posting using this resume"
              className="flex w-full items-start gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg"
            >
              <Send size={13} className="mt-0.5 shrink-0 text-fg-3" />
              <span>
                <span className="block">Quick apply</span>
                <span className="block text-[10px] text-fg-3">Submit an application now</span>
              </span>
            </button>
            <button
              onClick={() => { setOpenCardMenu(null); setTrackerModalResumeId(resume.id) }}
              title="Log a job you already applied to elsewhere, so you can track its status here"
              className="flex w-full items-start gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg"
            >
              <Briefcase size={13} className="mt-0.5 shrink-0 text-fg-3" />
              <span>
                <span className="block">Add to tracker</span>
                <span className="block text-[10px] text-fg-3">Log an application you already made</span>
              </span>
            </button>
            <button onClick={() => { setOpenCardMenu(null); setReferencesModalResume(resume) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
              <BookUser size={13} className="text-fg-3" /> References page
            </button>
            <div className="my-1 border-t border-line" />
            <div className="px-2 py-0.5"><ExportDropdown resumeId={resume.id} variant="card" /></div>
            {!isVariant && (
              <>
                <div className="my-1 border-t border-line" />
                <button onClick={() => { setOpenCardMenu(null); handlePin(resume.id, !!resume.pinned) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
                  {resume.pinned ? <PinOff size={13} className="text-fg-3" /> : <Pin size={13} className="text-fg-3" />}
                  {resume.pinned ? 'Unpin' : 'Pin to top'}
                </button>
                <button onClick={() => { setOpenCardMenu(null); setTagEditResumeId(resume.id); setTagEditValue(resume.tags?.join(', ') ?? '') }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg">
                  <Tag size={13} className="text-fg-3" /> Edit tags
                </button>
                <button onClick={() => { setOpenCardMenu(null); setArchiveConfirmResume(resume) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-err/80 transition hover:bg-err/10 hover:text-err">
                  <Archive size={13} /> Archive
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )

  // Shared card renderer for both master and variant resumes
  const renderResumeCard = (resume: ResumeResponse, isVariant = false, parentTitle?: string) => (
    <article key={resume.id} className={`rounded-[var(--radius-lg)] border border-line bg-surface flex flex-col p-5 ${isVariant ? 'border-l-2 border-l-accent/20' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <p className="text-xs uppercase tracking-[0.14em] text-fg-3">
            {isVariant ? 'Variant' : 'Resume'}
          </p>
          {resume.pinned && (
            <span className="flex items-center gap-0.5 rounded bg-warn/15 px-1.5 py-0.5 text-[9px] font-semibold text-warn">
              <Pin size={8} />Pinned
            </span>
          )}
          {!isVariant && getVariantCount(resume) > 0 && (
            <button
              onClick={() => toggleExpand(resume.id)}
              className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110"
            >
              <GitFork size={10} />
              {getVariantCount(resume)}
              {expandedParents.has(resume.id) ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            </button>
          )}
        </div>
        {matchMap[resume.id] && matchMap[resume.id].similarity_score != null && (
          <span className={`shrink-0 rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-bold tabular-nums ring-1 ${
            (matchMap[resume.id].similarity_score as number) >= 0.8
              ? 'bg-ok/10 text-ok ring-ok/20'
              : (matchMap[resume.id].similarity_score as number) >= 0.6
              ? 'bg-warn/10 text-warn ring-warn/20'
              : 'bg-err/10 text-err ring-err/20'
          }`}>
            {Math.round((matchMap[resume.id].similarity_score as number) * 100)}% match
          </span>
        )}
      </div>
      <h3 className="mt-2 line-clamp-2 text-lg font-semibold text-fg">{resume.title}</h3>
      {isVariant && parentTitle && (
        <p className="mt-0.5 text-[10px] text-fg-3">Variant of: {parentTitle}</p>
      )}
      <p
        className={`mt-2 text-xs ${
          resume.freshness_status === 'very_stale'
            ? 'text-err'
            : resume.freshness_status === 'stale'
            ? 'text-warn'
            : 'text-fg-3'
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
                  ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
                  : 'bg-surface-2 text-fg-2 hover:brightness-110 hover:text-fg'
              }`}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      {/* Primary actions + overflow menu */}
      <div className="mt-5 flex items-center gap-2">
        <Link
          href={`/workspace/${resume.id}/edit`}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs font-semibold text-fg transition hover:brightness-110"
        >
          <Pencil size={12} /> Edit
        </Link>
        <Link
          href={`/workspace/${resume.id}/optimize`}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
        >
          <Sparkles size={12} /> Optimize
        </Link>
        {renderActionMenu(resume, isVariant)}
      </div>
    </article>
  )

  return (
    <div className="content-shell space-y-6">
      {/* Stale resume banner (Feature 48) */}
      {!staleBannerDismissed && veryStaleResumes.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-warn/20 bg-warn/[0.07] px-4 py-3">
          <div className="flex items-center gap-2.5">
            <AlertTriangle size={14} className="shrink-0 text-warn" />
            <p className="text-[13px] text-warn">
              <strong>{veryStaleResumes.length}</strong>{' '}
              {veryStaleResumes.length === 1 ? "resume hasn't" : "resumes haven't"} been updated in 90+ days.
              Update {veryStaleResumes.length === 1 ? 'it' : 'them'} to stay competitive.
            </p>
          </div>
          <button
            onClick={() => setStaleBannerDismissed(true)}
            className="shrink-0 rounded-[var(--radius-md)] p-1 text-warn transition hover:bg-warn/10 hover:text-warn"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Resume Library</h1>
          <p className="mt-1 text-sm text-fg-2">Create, edit, and optimize resumes from a single workspace.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setProjectSearchOpen(true)}
            title="Search resume content — full text (⌘⇧F)"
            className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-3 py-2 text-xs flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Search content <span className="text-fg-3">⌘⇧F</span></span>
          </button>
          <Link href="/workspace/history" className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 px-4 py-2 text-xs">
            Run History
          </Link>
          <button
            onClick={() => setMatchModalOpen(true)}
            className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-4 py-2 text-xs font-semibold text-accent-strong transition hover:brightness-110"
          >
            Match to Job
          </button>

          {/* Export dropdown (Feature 49) */}
          <div className="relative">
            <button
              ref={exportMenuTriggerRef}
              onClick={() => {
                if (!exportMenuOpen && exportMenuTriggerRef.current) {
                  const rect = exportMenuTriggerRef.current.getBoundingClientRect()
                  const spaceBelow = window.innerHeight - rect.bottom
                  const spaceAbove = rect.top
                  setExportMenuFlipUp(spaceBelow < 220 && spaceAbove > spaceBelow)
                }
                setExportMenuOpen(o => !o)
              }}
              disabled={exportLoading}
              className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 flex items-center gap-1.5 px-3 py-2 text-xs"
            >
              {exportLoading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Download size={12} />
              )}
              <span className="hidden sm:inline">Export</span>
              <ChevronDown size={11} />
            </button>
            {exportMenuOpen && (
              <div className={`absolute right-0 z-50 max-h-[min(24rem,calc(100vh-6rem))] w-56 overflow-y-auto rounded-[var(--radius-md)] border border-line bg-surface py-1 shadow-[var(--shadow-2)] ${
                exportMenuFlipUp ? 'bottom-full mb-1' : 'top-full mt-1'
              }`}>
                {isFiltered && (
                  <>
                    <p className="px-3 pb-1 pt-1.5 text-[10px] font-mono uppercase tracking-[0.12em] text-fg-3">
                      Filtered ({filteredResumes.length})
                    </p>
                    {([
                      { format: 'tex', label: 'LaTeX Source (.tex)' },
                      { format: 'pdf', label: 'PDF Files (.pdf)' },
                      { format: 'docx', label: 'Word Docs (.docx)' },
                    ] as const).map(({ format, label }) => (
                      <button
                        key={`filtered-${format}`}
                        onClick={() => handleFilteredExport(format)}
                        disabled={filteredResumes.length === 0}
                        className="w-full px-3 py-2 text-left text-[12px] text-fg-2 transition hover:bg-surface-2 hover:text-fg disabled:opacity-50"
                      >
                        {label}
                      </button>
                    ))}
                    <div className="my-1 border-t border-line" />
                  </>
                )}
                <p className="px-3 pb-1 pt-1.5 text-[10px] font-mono uppercase tracking-[0.12em] text-fg-3">
                  All resumes
                </p>
                {([
                  { format: 'tex', label: 'LaTeX Source (.zip)' },
                  { format: 'pdf', label: 'PDF Files (.zip)' },
                  { format: 'docx', label: 'Word Docs (.zip)' },
                ] as const).map(({ format, label }) => (
                  <button
                    key={`all-${format}`}
                    onClick={() => handleBulkExport(format)}
                    className="w-full px-3 py-2 text-left text-[12px] text-fg-2 transition hover:bg-surface-2 hover:text-fg"
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <Link
            href="/workspace/merge"
            aria-label="Merge resumes"
            title="Merge resumes"
            className="rounded-[var(--radius-md)] border border-line-2 text-fg hover:bg-surface-2 flex items-center gap-1.5 px-4 py-2 text-xs"
          >
            <GitMerge size={12} aria-hidden="true" />
            <span className="hidden sm:inline">Merge</span>
          </Link>

          <Link href="/workspace/new" className="rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg hover:brightness-110 px-4 py-2 text-xs">
            New Resume
          </Link>
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Filter by title…"
            aria-label="Filter resumes by title"
            title="Filters the list below by title only — for full-text search across resume content, use Search content (⌘⇧F) above"
            className="w-full max-w-md rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
          />

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-fg-2">
              <ArrowUpDown size={12} className="text-fg-3" />
              <span className="font-mono uppercase tracking-[0.12em] text-fg-3">Sort</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                aria-label="Sort resumes"
                className="bg-transparent text-xs text-fg outline-none"
              >
                <option value="updated">Recently updated</option>
                <option value="name">Name A–Z</option>
                <option value="freshness">Freshness</option>
                <option value="match">Match score</option>
              </select>
            </label>

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
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section>
          {isLoading ? (
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-72 items-center justify-center">
              <LoadingSpinner />
            </div>
          ) : filteredResumes.length === 0 ? (
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface px-6 py-16 text-center">
              <h2 className="text-lg font-semibold text-fg">No resumes found</h2>
              <p className="mt-2 text-sm text-fg-2">
                {searchQuery ? `No results for "${searchQuery}".` : 'Create your first resume to start your pipeline.'}
              </p>
              {!searchQuery && (
                <Link href="/workspace/new" className="rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg hover:brightness-110 mt-5 px-4 py-2 text-xs">
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
                      <div className="ml-6 mt-2 space-y-3 border-l-2 border-accent/20 pl-4">
                        {variantMap[resume.id].map((variant) => renderResumeCard(variant, true, resume.title))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-[0.14em] text-fg-3">
                    <th className="px-4 py-3 font-semibold">Title</th>
                    {matchResults.length > 0 && <th className="px-4 py-3 font-semibold text-right">Match</th>}
                    <th className="px-4 py-3 font-semibold text-right">Updated</th>
                    <th className="px-4 py-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {masterResumes.map((resume) => (
                    <Fragment key={resume.id}>
                      <tr>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {getVariantCount(resume) > 0 && (
                              <button
                                onClick={() => toggleExpand(resume.id)}
                                className="flex items-center gap-1 text-accent-strong transition hover:brightness-110"
                              >
                                {expandedParents.has(resume.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                              </button>
                            )}
                            <Link href={`/workspace/${resume.id}/edit`} className="text-sm font-medium text-fg transition hover:text-accent-strong">
                              {resume.title}
                            </Link>
                            {getVariantCount(resume) > 0 && (
                              <span className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold text-accent-strong">
                                <GitFork size={9} />{getVariantCount(resume)}
                              </span>
                            )}
                          </div>
                        </td>
                        {matchResults.length > 0 && (
                          <td className="px-4 py-3 text-right">
                            {matchMap[resume.id] && matchMap[resume.id].similarity_score != null ? (
                              <span className={`rounded-[var(--radius-md)] px-2 py-0.5 text-[10px] font-bold tabular-nums ring-1 ${
                                (matchMap[resume.id].similarity_score as number) >= 0.8
                                  ? 'bg-ok/10 text-ok ring-ok/20'
                                  : (matchMap[resume.id].similarity_score as number) >= 0.6
                                  ? 'bg-warn/10 text-warn ring-warn/20'
                                  : 'bg-err/10 text-err ring-err/20'
                              }`}>
                                {Math.round((matchMap[resume.id].similarity_score as number) * 100)}%
                              </span>
                            ) : (
                              <span className="text-fg-3">—</span>
                            )}
                          </td>
                        )}
                        <td className={`px-4 py-3 text-right text-sm ${
                          resume.freshness_status === 'very_stale' ? 'text-err' :
                          resume.freshness_status === 'stale' ? 'text-warn' : 'text-fg-2'
                        }`} title={new Date(resume.updated_at).toLocaleString()}>
                          {resume.days_since_updated != null && resume.days_since_updated > 0
                            ? `${resume.days_since_updated}d ago`
                            : 'Today'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex gap-2 items-center">
                            <Link
                              href={`/workspace/${resume.id}/edit`}
                              className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:border-line-2 hover:text-fg"
                            >
                              Edit
                            </Link>
                            <Link
                              href={`/workspace/${resume.id}/optimize`}
                              className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-1.5 text-xs font-semibold text-accent-strong transition hover:brightness-110"
                            >
                              Optimize
                            </Link>
                            {renderActionMenu(resume, false)}
                          </div>
                        </td>
                      </tr>
                      {expandedParents.has(resume.id) && variantMap[resume.id]?.map((variant) => (
                        <tr key={variant.id} className="bg-surface-2">
                          <td className="py-3 pl-12 pr-4">
                            <div className="flex items-center gap-2">
                              <GitFork size={11} className="text-accent/50" />
                              <Link href={`/workspace/${variant.id}/edit`} className="text-sm font-medium text-fg-2 transition hover:text-accent-strong">
                                {variant.title}
                              </Link>
                              <span className="text-[10px] text-fg-3">variant</span>
                            </div>
                          </td>
                          {matchResults.length > 0 && (
                            <td className="px-4 py-3 text-right">
                              <span className="text-fg-3">—</span>
                            </td>
                          )}
                          <td className={`px-4 py-3 text-right text-sm ${
                            variant.freshness_status === 'very_stale' ? 'text-err' :
                            variant.freshness_status === 'stale' ? 'text-warn' : 'text-fg-3'
                          }`} title={new Date(variant.updated_at).toLocaleString()}>
                            {variant.days_since_updated != null && variant.days_since_updated > 0
                              ? `${variant.days_since_updated}d ago`
                              : 'Today'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="inline-flex gap-2 items-center">
                              <Link
                                href={`/workspace/${variant.id}/edit`}
                                className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 transition hover:border-line-2 hover:text-fg"
                              >
                                Edit
                              </Link>
                              <Link
                                href={`/workspace/${variant.id}/optimize`}
                                className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-1.5 text-xs font-semibold text-accent-strong transition hover:brightness-110"
                              >
                                Optimize
                              </Link>
                              {renderActionMenu(variant, true)}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Archived resumes section (Feature 39) */}
          {showArchived && (
            <div className="mt-6">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.12em] text-fg-3">
                <Archive size={12} />
                Archived
              </h2>
              {archivedLoading ? (
                <div className="flex items-center justify-center py-8"><LoadingSpinner /></div>
              ) : archivedResumes.length === 0 ? (
                <p className="rounded-[var(--radius-lg)] border border-line bg-surface-2 px-4 py-6 text-center text-sm text-fg-3">
                  No archived resumes.
                </p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {archivedResumes.map(r => (
                    <div key={r.id} className="rounded-[var(--radius-lg)] border border-line bg-surface flex items-center justify-between gap-3 p-4 opacity-60">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-fg-2">{r.title}</p>
                        <p className="text-[11px] text-fg-3">Archived</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <button
                          onClick={() => handleUnarchive(r.id)}
                          title="Restore"
                          className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[10px] font-medium text-fg-3 ring-1 ring-line transition hover:bg-ok/10 hover:text-ok"
                        >
                          <ArchiveRestore size={11} />
                          Restore
                        </button>
                        <button
                          onClick={() => { if (confirm(`Permanently delete "${r.title}"? This cannot be undone.`)) handleDeletePermanently(r.id) }}
                          title="Delete permanently"
                          aria-label={`Delete "${r.title}" permanently`}
                          className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[10px] font-medium text-fg-3 ring-1 ring-line transition hover:bg-err/10 hover:text-err"
                        >
                          <Trash2 size={11} />
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* My Templates section (Feature 39E) */}
          {templateResumes.length > 0 && !activeTagFilter && (
            <div className="mt-6">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.12em] text-fg-3">
                <LayoutTemplate size={12} />
                My Templates
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {templateResumes.map(r => (
                  <article key={r.id} className="rounded-[var(--radius-lg)] border border-line bg-surface flex flex-col gap-2 p-4">
                    <div className="flex items-center gap-2">
                      <LayoutTemplate size={11} className="text-fg-3" />
                      <p className="truncate text-sm font-medium text-fg-2">{r.title}</p>
                    </div>
                    <div className="flex gap-2">
                      <a href={`/workspace/${r.id}/edit`} className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-1.5 text-center text-[11px] font-semibold text-fg-2 transition hover:brightness-110 hover:text-fg">
                        Edit
                      </a>
                      <button
                        onClick={async () => {
                          try {
                            const updated = await apiClient.updateResume(r.id, { is_template: false })
                            setResumes(prev => prev.map(x => x.id === r.id ? { ...x, ...updated } : x))
                            toast.success('Removed from templates')
                          } catch { toast.error('Failed') }
                        }}
                        className="rounded-[var(--radius-md)] border border-line px-2 py-1.5 text-[11px] text-fg-3 transition hover:text-err"
                        title="Remove from templates"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          {/* Tag Filter + Archive (Feature 39) */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2 flex items-center gap-2">
              <Tag size={12} />
              Organize
            </h2>
            {allTags.length > 0 ? (
              <div className="mt-3 space-y-1">
                <p className="text-[10px] uppercase tracking-wide text-fg-3 mb-2">Filter by tag</p>
                <button
                  onClick={() => setActiveTagFilter(null)}
                  className={`w-full rounded-[var(--radius-md)] px-3 py-1.5 text-left text-xs transition ${
                    !activeTagFilter ? 'bg-surface-2 text-fg' : 'text-fg-3 hover:bg-surface-2 hover:text-fg-2'
                  }`}
                >
                  All resumes
                </button>
                {allTags.map(tag => (
                  <button
                    key={tag}
                    onClick={() => setActiveTagFilter(activeTagFilter === tag ? null : tag)}
                    className={`flex w-full items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-left text-xs transition ${
                      activeTagFilter === tag
                        ? 'bg-accent-soft text-accent-strong'
                        : 'text-fg-3 hover:bg-surface-2 hover:text-fg-2'
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-accent/60" />
                    {tag}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-fg-3">Add tags to resumes to filter here.</p>
            )}
            <div className="mt-4 border-t border-line pt-3">
              <button
                onClick={() => {
                  setShowArchived(v => {
                    if (!v) loadArchivedResumes()
                    return !v
                  })
                }}
                className="flex w-full items-center gap-2 rounded-[var(--radius-md)] px-2 py-1.5 text-xs text-fg-3 transition hover:bg-err/10 hover:text-err"
              >
                <Archive size={11} />
                {showArchived ? 'Hide Archived' : 'View Archived'}
              </button>
            </div>
          </section>

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2">Recent Activity</h2>
            {jobs.length === 0 ? (
              <p className="mt-3 text-sm text-fg-3">No recent runs yet.</p>
            ) : (
              <div className="mt-4 space-y-3">
                {jobs.slice(0, 5).map((job, index) => {
                  const jobId = job.job_id
                  const expanded = !!jobId && expandedJobId === jobId
                  const result = jobId ? jobResultCache[jobId] : undefined
                  return (
                    <div key={jobId ?? `${job.last_updated}-${index}`} className="overflow-hidden rounded-[var(--radius-md)] border border-line bg-bg">
                      <button
                        type="button"
                        onClick={() => jobId && handleToggleJobDetail(jobId)}
                        disabled={!jobId}
                        aria-expanded={expanded}
                        className="flex w-full items-start justify-between gap-2 p-3 text-left transition enabled:hover:bg-surface-2 disabled:cursor-default"
                      >
                        <div className="min-w-0">
                          <p className="text-xs uppercase tracking-[0.12em] text-fg-3">{job.stage || 'Pipeline'}</p>
                          <p className="mt-1 text-sm capitalize text-fg">{job.status}</p>
                          <p className="mt-1 text-xs text-fg-3">{new Date(job.last_updated * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
                        </div>
                        {jobId && <ChevronDown size={14} className={`mt-0.5 shrink-0 text-fg-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />}
                      </button>
                      {expanded && jobId && (
                        <div className="border-t border-line px-3 py-2.5 text-xs">
                          {jobResultLoading === jobId ? (
                            <p className="text-fg-3">Loading result…</p>
                          ) : result == null ? (
                            <p className="text-fg-3">No detailed result is available for this run.</p>
                          ) : (
                            <div className="space-y-1.5">
                              {result.error && <p className="text-err">{result.error}</p>}
                              {result.ats_score != null && (
                                <p className="text-fg-2">ATS score: <span className="font-semibold text-fg">{Math.round(result.ats_score)}</span></p>
                              )}
                              {result.compilation_time != null && (
                                <p className="text-fg-3">Compiled in {result.compilation_time.toFixed(1)}s</p>
                              )}
                              {(result.pdf_job_id || jobId) && (
                                <a
                                  href={apiClient.getPdfUrl(result.pdf_job_id ?? jobId)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-accent-strong transition hover:brightness-110"
                                >
                                  <Download size={12} /> Download PDF
                                </a>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {jobs.length > 0 && (
              <Link href="/workspace/history" className="mt-4 inline-block text-xs font-semibold uppercase tracking-[0.12em] text-accent-strong transition hover:brightness-110">
                View Full History
              </Link>
            )}
          </section>

          {atsStats && atsStats.optimized_count > 0 && (
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <div className="flex items-center gap-2 mb-3">
                <BarChart2 size={13} className="text-accent-strong/70" />
                <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2">ATS Scores</h3>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-lg font-bold tabular-nums text-accent-strong">
                    {atsStats.avg_ats_score != null ? Math.round(atsStats.avg_ats_score) : '—'}
                  </p>
                  <p className="text-[10px] text-fg-3 mt-0.5">Avg</p>
                </div>
                <div>
                  <p className="text-lg font-bold tabular-nums text-ok">
                    {atsStats.best_ats_score != null ? Math.round(atsStats.best_ats_score) : '—'}
                  </p>
                  <p className="text-[10px] text-fg-3 mt-0.5">Best</p>
                </div>
                <div>
                  <p className="text-lg font-bold tabular-nums text-fg">
                    {atsStats.optimized_count}
                  </p>
                  <p className="text-[10px] text-fg-3 mt-0.5">Optimized</p>
                </div>
              </div>
            </section>
          )}

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2">Workflow Tip</h3>
            <p className="mt-2 text-sm text-fg-2">
              Use <strong className="text-fg">Fork</strong> to create role-specific variants of a resume. Edit each variant independently, then compare with the parent to review changes.
            </p>
          </section>
        </aside>
      </div>

      {/* Fork modal */}
      {forkModalResumeId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--overlay)]" onClick={() => setForkModalResumeId(null)}>
          <div className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-fg">Create Variant</h3>
              <button onClick={() => setForkModalResumeId(null)} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2">
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-fg-3 mb-4">This creates a linked copy you can customize for a specific role.</p>
            <input
              type="text"
              value={forkTitle}
              onChange={e => setForkTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !isForking) handleFork(forkModalResumeId, forkTitle); if (e.key === 'Escape') setForkModalResumeId(null) }}
              placeholder="Variant title"
              autoFocus
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setForkModalResumeId(null)}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                onClick={() => handleFork(forkModalResumeId, forkTitle)}
                disabled={isForking}
                className="rounded-[var(--radius-md)] bg-accent font-semibold text-accent-fg hover:brightness-110 px-4 py-2 text-xs disabled:opacity-50"
              >
                {isForking ? 'Creating...' : 'Create Variant'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Translate modal */}
      {translateModalResumeId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--overlay)]" onClick={() => setTranslateModalResumeId(null)}>
          <div className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)]" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Globe size={16} className="text-accent-strong" />
                <h3 className="text-base font-semibold text-fg">Translate Resume</h3>
              </div>
              <button onClick={() => setTranslateModalResumeId(null)} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2">
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-fg-3 mb-4">Creates a new variant with prose translated by AI. LaTeX commands are preserved exactly.</p>
            <label className="block text-xs font-medium text-fg-2 mb-1.5">Target Language</label>
            <select
              value={translateSelectedLang}
              onChange={e => setTranslateSelectedLang(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent mb-5"
            >
              {TRANSLATE_LANGUAGES.map(l => (
                <option key={l.code} value={l.code}>{l.name}</option>
              ))}
            </select>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setTranslateModalResumeId(null)}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                onClick={() => handleTranslate(translateModalResumeId, translateSelectedLang)}
                disabled={isTranslating}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-xs font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-50"
              >
                {isTranslating ? <><Loader2 size={12} className="animate-spin" /> Translating…</> : <><Globe size={12} /> Translate</>}
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

      {/* Quick Apply modal (Feature 87) */}
      {applyModalResume && (
        <ApplyModal
          resumeId={applyModalResume.id}
          resumeTitle={applyModalResume.title}
          onClose={() => setApplyModalResume(null)}
        />
      )}

      <OnboardingFlow
        isOpen={isOnboardingOpen}
        onComplete={completeOnboarding}
        onSkip={skipOnboarding}
        userType="new"
      />

      {/* Tag Edit modal (Feature 39) */}
      {tagEditResumeId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--overlay)]" onClick={() => setTagEditResumeId(null)}>
          <div className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)]" onClick={e => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-base font-semibold text-fg">
                <Tag size={14} className="text-accent-strong" />
                Edit Tags
              </h3>
              <button onClick={() => setTagEditResumeId(null)} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2">
                <X size={16} />
              </button>
            </div>
            <p className="mb-3 text-xs text-fg-3">Enter tags separated by commas (max 10, each ≤30 chars)</p>
            <input
              type="text"
              value={tagEditValue}
              onChange={e => setTagEditValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSaveTags(); if (e.key === 'Escape') setTagEditResumeId(null) }}
              placeholder="e.g. frontend, senior, remote"
              autoFocus
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setTagEditResumeId(null)} className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg">
                Cancel
              </button>
              <button onClick={handleSaveTags} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110">
                Save Tags
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Archive confirmation modal — themed replacement for window.confirm() */}
      {archiveConfirmResume && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[color:var(--overlay)]"
          onClick={() => { if (!isArchiving) setArchiveConfirmResume(null) }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="archive-confirm-title"
            className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)]"
            onClick={e => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 id="archive-confirm-title" className="flex items-center gap-2 text-base font-semibold text-fg">
                <Archive size={14} className="text-err" />
                Archive resume
              </h3>
              <button
                onClick={() => { if (!isArchiving) setArchiveConfirmResume(null) }}
                className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
              >
                <X size={16} />
              </button>
            </div>
            <p className="mb-5 text-sm text-fg-2">
              Archive &ldquo;<strong className="text-fg">{archiveConfirmResume.title}</strong>&rdquo;? It will be hidden from the workspace, but you can restore it later from the archived list.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setArchiveConfirmResume(null)}
                disabled={isArchiving}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleArchive(archiveConfirmResume.id)}
                disabled={isArchiving}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-err/15 px-4 py-2 text-xs font-semibold text-err ring-1 ring-err/30 transition hover:bg-err/25 disabled:opacity-50"
              >
                {isArchiving ? <Loader2 size={12} className="animate-spin" /> : <Archive size={12} />}
                {isArchiving ? 'Archiving…' : 'Archive'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
