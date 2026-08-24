'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Clock, Copy, DownloadCloud,
  FileCode2, Files, Gauge, GitBranch, LayoutTemplate, Link2, Loader2, MapPin,
  PanelLeft, PanelLeftClose, PanelRight, PanelRightClose, Play, RotateCcw,
  Sparkles, Square, Upload, X, Zap,
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ExplainErrorResponse, type ScrapeJobResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useTrialStatus } from '@/hooks/useTrialStatus'
import LaTeXEditor, { LaTeXEditorRef } from '@/components/LaTeXEditor'
import ModeToggle from '@/components/theme/ModeToggle'
import DiffViewerModal from '@/components/DiffViewerModal'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { useQuickATSScore } from '@/hooks/useQuickATSScore'
import { DEMO_RESUME_TEMPLATE } from '@/lib/latex-templates'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'

const LogViewer = dynamic(() => import('@/components/LogViewer'))
const PDFPreview = dynamic(() => import('@/components/PDFPreview'))
const DeepAnalysisPanel = dynamic(() => import('@/components/ats/DeepAnalysisPanel'))
const MultiFormatUpload = dynamic(() => import('@/components/MultiFormatUpload'))
const ExportDropdown = dynamic(() => import('@/components/ExportDropdown'))
const ErrorExplainerPanel = dynamic(() => import('@/components/ErrorExplainerPanel'))
const ImportProjectsModal = dynamic(() => import('@/components/ImportProjectsModal'))

const CATEGORY_LABELS: Record<string, string> = {
  formatting: 'Formatting',
  structure: 'Structure',
  content: 'Content',
  keywords: 'Keywords',
  readability: 'Readability',
}

type Tool = 'files' | 'ai' | 'ats' | 'import' | 'templates'
type MobilePane = 'tools' | 'editor' | 'pdf'

const RAIL: { id: Tool; icon: typeof Files; label: string }[] = [
  { id: 'files', icon: Files, label: 'Files' },
  { id: 'ai', icon: Sparkles, label: 'AI Optimize' },
  { id: 'ats', icon: Gauge, label: 'ATS Score' },
  { id: 'import', icon: DownloadCloud, label: 'Import' },
  { id: 'templates', icon: LayoutTemplate, label: 'Templates' },
]

