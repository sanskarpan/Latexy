'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from '@/lib/auth-client'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { GitFork, History, Link2, Loader2, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type AcademicCVReport, type CheckpointEntry, type DiffWithParentResponse, type ExplainErrorResponse, type LatexCompiler, type ScrapeJobResponse } from '@/lib/api-client'
import CompilerSelector from '@/components/CompilerSelector'
import VersionHistoryPanel from '@/components/VersionHistoryPanel'
import { useJobStream } from '@/hooks/useJobStream'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { useQuickATSScore } from '@/hooks/useQuickATSScore'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import ModeToggle from '@/components/theme/ModeToggle'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import ATSScoreCard from '@/components/ATSScoreCard'
import DiffViewerModal from '@/components/DiffViewerModal'
import CompareModal from '@/components/CompareModal'
import ChangeReviewModal from '@/components/ChangeReviewModal'
import LoadingSpinner from '@/components/LoadingSpinner'
import ErrorExplainerPanel from '@/components/ErrorExplainerPanel'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import AtsSimulatorPanel from '@/components/ats/AtsSimulatorPanel'
import KeywordDensityMap from '@/components/KeywordDensityMap'
import PublicationsPanel from '@/components/PublicationsPanel'
import GuidedIntakePanel from '@/components/GuidedIntakePanel'
import { EMPTY_INTAKE, intakeIsEmpty, type GuidedIntake } from '@/lib/guided-intake'

const TRIM_INSTRUCTION =
  'Condense this resume to fit on exactly ONE page. Prioritize recent and most impactful content. Remove less critical details, condense bullet points, reduce descriptions. Do NOT remove any job titles, companies, degrees, or institution names.'

const PERSONA_OPTIONS = [
  { key: 'startup', icon: '🚀', label: 'Startup / Scale-up', description: 'Lean, impact-driven language — metrics, growth, and ownership.' },
  { key: 'enterprise', icon: '🏢', label: 'Enterprise / Corporate', description: 'Formal, structured — collaboration, process, and scale.' },
  { key: 'academic', icon: '🎓', label: 'Academic / Research', description: 'Publications, grants, teaching, and scholarly contributions.' },
  { key: 'career_change', icon: '🔄', label: 'Career Change / Pivot', description: 'Surfaces transferable skills and bridges to the new field.' },
  { key: 'executive', icon: '💼', label: 'Executive / C-Suite', description: 'P&L, vision, and board-level leadership impact.' },
] as const

