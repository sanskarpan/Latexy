'use client'

import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { AlertTriangle, ChevronDown, Clock, Link2, Loader2, MapPin, Upload, X, Zap } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { apiClient, type ExplainErrorResponse, type ScrapeJobResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useTrialStatus } from '@/hooks/useTrialStatus'
import LaTeXEditor, { LaTeXEditorRef } from '@/components/LaTeXEditor'
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

const CATEGORY_LABELS: Record<string, string> = {
  formatting: 'Formatting',
  structure: 'Structure',
  content: 'Content',
  keywords: 'Keywords',
  readability: 'Readability',
}

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

  useEffect(() => {
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (stream.streamingLatex && editorRef.current) {
      editorRef.current.setValue(stream.streamingLatex)
      if (stream.status === 'completed' || stream.status === 'failed') {
        setLatexContent(stream.streamingLatex)
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

  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  const runCompile = async (mode: 'compile' | 'combined') => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) { toast.error('LaTeX content is required'); return }
    if (!resolvedSession && !effectiveCanRun) { toast.error('Trial limit reached. Upgrade to continue.'); return }
    setIsSubmitting(true)
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
      setActiveJobId(response.job_id)
      if (!resolvedSession) trialStatus.incrementUsage()
    } catch {
      // Silent fail for auto-compile
    } finally {
      setIsSubmitting(false)
    }
  }, [isProcessing, isSubmitting, resolvedSession, trialStatus, effectiveCanRun])

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
    if (!resolvedSession && !effectiveCanRun) { toast.error('Trial limit reached. Upgrade to continue.'); return }
    setIsSubmitting(true)
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
  }, [latexContent, jobDescription, resolvedSession, trialStatus, TRIM_INSTRUCTION, effectiveCanRun])

  const statusTone = useMemo(() => {
    if (stream.status === 'completed') return 'text-ok'
    if (stream.status === 'failed') return 'text-err'
    if (isProcessing) return 'text-accent-strong animate-pulse'
    return 'text-fg-3'
  }, [stream.status, isProcessing])

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

  return (
    <div className="content-shell">
      <div className="space-y-5">
        {/* KPI strip */}
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['Mode', 'Resume Studio'],
            ['Status', stream.status],
            ['Active Job', activeJobId ? `${activeJobId.slice(0, 12)}…` : 'None'],
            ['Trials Left', resolvedSession ? '∞' : hydrated ? String(trialStatus.remaining) : '…'],
          ].map(([k, v]) => (
            <article key={k} className="rounded-[var(--radius-lg)] border border-line bg-surface p-3">
              <p className="text-xs uppercase tracking-[0.18em] text-fg-3">{k}</p>
              <p className={`mt-1 text-base text-fg ${k === 'Status' ? statusTone : ''}`}>{v}</p>
            </article>
          ))}
        </section>

        {/* Main two-column grid — editor left, output right */}
        <div className="grid gap-5 xl:grid-cols-[1fr_1.1fr]">

          {/* ── LEFT: editor panel ── */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 flex flex-col h-[820px]">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
              <div>
                <h1 className="text-2xl font-semibold text-fg">Resume Studio</h1>
                <p className="mt-1 text-sm text-fg-2">Edit LaTeX source, attach job context, and run compile pipelines.</p>
              </div>
              <span className="text-xs font-mono uppercase tracking-[0.24em] text-fg-2">LaTeX Pipeline</span>
            </div>

            <div className="mb-3 flex flex-wrap gap-2 flex-shrink-0">
              <button
                onClick={() => { setLatexContent(DEMO_RESUME_TEMPLATE); editorRef.current?.setValue(DEMO_RESUME_TEMPLATE) }}
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-1.5 text-xs text-fg hover:bg-surface-2"
              >
                Reset Sample
              </button>
              <button
                onClick={() => { setLatexContent(''); editorRef.current?.setValue('') }}
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-1.5 text-xs text-fg hover:bg-surface-2"
              >
                Clear Source
              </button>
              <button
                onClick={() => setShowImportModal(true)}
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-1.5 text-xs text-fg hover:bg-surface-2 flex items-center gap-1.5"
              >
                <Upload size={12} />
                Import File
              </button>
            </div>

            <div className="flex-1 min-h-0 flex flex-col gap-4">
              {/* Page overflow warning banner */}
              {stream.pageCount !== null && stream.pageCount > 1 && (
                <div className="flex-shrink-0 flex items-center justify-between rounded-[var(--radius-md)] border border-warn/20 bg-warn/10 px-4 py-2">
                  <span className="text-xs text-warn">
                    <AlertTriangle size={12} className="inline mr-1 -mt-0.5" /> Your resume is {stream.pageCount} pages. Most recruiters prefer 1 page.
                  </span>
                  <button
                    onClick={handleTrimToOnePage}
                    disabled={isSubmitting || isProcessing}
                    className="ml-3 text-xs text-warn underline hover:brightness-110 disabled:opacity-50"
                  >
                    Trim with AI →
                  </button>
                </div>
              )}

              {/* Compile timeout banner */}
              {stream.timeoutError && (
                <div className="flex-shrink-0 flex items-center justify-between rounded-[var(--radius-md)] border border-accent/20 bg-accent-soft px-4 py-2">
                  <span className="text-xs text-accent-strong">
                    <Clock size={12} className="inline mr-1 -mt-0.5" /> Compile timed out — {stream.timeoutError.plan} plan limit ({
                      stream.timeoutError.plan === 'free' ? '30s'
                      : stream.timeoutError.plan === 'basic' ? '120s'
                      : '240s'
                    })
                  </span>
                  {flags.upgrade_ctas && (
                    <a
                      href="/billing"
                      className="ml-3 shrink-0 text-xs font-medium text-accent-strong underline hover:brightness-110"
                    >
                      Upgrade for longer timeouts →
                    </a>
                  )}
                </div>
              )}
              <div className="relative flex-1 min-h-0 rounded-[var(--radius-lg)] border border-line bg-bg overflow-hidden">
                <LaTeXEditor
                  ref={editorRef}
                  value={latexContent}
                  onChange={setLatexContent}
                  logLines={stream.logLines}
                  onAutoCompile={autoCompile && !isProcessing ? handleAutoCompile : undefined}
                  atsScore={quickATSScore}
                  atsScoreLoading={quickATSLoading}
                  onATSBadgeClick={() => setDeepPanelOpen(true)}
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
              <div className="min-h-32 flex-shrink-0 flex flex-col">
                <div className="mb-2 flex items-center justify-between">
                  <label className="block text-xs uppercase tracking-[0.22em] text-fg-2">Job Description</label>
                  <span className="text-[10px] text-fg-3">optional</span>
                </div>
                <div className="mb-1.5 flex flex-col gap-2 sm:flex-row">
                  <input
                    type="url"
                    value={jobUrl}
                    onChange={(e) => { setJobUrl(e.target.value); setScrapedMeta(null) }}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleScrapeUrl() }}
                    placeholder="Paste job URL (Greenhouse, Lever, Workday, Indeed…)"
                    disabled={isProcessing || isScraping}
                    className="w-full min-w-0 flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none transition placeholder:text-fg-3 focus:border-accent disabled:opacity-50 sm:py-1.5"
                  />
                  <button
                    onClick={handleScrapeUrl}
                    disabled={!jobUrl.trim() || isProcessing || isScraping}
                    title="Import job description from URL"
                    className="flex shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs font-medium text-fg-2 transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40 sm:py-1.5"
                  >
                    {isScraping ? <Loader2 size={11} className="animate-spin" /> : <Link2 size={11} />}
                    {isScraping ? 'Importing…' : 'Import'}
                  </button>
                </div>
                {scrapedMeta && !scrapedMeta.error && (
                  <div className="mb-1.5 flex flex-wrap items-center gap-1">
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
                      <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-3 inline-flex items-center gap-1">
                        <MapPin size={10} /> {scrapedMeta.location}
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
                    <span className="ml-auto text-[9px] text-fg-3">via {scrapedMeta.source}</span>
                  </div>
                )}
                <textarea
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  placeholder="Paste a job description to tailor the optimization…"
                  className="flex-1 w-full rounded-[var(--radius-lg)] border border-line bg-bg p-4 text-sm text-fg outline-none transition focus:border-accent resize-none scrollbar-subtle"
                />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-3 flex-shrink-0 items-center">
              <button
                onClick={toggleAutoCompile}
                title="Auto-compile on change (2s debounce)"
                className={`flex items-center gap-1.5 rounded-[var(--radius-md)] border px-3 py-2 text-xs font-medium transition ${
                  autoCompile
                    ? 'border-accent bg-accent-soft text-accent-strong'
                    : 'border-line-2 bg-surface-2 text-fg-3 hover:text-fg hover:bg-surface-2'
                }`}
              >
                <Zap size={12} />
                Auto
              </button>
              <button
                onClick={() => runCompile('compile')}
                disabled={isSubmitting || isProcessing || (!resolvedSession && !effectiveCanRun)}
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-sm text-fg transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {isSubmitting ? 'Compiling…' : 'Compile'}
              </button>
              <button
                onClick={() => runCompile('combined')}
                disabled={isSubmitting || isProcessing || (!resolvedSession && !effectiveCanRun)}
                className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSubmitting ? 'Running…' : 'Optimize + Compile'}
              </button>
              <ExportDropdown
                latexContent={editorRef.current?.getValue() || latexContent}
                onPdfExport={handleDownload}
              />
            </div>
          </section>

          {/* ── RIGHT: output panel ── */}
          <section className="space-y-3">
            {/* Progress strip */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-[var(--radius-lg)] border border-line bg-surface px-5 py-4"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`text-xs font-semibold uppercase tracking-[0.16em] ${statusTone}`}>
                    {stream.status}
                  </span>
                  <span className="text-sm text-fg-2 truncate">{stream.stage || 'waiting for submission'}</span>
                </div>
                <span className="text-xs font-mono text-fg-3 flex-shrink-0">{stream.percent}%</span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${stream.percent}%` }} />
              </div>
              {stream.message && (
                <p className="mt-2 text-xs text-fg-3 truncate">{stream.message}</p>
              )}
            </motion.div>

            {/* PDF viewer + Quality signals side-by-side */}
            <div className="grid gap-3 grid-cols-[1fr_188px]">
              {/* PDF viewer — large */}
              <div className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden h-[680px]">
                <PDFPreview
                  pdfUrl={pdfUrl}
                  isLoading={isProcessing}
                  onDownload={handleDownload}
                />
              </div>

              {/* Quality signals sidebar — no box, clean list */}
              <div className="flex flex-col gap-5 py-1">
                {/* ATS score */}
                <div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">ATS Score</p>
                  <p className="mt-1 text-4xl font-bold tabular-nums text-accent-strong">
                    {stream.atsScore != null ? stream.atsScore : '—'}
                  </p>
                  {stream.atsScore != null && (
                    <p className="mt-0.5 text-[10px] text-fg-3">out of 100</p>
                  )}
                </div>

                {/* Tokens */}
                <div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Tokens Used</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums text-fg">
                    {stream.tokensUsed != null ? stream.tokensUsed.toLocaleString() : '—'}
                  </p>
                </div>

                {/* Category scores */}
                {categoryScores && (
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Categories</p>
                    {Object.entries(categoryScores).map(([key, val]) => (
                      <div key={key}>
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] text-fg-2">{CATEGORY_LABELS[key] ?? key}</span>
                          <span className="text-[10px] font-mono text-fg-2">{val}</span>
                        </div>
                        <div className="h-1 w-full rounded-full bg-surface-2">
                          <div
                            className="h-full rounded-full bg-accent/70 transition-all"
                            style={{ width: `${val}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Changes count */}
                {stream.changesMade && stream.changesMade.length > 0 && (
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Changes</p>
                    <p className="mt-1 text-xl font-semibold tabular-nums text-fg">{stream.changesMade.length}</p>
                    <p className="mt-0.5 text-[10px] text-fg-3">sections modified</p>
                  </div>
                )}

                {/* AI Deep Analysis */}
                <div className="border-t border-line pt-4">
                  <button
                    onClick={() => { setDeepPanelOpen(true); if (!deepAnalysisJobId) handleRunDeepAnalysis() }}
                    disabled={isDeepAnalysisRunning}
                    className="w-full rounded-[var(--radius-md)] bg-accent-soft px-3 py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:opacity-50"
                  >
                    {isDeepAnalysisRunning ? 'Analysing…' : 'AI Analysis'}
                  </button>
                  {deepAnalysisUsesRemaining !== null && (
                    <p className="mt-1.5 text-[10px] text-center text-fg-3">{deepAnalysisUsesRemaining} free uses left</p>
                  )}
                </div>
              </div>
            </div>

            {/* Live logs — collapsed by default */}
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden">
              <button
                onClick={() => setLogsOpen(v => !v)}
                className="flex w-full items-center justify-between px-5 py-3.5 text-left"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-sm font-semibold text-fg">Live Logs</span>
                  {stream.logLines.length > 0 && (
                    <span className="rounded-[var(--radius-md)] bg-surface-2 px-1.5 py-0.5 text-[10px] font-mono text-fg-2">
                      {stream.logLines.length}
                    </span>
                  )}
                </div>
                <ChevronDown
                  size={14}
                  className={`text-fg-3 transition-transform duration-200 ${logsOpen ? 'rotate-180' : ''}`}
                />
              </button>
              {logsOpen && (
                <div className="border-t border-line">
                  <div className="rounded-b-[var(--radius-lg)] overflow-hidden bg-bg">
                    <LogViewer
                      lines={stream.logLines}
                      maxHeight="18rem"
                      className="font-mono text-xs"
                    />
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
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

      {/* Import modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-[var(--overlay)] flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)] p-6">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-base font-semibold text-fg">Import Resume File</h3>
              <button
                onClick={() => setShowImportModal(false)}
                className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-fg-3 mb-5">
              This will replace the current editor content.
            </p>
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