export default function TryPage() {
  const flags = useFeatureFlags()
  const [hydrated, setHydrated] = useState(false)
  const [latexContent, setLatexContent] = useState(DEMO_RESUME_TEMPLATE)
  const [jobDescription, setJobDescription] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [logsOpen, setLogsOpen] = useState(false)
  const [deepPanelOpen, setDeepPanelOpen] = useState(false)
  const [showImportModal, setShowImportModal] = useState(false)
  const [showProjectsModal, setShowProjectsModal] = useState(false)
  const [deepAnalysisJobId, setDeepAnalysisJobId] = useState<string | null>(null)
  const [deepAnalysisUsesRemaining, setDeepAnalysisUsesRemaining] = useState<number | null>(null)
  const [isDeepAnalysisRunning, setIsDeepAnalysisRunning] = useState(false)
  const [deepAnalysisError, setDeepAnalysisError] = useState<string | null>(null)

  // URL scraper
  const [jobUrl, setJobUrl] = useState('')
  const [isScraping, setIsScraping] = useState(false)
  const [scrapedMeta, setScrapedMeta] = useState<ScrapeJobResponse | null>(null)

  // Error explainer
  const [explainerOpen, setExplainerOpen] = useState(false)
  const [explainerLoading, setExplainerLoading] = useState(false)
  const [explainerData, setExplainerData] = useState<ExplainErrorResponse | null>(null)
  const [explainerLine, setExplainerLine] = useState<number | null>(null)

  // ── IDE shell layout state ──
  const [tool, setTool] = useState<Tool>('files')
  const [leftOpen, setLeftOpen] = useState(true)
  const [pdfOpen, setPdfOpen] = useState(true)
  const [split, setSplit] = useState(50) // % width of editor within editor+pdf area
  const [mobilePane, setMobilePane] = useState<MobilePane>('editor')
  const [isDesktop, setIsDesktop] = useState(true)
  const splitAreaRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)

  // ── local persistence + sync state ──
  const [persistState, setPersistState] = useState<'saved' | 'pending'>('saved')
  const [sourceCopied, setSourceCopied] = useState(false)
  const [cursorLine, setCursorLine] = useState<number | null>(null)
  const rehydratedRef = useRef(false)
  // Baseline the editor is considered "clean" against (demo, restored draft, or last compiled)
  const cleanBaselineRef = useRef(DEMO_RESUME_TEMPLATE)
  const hasUnsavedRef = useRef(false)
  // Editor content captured immediately before a run, restored if the job is cancelled
  const preRunSnapshotRef = useRef<string | null>(null)
  // Whether the in-flight run rewrites content (optimize/trim) vs. a plain compile.
  const lastRunOptimizeRef = useRef(false)
  // Pre-optimize content kept AFTER an optimize completes, so the user can review
  // the diff or revert to the original (AI optimize is otherwise destructive).
  const [optimizeSnapshot, setOptimizeSnapshot] = useState<string | null>(null)
  const [showOptimizeDiff, setShowOptimizeDiff] = useState(false)
  // Whether the currently in-flight/active job was triggered by auto-compile
  // rather than a manual Recompile click — used so a failed auto-compile gets
  // the same failure toast a manual compile's submit-catch already gives it,
  // without spamming a toast on every debounce tick for the same error.
  const autoCompileTriggeredRef = useRef(false)
  const lastAutoCompileErrorRef = useRef<string | null>(null)

  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()
  const { score: quickATSScore, loading: quickATSLoading, refetch: refetchATS } = useQuickATSScore(latexContent, jobDescription)
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)
  const { state: deepStream } = useJobStream(deepAnalysisJobId)
  const trialStatus = useTrialStatus()
  const { data: session } = useSession()
  const resolvedSession = hydrated ? session : null
  // When trial_limits flag is off, every visitor can run without restriction
  const effectiveCanRun = flags.trial_limits ? trialStatus.canRun : true
  // Anonymous visitor who has exhausted their free compiles
  const trialBlocked = !resolvedSession && !effectiveCanRun

  const notifyTrialBlocked = useCallback(() => {
    if (flags.upgrade_ctas) {
      toast.error("You've used all your free compiles", {
        description: 'Log in or upgrade to keep compiling.',
        action: { label: 'Upgrade', onClick: () => { window.location.href = '/billing' } },
      })
    } else {
      toast.error("You've used all your free compiles — log in to continue.")
    }
  }, [flags.upgrade_ctas])

  useEffect(() => {
    setHydrated(true)
  }, [])

  // Rehydrate the last locally-saved draft on mount so a reload/tab-close no
  // longer silently destroys work. The restored buffer becomes the clean
  // baseline so the beforeunload guard only fires on genuinely new edits.
  useEffect(() => {
    try {
      const savedTex = localStorage.getItem('latexy_try_latex')
      const savedJd = localStorage.getItem('latexy_try_jd')
      if (savedTex != null && savedTex !== latexContent) {
        setLatexContent(savedTex)
        editorRef.current?.setValue(savedTex)
        cleanBaselineRef.current = savedTex
      }
      if (savedJd != null) setJobDescription(savedJd)
    } catch {
      /* localStorage unavailable — ignore */
    }
    rehydratedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced autosave of the editor + job description to localStorage.
  useEffect(() => {
    if (!rehydratedRef.current) return
    setPersistState('pending')
    const t = setTimeout(() => {
      try {
        localStorage.setItem('latexy_try_latex', latexContent)
        localStorage.setItem('latexy_try_jd', jobDescription)
        setPersistState('saved')
      } catch {
        /* quota/unavailable — leave as pending */
      }
    }, 600)
    return () => clearTimeout(t)
  }, [latexContent, jobDescription])

  // Warn on unload when the buffer differs from the clean baseline.
  useEffect(() => {
    hasUnsavedRef.current =
      latexContent.trim() !== '' && latexContent !== cleanBaselineRef.current
  }, [latexContent])

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!hasUnsavedRef.current) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  const persistNow = useCallback(() => {
    try {
      localStorage.setItem('latexy_try_latex', editorRef.current?.getValue() ?? latexContent)
      localStorage.setItem('latexy_try_jd', jobDescription)
      setPersistState('saved')
      toast.success('Saved locally')
    } catch {
      toast.error('Could not save to this browser')
    }
  }, [latexContent, jobDescription])

  // Track desktop breakpoint so the resizable split (inline width %) applies
  // only at lg+, while mobile uses a single-pane switch.
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const apply = () => setIsDesktop(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (stream.streamingLatex && editorRef.current) {
      editorRef.current.setValue(stream.streamingLatex, { reveal: false })
      if (stream.status === 'completed' || stream.status === 'failed') {
        setLatexContent(stream.streamingLatex)
        // The AI-rewritten source is the new clean baseline
        cleanBaselineRef.current = stream.streamingLatex
        // Keep the pre-optimize content so the user can diff or revert a completed
        // optimize (otherwise the rewrite is destructive).
        if (stream.status === 'completed' && lastRunOptimizeRef.current
            && preRunSnapshotRef.current && preRunSnapshotRef.current !== stream.streamingLatex) {
          setOptimizeSnapshot(preRunSnapshotRef.current)
        }
        lastRunOptimizeRef.current = false
      }
    }
  }, [stream.streamingLatex, stream.status])

  useEffect(() => {
    const fetchPdf = async () => {
      if (stream.status === 'completed' && stream.pdfJobId) {
        try {
          const blob = await apiClient.downloadPdf(stream.pdfJobId)
          const url = URL.createObjectURL(blob)
          if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
          pdfUrlRef.current = url
          setPdfUrl(url)
        } catch {
          toast.error('Failed to load PDF preview')
        }
      } else if (stream.status === 'queued' || stream.status === 'processing') {
        if (pdfUrlRef.current) {
          URL.revokeObjectURL(pdfUrlRef.current)
          pdfUrlRef.current = null
        }
        setPdfUrl(null)
      }
    }
    fetchPdf()

    // Refresh ATS quick-score immediately after compile
    if (stream.status === 'completed') refetchATS()

    // Track analytics on completion/failure
    if (stream.status === 'completed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'completed')
      if (stream.tokensUsed) {
        apiClient.trackOptimization(activeJobId, 'openai', 'gpt-4o-mini', stream.tokensUsed)
        apiClient.trackFeatureUsage('optimize')
      } else {
        apiClient.trackFeatureUsage('compile')
      }
    } else if (stream.status === 'failed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'failed')
    }
  }, [stream.status, stream.pdfJobId, activeJobId, stream.tokensUsed, refetchATS])

  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = null
      }
    }
  }, [])

  // Draggable editor/PDF splitter
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!draggingRef.current || !splitAreaRef.current) return
      const rect = splitAreaRef.current.getBoundingClientRect()
      const pct = ((e.clientX - rect.left) / rect.width) * 100
      setSplit(Math.min(72, Math.max(28, pct)))
    }
    const up = () => { draggingRef.current = false; document.body.style.cursor = '' }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [])

  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  const runCompile = async (mode: 'compile' | 'combined') => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) { toast.error('LaTeX content is required'); return }
    if (trialBlocked) { notifyTrialBlocked(); return }
    preRunSnapshotRef.current = currentContent
    lastRunOptimizeRef.current = mode === 'combined'
    cleanBaselineRef.current = currentContent
    // Surface the result pane immediately on any submit (mobile lands on Editor otherwise)
    setMobilePane('pdf')
    setIsSubmitting(true)
    autoCompileTriggeredRef.current = false
    try {
      // Trial usage is now enforced+counted server-side in /jobs/submit for anonymous users.
      const response =
        mode === 'compile'
          ? await apiClient.compileLatex({ latex_content: currentContent, device_fingerprint: trialStatus.fingerprint })
          : await apiClient.optimizeAndCompile({
              latex_content: currentContent,
              job_description: jobDescription,
              optimization_level: 'balanced',
              device_fingerprint: trialStatus.fingerprint,
            })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed to submit job')
      setActiveJobId(response.job_id)
      if (!resolvedSession) trialStatus.incrementUsage()
      toast.success('Job submitted. Streaming updates live.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Submission failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = useCallback(async () => {
    if (!activeJobId) return
    try {
      await apiClient.cancelJob(activeJobId)
      // Restore the editor to its pre-run state (optimize overwrites it live).
      if (preRunSnapshotRef.current != null) {
        editorRef.current?.setValue(preRunSnapshotRef.current)
        setLatexContent(preRunSnapshotRef.current)
      }
      setActiveJobId(null)
      toast.success('Compile cancelled')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Cancel failed')
    }
  }, [activeJobId])

  const handleDownload = async () => {
    const downloadId = stream.pdfJobId ?? activeJobId
    if (!downloadId) { toast.error('No PDF is ready yet'); return }
    try {
      const blob = await apiClient.downloadPdf(downloadId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'latexy_resume.pdf'
      a.click()
      // Defer revocation so the browser has started the download before the
      // blob URL is invalidated (immediate revoke races the download in
      // Firefox / some Chromium builds).
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('PDF downloaded')
    } catch {
      toast.error('Download failed')
    }
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (isProcessing || isSubmitting) return
    if (!resolvedSession && !effectiveCanRun) return
    setIsSubmitting(true)
    try {
      // Trial usage is now enforced+counted server-side in /jobs/submit for anonymous users.
      const response = await apiClient.compileLatex({ latex_content: content, device_fingerprint: trialStatus.fingerprint })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      autoCompileTriggeredRef.current = true
      setActiveJobId(response.job_id)
      if (!resolvedSession) trialStatus.incrementUsage()
    } catch (error) {
      // Auto-compile fires on a debounce rather than a click, so a hard failure to
      // even submit (network/API error, trial exhausted, etc.) needs the same
      // toast.error runCompile's catch already gives manual compiles — deduped so a
      // persistent failure doesn't re-toast on every debounce tick while the user
      // keeps typing.
      const msg = error instanceof Error ? error.message : 'Auto-compile failed'
      if (lastAutoCompileErrorRef.current !== msg) {
        lastAutoCompileErrorRef.current = msg
        toast.error(msg)
      }
    } finally {
      setIsSubmitting(false)
    }
  }, [isProcessing, isSubmitting, resolvedSession, trialStatus, effectiveCanRun])

  // Surface auto-compile job failures (e.g. invalid LaTeX) the same way a manual
  // compile's result is visible — the status badge already turns red for any
  // trigger, but a toast is the only prompt that reaches a user who isn't looking
  // at the PDF pane (e.g. still mid-edit on mobile). One toast per distinct error,
  // not one per debounce tick — cleared on the next successful compile.
  useEffect(() => {
    if (!autoCompileTriggeredRef.current) return
    if (stream.status === 'failed') {
      const msg = stream.error || 'Auto-compile failed — open Live Logs for details'
      if (lastAutoCompileErrorRef.current !== msg) {
        lastAutoCompileErrorRef.current = msg
        toast.error(msg, { description: 'Auto-compile failed. Open Live Logs to see the LaTeX error.' })
      }
    } else if (stream.status === 'completed') {
      lastAutoCompileErrorRef.current = null
    }
  }, [stream.status, stream.error])

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

  const TRIM_INSTRUCTION = "Condense this resume to fit on exactly ONE page. Prioritize recent and most impactful content. Remove less critical details, condense bullet points, reduce descriptions. Do NOT remove any job titles, companies, degrees, or institution names."

  const handleTrimToOnePage = useCallback(async () => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) return
    if (trialBlocked) { notifyTrialBlocked(); return }
    preRunSnapshotRef.current = currentContent
    lastRunOptimizeRef.current = true
    cleanBaselineRef.current = currentContent
    setMobilePane('pdf')
    setIsSubmitting(true)
    autoCompileTriggeredRef.current = false
    try {
      // Trial usage is now enforced+counted server-side in /jobs/submit for anonymous users.
      const response = await apiClient.optimizeAndCompile({
        latex_content: currentContent,
        job_description: jobDescription,
        optimization_level: 'aggressive',
        custom_instructions: TRIM_INSTRUCTION,
        device_fingerprint: trialStatus.fingerprint,
      })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed to start trim')
      setActiveJobId(response.job_id)
      if (!resolvedSession) trialStatus.incrementUsage()
      toast.success('Trimming to 1 page…')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Trim failed')
    } finally {
      setIsSubmitting(false)
    }
  }, [latexContent, jobDescription, resolvedSession, trialStatus, TRIM_INSTRUCTION, trialBlocked, notifyTrialBlocked])

  // Revert a completed optimize back to the pre-optimize content.
  const revertOptimize = useCallback((latex?: string) => {
    const target = latex ?? optimizeSnapshot
    if (target == null) return
    editorRef.current?.setValue(target)
    setLatexContent(target)
    cleanBaselineRef.current = target
    setOptimizeSnapshot(null)
    setShowOptimizeDiff(false)
    toast.success('Reverted to your original resume')
  }, [optimizeSnapshot])

  const categoryScores = stream.atsDetails?.category_scores as Record<string, number> | undefined

  const handleRunDeepAnalysis = async (industryOverride?: string) => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) { toast.error('Add LaTeX content first'); return }
    setIsDeepAnalysisRunning(true)
    setDeepAnalysisError(null)
    try {
      const response = await apiClient.deepAnalyzeResume({
        latex_content: currentContent,
        job_description: jobDescription || undefined,
        device_fingerprint: trialStatus.fingerprint,
        industry_override: industryOverride,
      })
      if (response.success && response.job_id) {
        setDeepAnalysisJobId(response.job_id)
        setDeepAnalysisUsesRemaining(response.uses_remaining ?? null)
      } else {
        throw new Error(response.message || 'Deep analysis failed')
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Deep analysis failed'
      setDeepAnalysisError(msg)
      toast.error(msg)
      if (msg.startsWith('HTTP 402:')) {
        setDeepAnalysisUsesRemaining(0)
      }
    } finally {
      setIsDeepAnalysisRunning(false)
    }
  }

  const restoreContent = (prev: string) => {
    setLatexContent(prev)
    editorRef.current?.setValue(prev)
  }
  const resetEditor = () => {
    const prev = editorRef.current?.getValue() ?? latexContent
    restoreContent(DEMO_RESUME_TEMPLATE)
    toast('Reset to demo template', { action: { label: 'Undo', onClick: () => restoreContent(prev) } })
  }
  const clearEditor = () => {
    const prev = editorRef.current?.getValue() ?? latexContent
    restoreContent('')
    toast('Editor cleared', { action: { label: 'Undo', onClick: () => restoreContent(prev) } })
  }
  const nudgeSplit = (delta: number) => setSplit((s) => Math.min(72, Math.max(28, s + delta)))
  const handleSplitKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); nudgeSplit(-2) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); nudgeSplit(2) }
    else if (e.key === 'Home') { e.preventDefault(); setSplit(28) }
    else if (e.key === 'End') { e.preventDefault(); setSplit(72) }
    else if (e.key === 'Enter') { e.preventDefault(); setSplit(50) }
  }
  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(editorRef.current?.getValue() ?? latexContent)
      setSourceCopied(true)
      setTimeout(() => setSourceCopied(false), 1500)
    } catch {
      toast.error('Copy failed')
    }
  }
  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(stream.logLines.map((l) => l.line).join('\n'))
      toast.success('Logs copied')
    } catch {
      toast.error('Copy failed')
    }
  }
  const openTool = (id: Tool) => { setTool(id); setLeftOpen(true); setMobilePane('tools') }
  const trialsLabel = resolvedSession ? '∞' : hydrated ? String(trialStatus.remaining) : '…'
  const atsDisplay = stream.atsScore ?? quickATSScore

  // ────────────────────────── rail panel bodies ──────────────────────────
  // Rendered inline (not child components) so controlled inputs keep focus.
  const panelHead = (title: string, action?: React.ReactNode) => (
    <div className="flex items-center justify-between border-b border-line px-3 py-2">
      <span className="font-ui text-[12px] font-semibold uppercase tracking-[0.14em] text-fg-3">{title}</span>
      {action}
    </div>
  )

  const filesPanel = (
    <>
      {panelHead('Project')}
      <div className="p-1.5">
        <button
          type="button"
          onClick={() => setMobilePane('editor')}
          aria-current="true"
          className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] bg-accent-soft px-2 py-1.5 text-left font-mono text-[12px] text-accent-strong transition hover:brightness-105"
        >
          <FileCode2 size={13} className="flex-shrink-0 opacity-70" /> resume.tex
        </button>
      </div>
      <div className="border-t border-line p-3">
        <p className="mb-2 font-ui text-[11px] text-fg-3">Source</p>
        <div className="grid grid-cols-2 gap-1.5">
          <button onClick={resetEditor} className="flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-2 py-1.5 font-ui text-[11px] text-fg-2 transition hover:text-fg">
            <RotateCcw size={11} /> Reset
          </button>
          <button onClick={clearEditor} className="flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-2 py-1.5 font-ui text-[11px] text-fg-2 transition hover:text-fg">
            <X size={11} /> Clear
          </button>
        </div>
        <button onClick={() => setShowImportModal(true)} className="mt-1.5 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-2 py-1.5 font-ui text-[11px] text-fg-2 transition hover:text-fg">
          <Upload size={11} /> Import file (PDF · DOCX · TEX)
        </button>
      </div>
    </>
  )

  const aiPanel = (
    <div className="flex min-h-0 flex-1 flex-col">
      {panelHead('AI Optimize')}
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="border-b border-line p-3">
          <label className="font-ui text-[11px] text-fg-3">Target job</label>
          <div className="mt-1.5 flex gap-1.5">
            <input
              type="url"
              value={jobUrl}
              onChange={(e) => { setJobUrl(e.target.value); setScrapedMeta(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleScrapeUrl() }}
              placeholder="Paste job URL…"
              disabled={isProcessing || isScraping}
              className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1.5 font-body text-[12px] text-fg outline-none transition placeholder:text-fg-3 focus:border-accent disabled:opacity-50"
            />
            <button
              onClick={handleScrapeUrl}
              disabled={!jobUrl.trim() || isProcessing || isScraping}
              title="Import job description from URL"
              className="flex shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 text-fg-2 transition hover:text-fg disabled:opacity-40"
            >
              {isScraping ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />}
            </button>
          </div>
          {scrapedMeta && !scrapedMeta.error && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              {scrapedMeta.title && <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent-strong">{scrapedMeta.title}</span>}
              {scrapedMeta.company && <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg-2">{scrapedMeta.company}</span>}
              {scrapedMeta.location && <span className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg-3"><MapPin size={10} /> {scrapedMeta.location}</span>}
            </div>
          )}
          <textarea
            value={jobDescription}
            onChange={(e) => setJobDescription(e.target.value)}
            placeholder="…or paste a job description to tailor the optimization."
            className="mt-1.5 h-24 w-full resize-none rounded-[var(--radius-md)] border border-line bg-bg p-2 font-body text-[12px] text-fg outline-none transition placeholder:text-fg-3 focus:border-accent scrollbar-subtle"
          />
          <button
            onClick={() => runCompile('combined')}
            disabled={isSubmitting || isProcessing}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-3 py-2 font-ui text-xs font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sparkles size={13} /> {isSubmitting ? 'Running…' : 'Optimize for this role'}
          </button>
          <button
            onClick={handleTrimToOnePage}
            disabled={isSubmitting || isProcessing}
            className="mt-1.5 flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line-2 px-3 py-1.5 font-ui text-[11px] text-fg-2 transition hover:text-fg disabled:opacity-50"
          >
            Trim to one page
          </button>
        </div>
        {optimizeSnapshot != null && (
          <div className="border-t border-line p-3">
            <div className="flex items-center justify-between gap-2 rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft/40 px-3 py-2">
              <span className="font-ui text-[11px] text-fg-2">AI rewrote your resume.</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setShowOptimizeDiff(true)}
                  className="rounded-[var(--radius-sm)] px-2 py-1 font-ui text-[11px] font-medium text-accent-strong transition hover:bg-surface-2"
                >
                  View diff
                </button>
                <button
                  onClick={() => revertOptimize()}
                  className="rounded-[var(--radius-sm)] px-2 py-1 font-ui text-[11px] font-medium text-fg-2 transition hover:bg-surface-2"
                >
                  Revert to original
                </button>
              </div>
            </div>
          </div>
        )}
        {showOptimizeDiff && optimizeSnapshot != null && (
          <DiffViewerModal
            resumeId=""
            checkpointA={null}
            checkpointB={null}
            parentLatex={optimizeSnapshot}
            parentTitle="Original"
            variantLatex={editorRef.current?.getValue() || latexContent}
            variantTitle="AI Optimized"
            onRestore={(latex) => revertOptimize(latex)}
            onClose={() => setShowOptimizeDiff(false)}
          />
        )}
        {stream.changesMade && stream.changesMade.length > 0 && (
          <div className="p-3">
            <p className="mb-2 font-ui text-[11px] text-fg-3">{stream.changesMade.length} change{stream.changesMade.length !== 1 ? 's' : ''} applied</p>
            <ul className="space-y-1.5">
              {stream.changesMade.map((c, i) => {
                const ch = (typeof c === 'string' ? { reason: c } : c) as { section?: string; change_type?: string; reason?: string }
                const tone = ch.change_type === 'added' ? 'text-ok' : ch.change_type === 'removed' ? 'text-err' : 'text-accent-strong'
                return (
                  <li key={i} className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-2.5">
                    {(ch.section || ch.change_type) && (
                      <div className="mb-1 flex items-center gap-1.5">
                        {ch.section && <span className="font-ui text-[11px] font-semibold uppercase tracking-[0.1em] text-accent-strong">{ch.section}</span>}
                        {ch.change_type && <span className={`font-ui text-[9px] uppercase tracking-[0.08em] ${tone}`}>· {ch.change_type}</span>}
                      </div>
                    )}
                    <p className="flex gap-1.5 font-body text-[11px] leading-relaxed text-fg-2">
                      <Check size={12} className={`mt-0.5 shrink-0 ${tone}`} />
                      <span>{ch.reason || '—'}</span>
                    </p>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  )

  const atsPanel = (
    <div className="flex min-h-0 flex-1 flex-col">
      {panelHead('ATS Score', (
        <button onClick={() => { setDeepPanelOpen(true); if (!deepAnalysisJobId) handleRunDeepAnalysis() }} disabled={isDeepAnalysisRunning} className="font-ui text-[11px] text-accent-strong transition hover:brightness-110 disabled:opacity-50">
          {isDeepAnalysisRunning ? 'Analysing…' : 'Deep scan'}
        </button>
      ))}
      <div className="border-b border-line p-4 text-center">
        <p className="font-display text-5xl font-bold tabular-nums text-accent-strong">
          {atsDisplay != null ? atsDisplay : quickATSLoading ? '…' : '—'}
        </p>
        <p className="mt-0.5 font-ui text-[11px] text-fg-3">out of 100</p>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {categoryScores ? (
          <div className="space-y-3">
            {Object.entries(categoryScores).map(([key, val]) => (
              <div key={key}>
                <div className="mb-1 flex justify-between font-ui text-[11px]">
                  <span className="text-fg-2">{CATEGORY_LABELS[key] ?? key}</span>
                  <span className="tabular-nums text-fg-3">{val}</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${val}%` }} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="font-body text-[12px] leading-relaxed text-fg-3">Compile or optimize to see a category breakdown, or run a <b className="text-fg-2">Deep scan</b> for a full AI analysis.</p>
        )}
        {stream.tokensUsed != null && (
          <div className="mt-4 border-t border-line pt-3">
            <p className="font-ui text-[11px] uppercase tracking-[0.16em] text-fg-3">Tokens used</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-fg">{stream.tokensUsed.toLocaleString()}</p>
          </div>
        )}
      </div>
    </div>
  )

  const importPanel = (
    <>
      {panelHead('Import')}
      <div className="space-y-2 p-3">
        {[
          { icon: GitBranch, label: 'Import projects', hint: 'GitHub · Portfolio URL · LinkedIn export', onClick: () => setShowProjectsModal(true) },
          { icon: Upload, label: 'Existing file', hint: 'PDF · DOCX · TEX', onClick: () => setShowImportModal(true) },
        ].map((s) => (
          <button key={s.label} onClick={s.onClick} className="flex w-full items-center gap-3 rounded-[var(--radius-md)] border border-line bg-surface-2 p-2.5 text-left transition hover:border-accent">
            <span className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-[var(--radius-md)] bg-accent-soft text-accent-strong"><s.icon size={15} /></span>
            <span>
              <span className="block font-ui text-[12px] font-medium text-fg">{s.label}</span>
              <span className="block font-ui text-[11px] text-fg-3">{s.hint}</span>
            </span>
            <ChevronRight size={14} className="ml-auto text-fg-3" />
          </button>
        ))}
      </div>
    </>
  )

  const templatesPanel = (
    <>
      {panelHead('Templates', <Link href="/templates" className="font-ui text-[11px] text-accent-strong hover:brightness-110">Browse all →</Link>)}
      <div className="grid grid-cols-2 gap-2 p-3">
        {['Minimal', 'Two-column', 'Academic', 'ATS-safe'].map((t) => (
          <Link
            key={t}
            href="/templates"
            aria-label={`Open ${t} in the template gallery`}
            title={`Open ${t} in the template gallery`}
            className="group rounded-[var(--radius-md)] border border-line bg-surface-2 p-2 text-left transition hover:border-accent"
          >
            <div className="mb-1.5 aspect-[3/4] rounded-[var(--radius-sm)] bg-bg p-1.5">
              <div className="h-1.5 w-2/3 rounded bg-fg/20" />
              <div className="mt-1 h-1 w-full rounded bg-fg/10" />
              <div className="mt-0.5 h-1 w-4/5 rounded bg-fg/10" />
              <div className="mt-2 h-1 w-1/2 rounded bg-accent/40" />
              <div className="mt-1 h-1 w-full rounded bg-fg/10" />
            </div>
            <span className="flex items-center justify-between font-ui text-[11px] text-fg-2">
              {t}
              <ChevronRight size={12} className="text-fg-3 transition group-hover:text-accent-strong" />
            </span>
          </Link>
        ))}
      </div>
      <p className="px-3 pb-3 font-ui text-[11px] leading-relaxed text-fg-3">Previews open the full gallery — your current draft stays saved.</p>
    </>
  )

  const activePanel = tool === 'files' ? filesPanel : tool === 'ai' ? aiPanel : tool === 'ats' ? atsPanel : tool === 'import' ? importPanel : templatesPanel

  // ────────────────────────── editor + pdf panes ──────────────────────────
  const editorPane = (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <div className="flex h-9 flex-shrink-0 items-center gap-2 border-b border-line bg-surface-2 px-3">
        <FileCode2 size={13} className="text-fg-3" />
        <span className="font-mono text-xs text-fg-2">resume.tex</span>
        <button
          onClick={copySource}
          title="Copy LaTeX source"
          aria-label="Copy LaTeX source"
          className="ml-auto flex items-center gap-1 rounded-[var(--radius-sm)] px-1.5 py-0.5 font-ui text-[11px] text-fg-3 transition hover:bg-surface hover:text-fg"
        >
          {sourceCopied ? <Check size={11} className="text-ok" /> : <Copy size={11} />}
          {sourceCopied ? 'Copied' : 'Copy'}
        </button>
        <span className="font-ui text-[11px] text-fg-3">⌘F to find</span>
      </div>
      <div className="relative min-h-0 flex-1">
        <LaTeXEditor
          ref={editorRef}
          value={latexContent}
          onChange={setLatexContent}
          readOnly={isProcessing}
          logLines={stream.logLines}
          onCompile={() => runCompile('compile')}
          onSave={persistNow}
          onCursorChange={setCursorLine}
          onAutoCompile={autoCompile && !isProcessing ? handleAutoCompile : undefined}
          atsScore={quickATSScore}
          atsScoreLoading={quickATSLoading}
          onATSBadgeClick={() => openTool('ats')}
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
  )

  const pdfPane = (
    <section className="flex min-h-0 flex-1 flex-col bg-surface-2">
      {/* progress strip */}
      {(isProcessing || stream.stage) && (
        <div className="flex-shrink-0 border-b border-line bg-surface px-4 py-2">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate font-ui text-[12px] text-fg-2">{stream.stage || 'waiting'}</span>
            <div className="flex flex-shrink-0 items-center gap-2">
              <span className="font-mono text-[12px] text-fg-3">{stream.percent}%</span>
              {isProcessing && activeJobId && (
                <button
                  onClick={handleCancel}
                  title="Cancel this run"
                  className="flex items-center gap-1 rounded-[var(--radius-sm)] border border-line-2 px-1.5 py-0.5 font-ui text-[11px] font-medium text-fg-2 transition hover:border-err hover:text-err"
                >
                  <Square size={9} className="fill-current" /> Stop
                </button>
              )}
            </div>
          </div>
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${stream.percent}%` }} />
          </div>
        </div>
      )}

      {/* page-overflow + timeout banners */}
      {stream.pageCount !== null && stream.pageCount > 1 && (
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-warn/20 bg-warn/10 px-4 py-2">
          <span className="font-ui text-[12px] text-warn"><AlertTriangle size={11} className="mr-1 -mt-0.5 inline" /> {stream.pageCount} pages — most recruiters prefer 1.</span>
          <button onClick={handleTrimToOnePage} disabled={isSubmitting || isProcessing} className="shrink-0 font-ui text-[11px] text-warn underline hover:brightness-110 disabled:opacity-50">Trim with AI →</button>
        </div>
      )}
      {stream.timeoutError && (
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-accent/20 bg-accent-soft px-4 py-2">
          <span className="font-ui text-[11px] text-accent-strong"><Clock size={11} className="mr-1 -mt-0.5 inline" /> Compile timed out — {stream.timeoutError.plan} plan limit ({stream.timeoutError.plan === 'free' ? '30s' : stream.timeoutError.plan === 'basic' ? '120s' : '240s'})</span>
          {flags.upgrade_ctas && <a href="/billing" className="shrink-0 font-ui text-[11px] font-medium text-accent-strong underline hover:brightness-110">Upgrade →</a>}
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <PDFPreview
          pdfUrl={pdfUrl}
          isLoading={isProcessing}
          onDownload={handleDownload}
          jobId={stream.pdfJobId}
          latexContent={latexContent}
          syncFromLine={cursorLine}
          onSyncToSource={(line) => { editorRef.current?.highlightLine(line); if (!isDesktop) setMobilePane('editor') }}
          onJumpToLine={(line) => { editorRef.current?.highlightLine(line); if (!isDesktop) setMobilePane('editor') }}
        />
      </div>

      {/* compile status / logs footer — only once there's something to report */}
      {(stream.logLines.length > 0 || isProcessing || stream.status === 'completed' || stream.status === 'failed') && (
        <div className="flex-shrink-0 border-t border-line bg-surface">
          <div className="flex w-full items-center gap-2 px-3 py-1.5">
            <button onClick={() => setLogsOpen((v) => !v)} aria-expanded={logsOpen} className="flex flex-1 items-center gap-2 text-left">
              <span className={`flex items-center gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-0.5 font-ui text-[11px] font-semibold ${
                stream.status === 'completed' ? 'bg-ok/10 text-ok' : stream.status === 'failed' ? 'bg-err/10 text-err' : 'bg-surface-2 text-fg-3'
              }`}>
                {stream.status === 'completed' ? <Check size={10} /> : null}
                {stream.status === 'completed' ? 'Compiled' : stream.status === 'failed' ? 'Failed' : isProcessing ? 'Compiling…' : 'Ready'}
              </span>
              {stream.logLines.length > 0 && <span className="font-ui text-[12px] text-fg-3">{stream.logLines.length} log lines</span>}
              <ChevronDown size={13} className={`ml-auto text-fg-3 transition-transform ${logsOpen ? 'rotate-180' : ''}`} />
            </button>
            {stream.logLines.length > 0 && (
              <button
                onClick={copyLogs}
                title="Copy all log output"
                aria-label="Copy all log output"
                className="flex shrink-0 items-center gap-1 rounded-[var(--radius-sm)] px-1.5 py-0.5 font-ui text-[11px] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
              >
                <Copy size={11} /> Copy
              </button>
            )}
          </div>
          {logsOpen && (
            <div className="border-t border-line bg-bg">
              <LogViewer lines={stream.logLines} maxHeight="14rem" className="font-mono text-xs" />
            </div>
          )}
        </div>
      )}
    </section>
  )

  return (
    <div className="fixed inset-0 top-0 flex flex-col bg-bg text-fg">
      {/* ── top project bar ── */}
      <header className="flex h-12 flex-shrink-0 items-center gap-2 border-b border-line bg-surface px-3 sm:gap-3">
        <Link href="/" className="grid h-6 w-6 flex-shrink-0 place-items-center rounded-[var(--radius-sm)] bg-accent font-display text-sm font-bold text-accent-fg" title="Home">L</Link>
        <span className="hidden font-display text-sm font-semibold text-fg sm:inline">Résumé Studio</span>
        <span className="hidden rounded-[var(--radius-sm)] bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-3 md:inline">resume.tex</span>
        <span
          title={persistState === 'saved' ? 'Draft autosaved to this browser' : 'Saving your draft locally…'}
          className="hidden items-center gap-1 font-ui text-[11px] text-fg-3 lg:inline-flex"
        >
          {persistState === 'saved'
            ? <><Check size={10} className="text-ok" /> Saved locally</>
            : <><Loader2 size={10} className="animate-spin" /> Saving…</>}
        </span>

        <div className="ml-1 flex items-center sm:ml-2">
          <button
            onClick={() => runCompile('compile')}
            disabled={isSubmitting || isProcessing}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-3.5 py-1.5 font-ui text-xs font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isProcessing || isSubmitting ? <Loader2 size={13} className="animate-spin" /> : <Play size={12} className="fill-current" />}
            {isProcessing || isSubmitting ? 'Compiling…' : 'Recompile'}
          </button>
        </div>
        <button
          onClick={toggleAutoCompile}
          title="Auto-compile on change"
          className={`hidden select-none items-center gap-1.5 rounded-[var(--radius-md)] border px-2 py-1.5 font-ui text-[11px] transition sm:flex ${
            autoCompile ? 'border-accent bg-accent-soft text-accent-strong' : 'border-line-2 text-fg-3 hover:text-fg'
          }`}
        >
          <Zap size={12} /> Auto
        </button>

        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => openTool('ats')} className="hidden items-center gap-1.5 rounded-[var(--radius-pill)] border border-line bg-surface-2 px-2.5 py-1 font-ui text-[11px] text-fg-2 transition hover:border-accent sm:flex">
            <Gauge size={12} className="text-accent-strong" /> ATS <b className="tabular-nums text-accent-strong">{atsDisplay ?? '—'}</b>
          </button>
          <button
            onClick={() => setPdfOpen((v) => !v)}
            title={pdfOpen ? 'Editor only' : 'Show preview'}
            className="hidden h-8 w-8 place-items-center rounded-[var(--radius-md)] border border-line-2 text-fg-3 transition hover:border-accent hover:text-fg lg:grid"
          >
            {pdfOpen ? <PanelRightClose size={15} /> : <PanelRight size={15} />}
          </button>
          <ModeToggle />
          <ExportDropdown latexContent={editorRef.current?.getValue() || latexContent} onPdfExport={handleDownload} />
          {resolvedSession ? (
            <Link href="/dashboard" title="Dashboard" className="grid h-7 w-7 place-items-center rounded-[var(--radius-pill)] bg-accent-soft font-ui text-[11px] font-semibold text-accent-strong">
              {(resolvedSession.user?.name || resolvedSession.user?.email || 'A').charAt(0).toUpperCase()}
            </Link>
          ) : (
            <div className="flex items-center gap-2">
              <span className="hidden font-ui text-[12px] text-fg-3 sm:inline">trials <b className="text-accent-strong">{trialsLabel}</b></span>
              <Link href="/login" className="whitespace-nowrap rounded-[var(--radius-md)] border border-line-2 px-2.5 py-1.5 font-ui text-[11px] font-semibold text-fg transition hover:border-accent hover:text-accent-strong">Log in</Link>
            </div>
          )}
        </div>
      </header>

      {/* ── trial-exhausted banner ── */}
      {trialBlocked && (
        <div className="flex flex-shrink-0 flex-wrap items-center justify-center gap-x-2 gap-y-0.5 border-b border-warn/20 bg-warn/10 px-3 py-1.5 text-center">
          <span className="font-ui text-[11px] text-warn">
            <AlertTriangle size={11} className="mr-1 -mt-0.5 inline" /> You&apos;ve used all your free compiles.
          </span>
          <span className="font-ui text-[11px] text-fg-2">
            <Link href="/login" className="font-semibold text-accent-strong underline hover:brightness-110">Log in</Link>
            {flags.upgrade_ctas && <> or <a href="/billing" className="font-semibold text-accent-strong underline hover:brightness-110">upgrade</a></>} to continue.
          </span>
        </div>
      )}

      {/* ── mobile pane switch (< lg) ── */}
      <div className="flex flex-shrink-0 items-center gap-1 border-b border-line bg-surface px-2 py-1.5 lg:hidden">
        {([['tools', 'Tools'], ['editor', 'Editor'], ['pdf', 'PDF']] as [MobilePane, string][]).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setMobilePane(id)}
            className={`flex-1 rounded-[var(--radius-md)] px-3 py-1.5 font-ui text-xs font-medium transition ${
              mobilePane === id ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'
            }`}
          >
            {label}
          </button>
        ))}
        {/* Auto-compile toggle — header copy is hidden < sm, so surface it here */}
        <button
          onClick={toggleAutoCompile}
          title="Auto-compile on change"
          aria-pressed={autoCompile}
          className={`flex shrink-0 select-none items-center gap-1 rounded-[var(--radius-md)] border px-2.5 py-1.5 font-ui text-xs font-medium transition sm:hidden ${
            autoCompile ? 'border-accent bg-accent-soft text-accent-strong' : 'border-line-2 text-fg-3'
          }`}
        >
          <Zap size={13} /> Auto
        </button>
      </div>

      {/* ── body ── */}
      <div className="flex min-h-0 flex-1">
        {/* icon rail (lg+) */}
        <nav className="hidden w-12 flex-shrink-0 flex-col items-center gap-1 border-r border-line bg-surface py-2 lg:flex">
          {RAIL.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              onClick={() => { setTool(id); setLeftOpen(true) }}
              title={label}
              className={`grid h-9 w-9 place-items-center rounded-[var(--radius-md)] transition ${
                tool === id && leftOpen ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:bg-surface-2 hover:text-fg'
              }`}
            >
              <Icon size={17} />
            </button>
          ))}
          <button onClick={() => setLeftOpen((v) => !v)} title="Toggle panel" className="mt-auto grid h-9 w-9 place-items-center rounded-[var(--radius-md)] text-fg-3 transition hover:bg-surface-2 hover:text-fg">
            {leftOpen ? <PanelLeftClose size={16} /> : <PanelLeft size={16} />}
          </button>
        </nav>

        {/* left context panel */}
        <aside className={`${mobilePane === 'tools' ? 'flex' : 'hidden'} ${leftOpen ? 'lg:flex' : 'lg:hidden'} w-full flex-shrink-0 flex-col border-r border-line bg-surface lg:w-64`}>
          {/* mobile rail (horizontal) */}
          <div className="flex items-center gap-1 border-b border-line px-2 py-1.5 lg:hidden">
            {RAIL.map(({ id, icon: Icon, label }) => (
              <button key={id} onClick={() => setTool(id)} title={label} className={`grid h-8 w-8 place-items-center rounded-[var(--radius-md)] transition ${tool === id ? 'bg-accent-soft text-accent-strong' : 'text-fg-3'}`}>
                <Icon size={16} />
              </button>
            ))}
          </div>
          {activePanel}
        </aside>

        {/* editor + pdf split area */}
        <div ref={splitAreaRef} className="flex min-h-0 min-w-0 flex-1">
          {/* editor */}
          <div
            className={`${mobilePane === 'editor' ? 'flex' : 'hidden'} min-h-0 min-w-0 flex-col lg:flex ${isDesktop ? 'lg:flex-none' : 'flex-1'}`}
            style={isDesktop ? { width: `${pdfOpen ? split : 100}%` } : undefined}
          >
            {editorPane}
          </div>

          {/* splitter (lg+) */}
          {pdfOpen && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize editor and preview panes"
              aria-valuenow={Math.round(split)}
              aria-valuemin={28}
              aria-valuemax={72}
              tabIndex={0}
              onMouseDown={() => { draggingRef.current = true; document.body.style.cursor = 'col-resize' }}
              onDoubleClick={() => setSplit(50)}
              onKeyDown={handleSplitKey}
              title="Drag to resize · double-click to reset · arrow keys to nudge"
              className="group hidden w-2 flex-shrink-0 cursor-col-resize items-center justify-center bg-transparent focus:outline-none lg:flex"
            >
              <div className="h-full w-px bg-line transition-colors group-hover:bg-accent group-focus-visible:w-[3px] group-focus-visible:bg-accent" />
            </div>
          )}

          {/* pdf */}
          {pdfOpen && (
            <div
              className={`${mobilePane === 'pdf' ? 'flex' : 'hidden'} min-h-0 min-w-0 flex-col lg:flex ${isDesktop ? 'lg:flex-none' : 'flex-1'}`}
              style={isDesktop ? { width: `${100 - split}%` } : undefined}
            >
              {pdfPane}
            </div>
          )}
        </div>
      </div>

      {/* ── modals ── */}
      <DeepAnalysisPanel
        isOpen={deepPanelOpen}
        onClose={() => setDeepPanelOpen(false)}
        isLoading={isDeepAnalysisRunning || deepStream.status === 'queued' || deepStream.status === 'processing'}
        analysis={deepStream.deepAnalysis}
        error={deepAnalysisError}
        usesRemaining={flags.trial_limits ? deepAnalysisUsesRemaining : null}
        onRun={handleRunDeepAnalysis}
        isRunning={isDeepAnalysisRunning}
        hideUpgradeCtas={!flags.upgrade_ctas}
      />

      <ImportProjectsModal
        isOpen={showProjectsModal}
        onClose={() => setShowProjectsModal(false)}
        onInsert={(latex: string) => {
          editorRef.current?.setValue(latex)
          setLatexContent(latex)
          setShowProjectsModal(false)
          toast.success('Imported into editor')
        }}
      />

      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4">
          <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)]">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold text-fg">Import Resume File</h3>
              <button onClick={() => setShowImportModal(false)} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg">
                <X size={16} />
              </button>
            </div>
            <p className="mb-5 text-xs text-fg-3">This will replace the current editor content.</p>
            <MultiFormatUpload
              onFileUpload={(content) => {
                if (content) {
                  editorRef.current?.setValue(content)
                  setLatexContent(content)
                  setShowImportModal(false)
                  toast.success('File imported successfully')
                }
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