export default function OptimizationSuitePage() {
  const params = useParams()
  const router = useRouter()
  const resumeId = params.resumeId as string

  const [resume, setResume] = useState<{ title: string; latex_content: string } | null>(null)
  // Live editor content — kept in sync with the editor (manual edits + optimize
  // stream) so the quick ATS badge tracks the current document, not the loaded one.
  const [editorContent, setEditorContent] = useState('')
  const [isSavingVersion, setIsSavingVersion] = useState(false)
  const [jobDescription, setJobDescription] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [activeJobKind, setActiveJobKind] = useState<'compile' | 'optimize'>('compile')
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [baselineLatex, setBaselineLatex] = useState('')
  const [compareOriginalLatex, setCompareOriginalLatex] = useState<string | null>(null)
  const [compareAfterLatex, setCompareAfterLatex] = useState<string | null>(null)
  const [showCompareModal, setShowCompareModal] = useState(false)
  const [showReviewModal, setShowReviewModal] = useState(false)

  // Academic-CV awareness — a genuine CV legitimately runs past one page, so the
  // page-overflow warning is suppressed for it (see the banner below).
  const [academicReport, setAcademicReport] = useState<AcademicCVReport | null>(null)

  // Variant awareness
  const [parentResumeId, setParentResumeId] = useState<string | null>(null)
  const [parentTitle, setParentTitle] = useState<string | null>(null)
  const [parentDiffData, setParentDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showParentDiff, setShowParentDiff] = useState(false)
  const [forkPopoverOpen, setForkPopoverOpen] = useState(false)
  const [forkTitleInput, setForkTitleInput] = useState('')
  const [isForkingResume, setIsForkingResume] = useState(false)

  // Compiler selection
  const [compiler, setCompiler] = useState<LatexCompiler>('pdflatex')

  // Version history / checkpoint diff
  const [showHistory, setShowHistory] = useState(false)
  const [diffCheckpointA, setDiffCheckpointA] = useState<CheckpointEntry | null>(null)
  const [diffCheckpointB, setDiffCheckpointB] = useState<CheckpointEntry | null>(null)
  const [showHistoryDiff, setShowHistoryDiff] = useState(false)
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0)

  // URL scraper
  const [jobUrl, setJobUrl] = useState('')
  const [isScraping, setIsScraping] = useState(false)
  const [scrapedMeta, setScrapedMeta] = useState<ScrapeJobResponse | null>(null)

  // Optimization persona (Feature 56)
  const [persona, setPersona] = useState<string | null>(null)

  // Guided intake — user direction for the rewrite (input-driven optimization P1)
  const [intake, setIntake] = useState<GuidedIntake>(EMPTY_INTAKE)

  // Industry override for ATS calibration (Feature 46)
  const [industryOverride, setIndustryOverride] = useState<string | null>(null)
  // Re-scored result for the selected industry override — score/recommendations
  // must reflect the chosen calibration, not just the display label.
  const [industryOverrideResult, setIndustryOverrideResult] = useState<{
    ats_score?: number
    category_scores?: Record<string, number>
    recommendations?: string[]
    warnings?: string[]
    strengths?: string[]
    industry_key?: string
    industry_label?: string
  } | null>(null)
  const [isRescoringIndustry, setIsRescoringIndustry] = useState(false)

  // ATS tools tab
  const [activeToolTab, setActiveToolTab] = useState<'ATS Simulator' | 'Keywords' | 'Publications'>('ATS Simulator')

  // Error explainer
  const [explainerOpen, setExplainerOpen] = useState(false)
  const [explainerLoading, setExplainerLoading] = useState(false)
  const [explainerData, setExplainerData] = useState<ExplainErrorResponse | null>(null)
  const [explainerLine, setExplainerLine] = useState<number | null>(null)

  const { data: session, isPending: sessionLoading } = useSession()

  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()
  const { score: quickATSScore, loading: quickATSLoading, refetch: refetchATS } = useQuickATSScore(editorContent || resume?.latex_content || '', jobDescription)
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)
  const { requestPermission, notify } = usePushNotifications()

  useEffect(() => {
    if (!session || sessionLoading) return

    const fetchResume = async () => {
      try {
        const data = await apiClient.getResume(resumeId)
        setResume(data)
        setBaselineLatex(data.latex_content)
        setEditorContent(data.latex_content)
        editorRef.current?.setValue(data.latex_content)
        setParentResumeId(data.parent_resume_id ?? null)

        // Academic-CV detection (best-effort) — gates the page-overflow warning.
        apiClient.getAcademicCVReport(resumeId).then(setAcademicReport).catch(() => {})

        if (data.parent_resume_id) {
          apiClient.getResume(data.parent_resume_id).then(p => setParentTitle(p.title)).catch(() => {
            setParentResumeId(null)
          })
        }

        // Load compiler preference
        const loadedCompiler = data.metadata?.compiler as LatexCompiler | undefined
        const resolvedCompiler: LatexCompiler = loadedCompiler && ['pdflatex', 'xelatex', 'lualatex'].includes(loadedCompiler) ? loadedCompiler : 'pdflatex'
        setCompiler(resolvedCompiler)

        // Load last-used persona (Feature 56)
        const savedPersona = data.metadata?.last_persona as string | undefined
        if (savedPersona) setPersona(savedPersona)

        // Auto-compile on load so user sees PDF immediately
        if (data.latex_content && data.latex_content.length >= 100) {
          try {
            const r = await apiClient.compileLatex({ latex_content: data.latex_content, resume_id: resumeId, compiler: resolvedCompiler })
            if (r.success && r.job_id) { setActiveJobId(r.job_id); setActiveJobKind('compile') }
          } catch {
            // Silent
          }
        }
      } catch {
        toast.error('Failed to load resume')
        router.push('/workspace')
      } finally {
        setIsLoading(false)
      }
    }

    fetchResume()
  }, [resumeId, router, session, sessionLoading])

  // Unsaved-changes guard: manual edits or an un-saved optimize result should not
  // be lost silently on reload or navigation (parity with the edit page).
  const isDirty = editorContent.trim() !== '' && editorContent.trim() !== baselineLatex.trim()
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => { if (isDirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])
  const confirmDiscardIfDirty = useCallback(() => {
    if (!isDirty) return true
    return window.confirm('You have unsaved changes that will be lost. Leave without saving a new version?')
  }, [isDirty])

  useEffect(() => {
    if (!stream.streamingLatex || !editorRef.current) return
    editorRef.current.setValue(stream.streamingLatex, { reveal: false })
    // Keep live content (and thus the ATS badge) in sync with the optimize stream —
    // onChange does not fire for external setValue while the editor is read-only.
    setEditorContent(stream.streamingLatex)
  }, [stream.streamingLatex])

  useEffect(() => {
    const fetchPdf = async () => {
      if (stream.status !== 'completed' || !stream.pdfJobId) return

      try {
        const blob = await apiClient.downloadPdf(stream.pdfJobId)
        const nextUrl = URL.createObjectURL(blob)

        if (pdfUrlRef.current) {
          URL.revokeObjectURL(pdfUrlRef.current)
        }

        pdfUrlRef.current = nextUrl
        setPdfUrl(nextUrl)
      } catch {
        toast.error('Failed to load optimized PDF')
      }
    }

    fetchPdf()

    // Capture immutable after-snapshot for before/after comparison
    if (stream.status === 'completed' && compareOriginalLatex !== null) {
      setCompareAfterLatex(stream.streamingLatex ?? '')
    }

    // Track completion for analytics
    if (stream.status === 'completed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'completed')
      apiClient.trackOptimization(activeJobId, 'openai', 'gpt-4o-mini', stream.tokensUsed ?? undefined)
      apiClient.trackFeatureUsage('optimize')
      refetchATS()
      setHistoryRefreshKey((k) => k + 1)
    } else if (stream.status === 'failed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'failed')
    }
  }, [stream.status, stream.pdfJobId, stream.streamingLatex, activeJobId, stream.tokensUsed, refetchATS, compareOriginalLatex])

  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = null
      }
    }
  }, [])

  // Push notification on optimization complete (Feature 65) — only for optimize jobs
  useEffect(() => {
    if (activeJobKind === 'optimize' && stream.status === 'completed') {
      notify('Optimization complete', 'Your AI-optimized resume is ready to review')
    }
  }, [activeJobKind, stream.status, notify])

  useEffect(() => {
    if (activeJobKind === 'optimize' && stream.status === 'processing') {
      requestPermission()
    }
  }, [activeJobKind, stream.status, requestPermission])

  const runOptimization = async () => {
    const currentContent = editorRef.current?.getValue() || resume?.latex_content || ''
    setCompareOriginalLatex(currentContent)
    setIsSubmitting(true)
    setPdfUrl(null)
    // A fresh optimize pass produces its own ATS analysis — drop any stale
    // industry-override re-score so we don't show mismatched results.
    setIndustryOverrideResult(null)

    try {
      const response = await apiClient.optimizeAndCompile({
        latex_content: currentContent,
        job_description: jobDescription,
        optimization_level: 'balanced',
        compiler,
        persona: persona ?? undefined,
        industry: intake.industry || undefined,
        seniority: intake.seniority || undefined,
        tone: intake.tone || undefined,
        emphasize: intake.emphasize.length ? intake.emphasize : undefined,
        downplay: intake.downplay.length ? intake.downplay : undefined,
      })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to start optimization')
      }

      setActiveJobId(response.job_id)
      setActiveJobKind('optimize')
      toast.success('Optimization pipeline started')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Optimization failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Re-score against the chosen industry profile so the "Change industry…"
  // selector actually affects the displayed score/recommendations, not just
  // the label. Hits the same ats_scoring_service computation (sync path) that
  // powers the async job pipeline, so results stay consistent.
  const handleIndustryOverride = useCallback(async (key: string) => {
    const resolvedKey = key === 'generic' ? null : key
    setIndustryOverride(resolvedKey)
    const currentContent = editorRef.current?.getValue() || resume?.latex_content || ''
    if (!currentContent.trim()) return
    setIsRescoringIndustry(true)
    try {
      const res = await apiClient.scoreATS({
        latex_content: currentContent,
        job_description: jobDescription || undefined,
        industry_override: resolvedKey ?? undefined,
      })
      if (res.success) {
        setIndustryOverrideResult(res)
      } else {
        toast.error(res.message || 'Failed to re-score for this industry')
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to re-score for this industry')
    } finally {
      setIsRescoringIndustry(false)
    }
  }, [resume?.latex_content, jobDescription])

  const restoreOriginal = () => {
    if (!baselineLatex || !editorRef.current) return
    // Guard: restoring overwrites the editor. If the user has diverged from the
    // baseline (manual edits or an accepted optimization), confirm before wiping it.
    const current = editorRef.current.getValue()
    if (current.trim() !== baselineLatex.trim()) {
      const ok = window.confirm(
        'Restore the original resume? This will discard the current editor content, including any edits or applied optimizations.'
      )
      if (!ok) return
    }
    editorRef.current.setValue(baselineLatex)
    setEditorContent(baselineLatex)
    toast.success('Original resume restored in editor')
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      const response = await apiClient.compileLatex({ latex_content: content, resume_id: resumeId, compiler })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      setActiveJobId(response.job_id)
      setActiveJobKind('compile')
    } catch {
      // Silent fail
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting, resumeId, compiler])

  // Apply the user's per-change review result (F2-P0): load the reconstructed
  // LaTeX into the editor, make it the new "after" snapshot, and recompile.
  const handleApplyReviewedChanges = useCallback(async (latex: string) => {
    editorRef.current?.setValue(latex)
    setEditorContent(latex)
    setCompareAfterLatex(latex)
    setIsSubmitting(true)
    setPdfUrl(null)
    try {
      const response = await apiClient.compileLatex({ latex_content: latex, resume_id: resumeId, compiler })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed to recompile')
      setActiveJobId(response.job_id)
      setActiveJobKind('compile')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Recompile failed')
    } finally {
      setIsSubmitting(false)
    }
  }, [resumeId, compiler])

  const handleCompareWithParent = useCallback(async () => {
    try {
      const data = await apiClient.getResumeDiffWithParent(resumeId)
      setParentDiffData(data)
      setShowParentDiff(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load diff')
    }
  }, [resumeId])

  const handleCreateVariant = useCallback(async () => {
    if (isForkingResume) return
    setIsForkingResume(true)
    try {
      const newResume = await apiClient.forkResume(resumeId, forkTitleInput || undefined)
      setForkPopoverOpen(false)
      setForkTitleInput('')
      router.push(`/workspace/${newResume.id}/edit`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create variant')
    } finally {
      setIsForkingResume(false)
    }
  }, [resumeId, forkTitleInput, isForkingResume, router])

  const handleExplainError = useCallback(async (error: { line: number; message: string; surroundingLatex: string }) => {
    setExplainerLine(error.line)
    setExplainerOpen(true)
    setExplainerLoading(true)
    setExplainerData(null)
    try {
      const result = await apiClient.explainLatexError({
        error_message: error.message,
        surrounding_latex: error.surroundingLatex,
        error_line: error.line,
      })
      setExplainerData(result)
    } catch {
      setExplainerData({
        success: false, explanation: 'Failed to analyze error.',
        suggested_fix: 'Check the error message manually.', corrected_code: null,
        source: 'error', cached: false, processing_time: 0,
      })
    } finally {
      setExplainerLoading(false)
    }
  }, [])

  const handleApplyExplainerFix = useCallback(() => {
    if (!explainerData?.corrected_code || explainerLine == null) return
    editorRef.current?.applyFix(explainerLine, explainerData.corrected_code)
    setExplainerOpen(false)
    toast.success('Fix applied')
  }, [explainerData, explainerLine])

  const handleTrimToOnePage = useCallback(async () => {
    const currentContent = editorRef.current?.getValue() || resume?.latex_content || ''
    if (!currentContent.trim()) return
    setIsSubmitting(true)
    setPdfUrl(null)
    try {
      const response = await apiClient.optimizeAndCompile({
        latex_content: currentContent,
        job_description: jobDescription,
        optimization_level: 'aggressive',
        custom_instructions: TRIM_INSTRUCTION,
        industry: intake.industry || undefined,
        seniority: intake.seniority || undefined,
        tone: intake.tone || undefined,
        emphasize: intake.emphasize.length ? intake.emphasize : undefined,
        downplay: intake.downplay.length ? intake.downplay : undefined,
      })
      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to start trim')
      }
      setActiveJobId(response.job_id)
      setActiveJobKind('optimize')
      toast.success('Trimming to 1 page…')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Trim failed')
    } finally {
      setIsSubmitting(false)
    }
  }, [resume?.latex_content, jobDescription, intake])

  const handleHistoryRestore = useCallback((latex: string) => {
    editorRef.current?.setValue(latex)
    setEditorContent(latex)
    setShowHistoryDiff(false)
    // Toast is fired by the caller (VersionHistoryPanel or DiffViewerModal)
  }, [])

  const handleHistoryCompare = useCallback((a: CheckpointEntry, b: CheckpointEntry) => {
    setDiffCheckpointA(a)
    setDiffCheckpointB(b)
    setShowHistoryDiff(true)
  }, [])

  const handleScrapeUrl = useCallback(async () => {
    if (!jobUrl.trim() || isScraping) return
    setIsScraping(true)
    setScrapedMeta(null)
    try {
      const result = await apiClient.scrapeJobDescription(jobUrl.trim())
      if (result.error && !result.description) {
        toast.error("Couldn't scrape this URL — paste the job description manually")
        return
      }
      if (result.description) setJobDescription(result.description)
      setScrapedMeta(result)
      const label = [result.title, result.company].filter(Boolean).join(' · ') || 'job posting'
      toast.success(`Imported: ${label}`)
    } catch {
      toast.error("Couldn't scrape this URL — paste the job description manually")
    } finally {
      setIsScraping(false)
    }
  }, [jobUrl, isScraping])

  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="content-shell min-h-screen space-y-6 pb-12">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Optimization</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Targeted Optimization</h1>
          <p className="mt-1 text-sm text-fg-2">Optimize "{resume?.title}" — add a job description to tailor it to a specific role, or leave blank for general improvements.</p>
        </div>
        <div className="flex flex-wrap gap-2 sm:flex-nowrap sm:shrink-0">
          <div className="relative">
            <button
              onClick={() => { setForkPopoverOpen(v => !v); setForkTitleInput(`${resume?.title ?? ''} — Variant`) }}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
            >
              <GitFork size={12} />
              Variant
            </button>
            {forkPopoverOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-[var(--radius-md)] border border-line bg-bg p-3 shadow-[var(--shadow-2)]">
                <input
                  type="text"
                  value={forkTitleInput}
                  onChange={e => setForkTitleInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCreateVariant(); if (e.key === 'Escape') setForkPopoverOpen(false) }}
                  placeholder="Variant title"
                  autoFocus
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg outline-none focus:border-accent mb-2"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setForkPopoverOpen(false)} className="px-2 py-1 text-[10px] text-fg-3 hover:text-fg-2">Cancel</button>
                  <button onClick={handleCreateVariant} disabled={isForkingResume} className="rounded-[var(--radius-md)] bg-accent-soft px-3 py-1 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/20 hover:brightness-110 disabled:opacity-50">
                    {isForkingResume ? 'Creating...' : 'Create'}
                  </button>
                </div>
              </div>
            )}
          </div>
          <ModeToggle />
          <Link href={`/workspace/${resumeId}/edit`} onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }} className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
            Back to Editor
          </Link>
          <Link
            href={`/workspace/${resumeId}/cover-letter`}
            onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }}
            className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-semibold text-fg transition hover:bg-surface-2"
          >
            Cover Letter
          </Link>
          <span className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-accent-strong">
            Pro Pipeline
          </span>
        </div>
      </header>

      {/* Variant banner */}
      {parentResumeId && parentTitle && (
        <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-accent bg-accent-soft px-4 py-2">
          <span className="text-xs text-fg-2">
            Variant of: <span className="font-medium text-fg-2">{parentTitle}</span>
          </span>
          <button
            onClick={handleCompareWithParent}
            className="text-xs font-semibold text-accent-strong transition hover:brightness-110"
          >
            Compare with Parent
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-6">
          {/* ── Persona selector (Feature 56) ── */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Optimization Style</h2>
              <span className="text-[10px] text-fg-3">optional</span>
            </div>
            <p className="mt-1 text-[11px] text-fg-3">Choose a persona to bias the AI toward a specific context.</p>
            <div className="mt-3 grid grid-cols-1 gap-1.5">
              {PERSONA_OPTIONS.map((p) => {
                const active = persona === p.key
                return (
                  <button
                    key={p.key}
                    onClick={() => {
                      const next = active ? null : p.key
                      setPersona(next)
                      apiClient.updateResumeSettings(resumeId, { last_persona: next ?? '' }).catch(() => {})
                    }}
                    disabled={isProcessing}
                    className={`flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2 text-left transition disabled:opacity-50 ${
                      active
                        ? 'border-accent bg-accent-soft'
                        : 'border-line bg-surface-2 hover:bg-surface-2'
                    }`}
                  >
                    <span className="mt-0.5 text-base leading-none">{p.icon}</span>
                    <div className="min-w-0">
                      <p className={`text-[11px] font-semibold ${active ? 'text-accent-strong' : 'text-fg-2'}`}>{p.label}</p>
                      <p className="mt-0.5 text-[10px] leading-relaxed text-fg-3">{p.description}</p>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Job Description</h2>
              <span className="text-[10px] text-fg-3">optional</span>
            </div>
            <div className="mt-3 flex gap-2">
              <input
                type="url"
                value={jobUrl}
                onChange={(e) => { setJobUrl(e.target.value); setScrapedMeta(null) }}
                onKeyDown={(e) => { if (e.key === 'Enter') handleScrapeUrl() }}
                placeholder="Paste job URL (Greenhouse, Lever, Workday, Indeed…)"
                disabled={isProcessing || isScraping}
                className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-1.5 text-xs text-fg outline-none transition placeholder:text-fg-3 focus:border-accent disabled:opacity-50"
              />
              <button
                onClick={handleScrapeUrl}
                disabled={!jobUrl.trim() || isProcessing || isScraping}
                title="Import job description from URL"
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg-2 transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isScraping ? <Loader2 size={11} className="animate-spin" /> : <Link2 size={11} />}
                {isScraping ? 'Importing…' : 'Import'}
              </button>
            </div>
            {scrapedMeta && !scrapedMeta.error && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {scrapedMeta.title && (
                  <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-medium text-accent-strong">
                    {scrapedMeta.title}
                  </span>
                )}
                {scrapedMeta.company && (
                  <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-2">
                    {scrapedMeta.company}
                  </span>
                )}
                {scrapedMeta.location && (
                  <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-3">
                    📍 {scrapedMeta.location}
                  </span>
                )}
                {scrapedMeta.job_type && (
                  <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-3">
                    {scrapedMeta.job_type}
                  </span>
                )}
                {scrapedMeta.salary && (
                  <span className="rounded bg-ok/10 px-1.5 py-0.5 text-[10px] text-ok">
                    {scrapedMeta.salary}
                  </span>
                )}
                <span className="ml-auto text-[9px] text-fg-3">
                  via {scrapedMeta.source}
                </span>
              </div>
            )}
            <textarea
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder="Paste a job description to tailor the optimization to a specific role. Leave blank for general improvements."
              disabled={isProcessing}
              className="scrollbar-subtle mt-2 h-56 w-full resize-none rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4 text-sm text-fg outline-none transition focus:border-accent"
            />
            <div className="mt-3">
              <GuidedIntakePanel value={intake} onChange={setIntake} />
            </div>
            <button
              onClick={runOptimization}
              disabled={isProcessing || isSubmitting}
              className="rounded-[var(--radius-md)] bg-accent px-4 text-accent-fg hover:brightness-110 mt-4 w-full py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isProcessing || isSubmitting ? 'Processing...' : jobDescription.trim() ? 'Optimize for this Role' : 'Optimize Resume'}
            </button>
            {!intakeIsEmpty(intake) && (
              <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
                The AI will follow your direction —
                {[
                  intake.industry && ` ${intake.industry} industry`,
                  intake.seniority && ` ${intake.seniority} level`,
                  intake.tone && ` ${intake.tone.toLowerCase()} tone`,
                  intake.emphasize.length ? ` emphasizing ${intake.emphasize.join(', ')}` : '',
                  intake.downplay.length ? ` downplaying ${intake.downplay.join(', ')}` : '',
                ].filter(Boolean).join(' ·')}
                .
              </p>
            )}
          </section>

          <AnimatePresence>
            {activeJobId && (
              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
              >
                <div className="mb-4 flex items-start justify-between gap-3">
                  <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Pipeline Status</h2>
                  <span className="text-[10px] font-mono text-fg-3">{activeJobId.slice(0, 8)}</span>
                </div>
                <div className="h-2 rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${stream.percent}%` }} />
                </div>
                <p className="mt-3 text-sm capitalize text-fg">{stream.stage || 'Initializing'}</p>
                <p className="mt-1 text-xs text-fg-3">{stream.message || 'Connecting to workers...'}</p>
              </motion.section>
            )}
          </AnimatePresence>

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Live Logs</h2>
            <div className="mt-4 h-56 overflow-hidden rounded-[var(--radius-md)] bg-[var(--overlay)]">
              <LogViewer lines={stream.logLines} maxHeight="100%" className="h-full text-[10px]" />
            </div>
          </section>

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden">
            <button
              onClick={() => setShowHistory((v) => !v)}
              className="flex w-full items-center justify-between px-5 py-3.5 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2 transition hover:text-fg"
            >
              <span className="flex items-center gap-2">
                <History size={13} />
                Version History
              </span>
              <span className="text-[10px] font-normal normal-case tracking-normal text-fg-3">
                {showHistory ? 'Hide' : 'Show'}
              </span>
            </button>
            {showHistory && (
              <div className="max-h-80 overflow-y-auto border-t border-line">
                <VersionHistoryPanel
                  resumeId={resumeId}
                  onRestore={handleHistoryRestore}
                  onCompare={handleHistoryCompare}
                  refreshKey={historyRefreshKey}
                />
              </div>
            )}
          </section>
        </aside>

        <main className="min-w-0 space-y-6">
          <div className="grid gap-6 xl:grid-cols-2">
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-[620px] min-w-0 flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between gap-2 border-b border-line bg-surface-2 px-4">
                <div className="flex min-w-0 items-center gap-3 overflow-x-auto">
                  <p className="shrink-0 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">LaTeX Source</p>
                  <button
                    onClick={toggleAutoCompile}
                    title="Auto-compile on change (2s debounce)"
                    className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium transition ${
                      autoCompile
                        ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
                        : 'text-fg-3 hover:text-fg-2'
                    }`}
                  >
                    <Zap size={10} />
                    Auto
                  </button>
                  <span className="h-4 w-px bg-line" />
                  <CompilerSelector
                    resumeId={resumeId}
                    current={compiler}
                    onChange={setCompiler}
                    disabled={isProcessing || isSubmitting}
                  />
                </div>
                <button onClick={restoreOriginal} className="shrink-0 text-xs font-semibold text-fg-2 transition hover:text-fg">
                  Restore Original
                </button>
              </div>
              {/* Academic CVs legitimately run long — don't nag them about page count. */}
              {stream.pageCount !== null && stream.pageCount > 1 && !academicReport?.is_academic_cv && (
                <div className="flex shrink-0 items-center justify-between border-b border-warn/20 bg-warn/10 px-4 py-1.5">
                  <span className="text-[11px] text-warn">
                    ⚠ Your resume is {stream.pageCount} pages. Most recruiters prefer 1 page.
                  </span>
                  <button
                    onClick={handleTrimToOnePage}
                    disabled={isSubmitting || isProcessing}
                    className="ml-3 text-[11px] text-warn underline hover:brightness-110 disabled:opacity-50"
                  >
                    Trim with AI →
                  </button>
                </div>
              )}
              <div className="relative min-h-0 min-w-0 flex-1 overflow-x-auto bg-bg">
                <LaTeXEditor
                  ref={editorRef}
                  value={resume?.latex_content || ''}
                  onChange={setEditorContent}
                  readOnly={isProcessing}
                  logLines={stream.logLines}
                  onAutoCompile={autoCompile && !isProcessing ? handleAutoCompile : undefined}
                  atsScore={quickATSScore}
                  atsScoreLoading={quickATSLoading}
                  onExplainError={handleExplainError}
                  pageCount={stream.pageCount}
                />
                <div className="absolute inset-x-0 bottom-0 z-10">
                  <ErrorExplainerPanel
                    isOpen={explainerOpen}
                    isLoading={explainerLoading}
                    data={explainerData}
                    errorLine={explainerLine}
                    onClose={() => setExplainerOpen(false)}
                    onApplyFix={handleApplyExplainerFix}
                  />
                </div>
              </div>
            </section>

            <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-[620px] min-w-0 flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between gap-2 border-b border-line bg-surface-2 px-4">
                <p className="shrink-0 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Output Preview</p>
                <div className="flex items-center gap-3">
                  {compareAfterLatex !== null && compareOriginalLatex !== null && (
                    <>
                      <button
                        onClick={() => setShowReviewModal(true)}
                        className="text-xs font-semibold text-ok transition hover:brightness-110"
                      >
                        Review Changes
                      </button>
                      <button
                        onClick={() => setShowCompareModal(true)}
                        className="text-xs font-semibold text-accent-strong transition hover:brightness-110"
                      >
                        Compare with Original
                      </button>
                    </>
                  )}
                  {pdfUrl && (
                    <a href={pdfUrl} download="optimized_resume.pdf" className="text-xs font-semibold text-fg-2 transition hover:text-fg">
                      Download PDF
                    </a>
                  )}
                </div>
              </div>
              <div className="min-h-0 flex-1 bg-bg">
                <PDFPreview pdfUrl={pdfUrl} isLoading={isProcessing && stream.percent > 40} />
              </div>
            </section>
          </div>

          <section className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden">
            {/* Tab bar */}
            <div className="flex overflow-x-auto border-b border-line">
              {(['ATS Simulator', 'Keywords', 'Publications'] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveToolTab(tab)}
                  className={`shrink-0 px-5 py-3 text-xs font-semibold uppercase tracking-[0.14em] transition ${
                    activeToolTab === tab
                      ? 'border-b-2 border-accent text-accent-strong'
                      : 'text-fg-3 hover:text-fg-2'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="p-6">
              {activeToolTab === 'ATS Simulator' ? (
                <>
                  <p className="mb-5 text-sm text-fg-2">
                    See how major ATS platforms parse your resume. Select a system to view the
                    plain-text representation it would extract and identify any compatibility issues.
                  </p>
                  <AtsSimulatorPanel getLatexContent={() => editorRef.current?.getValue() || resume?.latex_content || ''} />
                </>
              ) : activeToolTab === 'Keywords' ? (
                <>
                  <p className="mb-5 text-sm text-fg-2">
                    Paste a job description to see which keywords your resume covers. Green = present,
                    amber = partial match, red = missing. Click a missing keyword for insertion advice.
                  </p>
                  <KeywordDensityMap getLatexContent={() => editorRef.current?.getValue() || resume?.latex_content || ''} />
                </>
              ) : (
                <>
                  <p className="mb-5 text-sm text-fg-2">
                    Fetch your publications from ORCID and insert a formatted bibliography section
                    directly into your resume. Filter by year range or publication type.
                  </p>
                  <PublicationsPanel insertAtCursor={(text) => editorRef.current?.insertAtCursor(text)} />
                </>
              )}
            </div>
          </section>

          <AnimatePresence>
            {stream.status === 'completed' && (
              <motion.section
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-[var(--radius-lg)] border border-line bg-surface p-6"
              >
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-xl font-semibold text-fg">ATS Analysis</h2>
                  <div className="flex gap-2">
                    <button
                      className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isSavingVersion}
                      onClick={async () => {
                        if (isSavingVersion) return
                        setIsSavingVersion(true)
                        try {
                          const latex = editorRef.current?.getValue() || stream.streamingLatex || ''
                          // Non-destructive: snapshot the CURRENT stored content as a
                          // checkpoint (recoverable from Version History) before the
                          // overwrite, so the prior version is never lost.
                          const stamp = new Date().toLocaleString()
                          try {
                            await apiClient.createCheckpoint(resumeId, `Before save · ${stamp}`)
                          } catch {
                            // Non-fatal — proceed with save even if snapshot fails
                          }
                          await apiClient.updateResume(resumeId, { latex_content: latex })
                          setBaselineLatex(latex) // the saved content is the new clean baseline
                          setEditorContent(latex)
                          setHistoryRefreshKey((k) => k + 1)
                          toast.success('New version saved — previous content kept in Version History')
                        } catch {
                          toast.error('Failed to save')
                        } finally {
                          setIsSavingVersion(false)
                        }
                      }}
                    >
                      {isSavingVersion ? 'Saving…' : 'Save as New Version'}
                    </button>
                    <button
                      className="rounded-[var(--radius-md)] bg-accent text-accent-fg hover:brightness-110 px-4 py-2 text-xs"
                      onClick={async () => {
                        if (!stream.pdfJobId) return
                        try {
                          const blob = await apiClient.downloadPdf(stream.pdfJobId)
                          const url = URL.createObjectURL(blob)
                          const a = document.createElement('a')
                          a.href = url
                          a.download = 'resume_optimized.pdf'
                          a.click()
                          URL.revokeObjectURL(url)
                        } catch {
                          toast.error('Failed to download PDF')
                        }
                      }}
                    >
                      Finalize and Export
                    </button>
                  </div>
                </div>
                <ATSScoreCard
                  score={industryOverrideResult?.ats_score ?? stream.atsScore ?? undefined}
                  categoryScores={industryOverrideResult?.category_scores ?? stream.atsDetails?.category_scores}
                  recommendations={industryOverrideResult?.recommendations ?? stream.atsDetails?.recommendations}
                  warnings={industryOverrideResult?.warnings ?? stream.atsDetails?.warnings}
                  strengths={industryOverrideResult?.strengths ?? stream.atsDetails?.strengths}
                  isLoading={isRescoringIndustry}
                  industryLabel={industryOverrideResult?.industry_label ?? (industryOverride ? null : stream.industryLabel)}
                  industryKey={industryOverrideResult?.industry_key ?? industryOverride ?? (stream.atsDetails as any)?.industry_key ?? null}
                  onIndustryOverride={handleIndustryOverride}
                />
              </motion.section>
            )}
          </AnimatePresence>
        </main>
      </div>

      {/* History checkpoint diff modal */}
      {showHistoryDiff && diffCheckpointA && (
        <DiffViewerModal
          resumeId={resumeId}
          checkpointA={diffCheckpointA}
          checkpointB={diffCheckpointB}
          currentLatex={editorRef.current?.getValue() ?? ''}
          onRestore={handleHistoryRestore}
          onClose={() => setShowHistoryDiff(false)}
        />
      )}

      {/* Parent diff modal */}
      {showParentDiff && parentDiffData && (
        <DiffViewerModal
          resumeId={resumeId}
          checkpointA={null}
          checkpointB={null}
          onRestore={(latex) => {
            editorRef.current?.setValue(latex)
            setShowParentDiff(false)
            toast.success('Version restored')
          }}
          onClose={() => setShowParentDiff(false)}
          parentLatex={parentDiffData.parent_latex}
          parentTitle={parentDiffData.parent_title}
          variantLatex={parentDiffData.variant_latex}
          variantTitle={parentDiffData.variant_title}
        />
      )}

      {/* Before/After optimization compare modal */}
      {showCompareModal && compareOriginalLatex !== null && compareAfterLatex !== null && (
        <CompareModal
          originalLatex={compareOriginalLatex}
          optimizedLatex={compareAfterLatex}
          optimizedPdfUrl={pdfUrl ?? undefined}
          compiler={compiler}
          onClose={() => setShowCompareModal(false)}
          onRestore={(latex) => {
            editorRef.current?.setValue(latex)
            setShowCompareModal(false)
            toast.success('Original restored')
          }}
        />
      )}

      {/* Per-change accept/reject review (F2-P0) */}
      {showReviewModal && compareOriginalLatex !== null && compareAfterLatex !== null && (
        <ChangeReviewModal
          originalLatex={compareOriginalLatex}
          optimizedLatex={compareAfterLatex}
          onApply={handleApplyReviewedChanges}
          onClose={() => setShowReviewModal(false)}
        />
      )}
    </div>
  )
}
