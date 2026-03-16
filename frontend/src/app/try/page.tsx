'use client'

import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { ChevronDown, Upload, X, Zap } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { apiClient, type ExplainErrorResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useTrialStatus } from '@/hooks/useTrialStatus'
import LaTeXEditor, { LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import DeepAnalysisPanel from '@/components/ats/DeepAnalysisPanel'
import MultiFormatUpload from '@/components/MultiFormatUpload'
import ExportDropdown from '@/components/ExportDropdown'
import ErrorExplainerPanel from '@/components/ErrorExplainerPanel'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { useQuickATSScore } from '@/hooks/useQuickATSScore'
import { DEMO_RESUME_TEMPLATE } from '@/lib/latex-templates'
const CATEGORY_LABELS: Record<string, string> = {
  formatting: 'Formatting',
  structure: 'Structure',
  content: 'Content',
  keywords: 'Keywords',
  readability: 'Readability',
}

export default function TryPage() {
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
    if (!session && !trialStatus.canRun) { toast.error('Trial limit reached. Upgrade to continue.'); return }
    setIsSubmitting(true)
    try {
      if (!session) await apiClient.trackUsage(trialStatus.fingerprint, mode)
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
      if (!session) trialStatus.incrementUsage()
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
      URL.revokeObjectURL(url)
      toast.success('PDF downloaded')
    } catch {
      toast.error('Download failed')
    }
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (isProcessing || isSubmitting) return
    if (!session && !trialStatus.canRun) return
    setIsSubmitting(true)
    try {
      if (!session) await apiClient.trackUsage(trialStatus.fingerprint, 'compile')
      const response = await apiClient.compileLatex({ latex_content: content, device_fingerprint: trialStatus.fingerprint })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      setActiveJobId(response.job_id)
      if (!session) trialStatus.incrementUsage()
    } catch {
      // Silent fail for auto-compile
    } finally {
      setIsSubmitting(false)
    }
  }, [isProcessing, isSubmitting, session, trialStatus])

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

  const statusTone = useMemo(() => {
    if (stream.status === 'completed') return 'text-emerald-300'
    if (stream.status === 'failed') return 'text-rose-300'
    if (isProcessing) return 'text-orange-300 animate-pulse'
    return 'text-slate-500'
  }, [stream.status, isProcessing])

  const categoryScores = stream.atsDetails?.category_scores as Record<string, number> | undefined

  const handleRunDeepAnalysis = async () => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) { toast.error('Add LaTeX content first'); return }
    setIsDeepAnalysisRunning(true)
    setDeepAnalysisError(null)
    try {
      const response = await apiClient.deepAnalyzeResume({
        latex_content: currentContent,
        job_description: jobDescription || undefined,
        device_fingerprint: trialStatus.fingerprint,
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
            ['Trials Left', session ? '∞' : String(trialStatus.remaining)],
          ].map(([k, v]) => (
            <article key={k} className="surface-card edge-highlight p-3">
              <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">{k}</p>
              <p className={`mt-1 text-base text-white ${k === 'Status' ? statusTone : ''}`}>{v}</p>
            </article>
          ))}
        </section>

        {/* Main two-column grid — editor left, output right */}
        <div className="grid gap-5 xl:grid-cols-[1fr_1.1fr]">

          {/* ── LEFT: editor panel ── */}
          <section className="surface-panel edge-highlight p-5 flex flex-col h-[820px]">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
              <div>
                <h1 className="text-2xl font-semibold text-white">Resume Studio</h1>
                <p className="mt-1 text-sm text-slate-400">Edit LaTeX source, attach job context, and run compile pipelines.</p>
              </div>
              <span className="text-xs font-mono uppercase tracking-[0.24em] text-slate-400">LaTeX Pipeline</span>
            </div>

            <div className="mb-3 flex flex-wrap gap-2 flex-shrink-0">
              <button
                onClick={() => { setLatexContent(DEMO_RESUME_TEMPLATE); editorRef.current?.setValue(DEMO_RESUME_TEMPLATE) }}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10"
              >
                Reset Sample
              </button>
              <button
                onClick={() => { setLatexContent(''); editorRef.current?.setValue('') }}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10"
              >
                Clear Source
              </button>
              <button
                onClick={() => setShowImportModal(true)}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10 flex items-center gap-1.5"
              >
                <Upload size={12} />
                Import File
              </button>
            </div>

            <div className="flex-1 min-h-0 flex flex-col gap-4">
              <div className="relative flex-1 min-h-0 rounded-xl border border-white/10 bg-slate-950/70 overflow-hidden">
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
              <div className="h-32 flex-shrink-0 flex flex-col">
                <div className="mb-2 flex items-center justify-between">
                  <label className="block text-xs uppercase tracking-[0.22em] text-slate-400">Job Description</label>
                  <span className="text-[10px] text-slate-600">optional</span>
                </div>
                <textarea
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  placeholder="Paste a job description to tailor the optimization…"
                  className="flex-1 w-full rounded-xl border border-white/10 bg-slate-950/70 p-4 text-sm text-slate-100 outline-none transition focus:border-orange-300/50 resize-none scrollbar-subtle"
                />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-3 flex-shrink-0 items-center">
              <button
                onClick={toggleAutoCompile}
                title="Auto-compile on change (2s debounce)"
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition ${
                  autoCompile
                    ? 'border-orange-500/30 bg-orange-500/20 text-orange-300'
                    : 'border-white/15 bg-white/5 text-zinc-500 hover:text-zinc-200 hover:bg-white/10'
                }`}
              >
                <Zap size={12} />
                Auto
              </button>
              <button
                onClick={() => runCompile('compile')}
                disabled={isSubmitting || isProcessing || (!session && !trialStatus.canRun)}
                className="rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {isSubmitting ? 'Compiling…' : 'Compile'}
              </button>
              <button
                onClick={() => runCompile('combined')}
                disabled={isSubmitting || isProcessing || (!session && !trialStatus.canRun)}
                className="rounded-lg bg-orange-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-orange-200 disabled:cursor-not-allowed disabled:opacity-50"
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
              className="surface-panel edge-highlight px-5 py-4"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`text-xs font-semibold uppercase tracking-[0.16em] ${statusTone}`}>
                    {stream.status}
                  </span>
                  <span className="text-sm text-slate-400 truncate">{stream.stage || 'waiting for submission'}</span>
                </div>
                <span className="text-xs font-mono text-slate-500 flex-shrink-0">{stream.percent}%</span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div className="h-full rounded-full bg-orange-300 transition-all duration-500" style={{ width: `${stream.percent}%` }} />
              </div>
              {stream.message && (
                <p className="mt-2 text-xs text-slate-500 truncate">{stream.message}</p>
              )}
            </motion.div>

            {/* PDF viewer + Quality signals side-by-side */}
            <div className="grid gap-3 grid-cols-[1fr_188px]">
              {/* PDF viewer — large */}
              <div className="surface-panel edge-highlight overflow-hidden h-[680px]">
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
                  <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">ATS Score</p>
                  <p className="mt-1 text-4xl font-bold tabular-nums text-orange-200">
                    {stream.atsScore != null ? stream.atsScore : '—'}
                  </p>
                  {stream.atsScore != null && (
                    <p className="mt-0.5 text-[10px] text-slate-500">out of 100</p>
                  )}
                </div>

                {/* Tokens */}
                <div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Tokens Used</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums text-slate-200">
                    {stream.tokensUsed != null ? stream.tokensUsed.toLocaleString() : '—'}
                  </p>
                </div>

                {/* Category scores */}
                {categoryScores && (
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Categories</p>
                    {Object.entries(categoryScores).map(([key, val]) => (
                      <div key={key}>
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] text-slate-400">{CATEGORY_LABELS[key] ?? key}</span>
                          <span className="text-[10px] font-mono text-slate-300">{val}</span>
                        </div>
                        <div className="h-1 w-full rounded-full bg-slate-800">
                          <div
                            className="h-full rounded-full bg-orange-300/70 transition-all"
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
                    <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Changes</p>
                    <p className="mt-1 text-xl font-semibold tabular-nums text-slate-200">{stream.changesMade.length}</p>
                    <p className="mt-0.5 text-[10px] text-slate-500">sections modified</p>
                  </div>
                )}

                {/* AI Deep Analysis */}
                <div className="border-t border-white/8 pt-4">
                  <button
                    onClick={() => { setDeepPanelOpen(true); if (!deepAnalysisJobId) handleRunDeepAnalysis() }}
                    disabled={isDeepAnalysisRunning}
                    className="w-full rounded-lg bg-violet-500/20 px-3 py-2 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30 disabled:opacity-50"
                  >
                    {isDeepAnalysisRunning ? 'Analysing…' : 'AI Analysis'}
                  </button>
                  {deepAnalysisUsesRemaining !== null && (
                    <p className="mt-1.5 text-[10px] text-center text-slate-600">{deepAnalysisUsesRemaining} free uses left</p>
                  )}
                </div>
              </div>
            </div>

            {/* Live logs — collapsed by default */}
            <div className="surface-panel edge-highlight overflow-hidden">
              <button
                onClick={() => setLogsOpen(v => !v)}
                className="flex w-full items-center justify-between px-5 py-3.5 text-left"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-sm font-semibold text-white">Live Logs</span>
                  {stream.logLines.length > 0 && (
                    <span className="rounded-md bg-white/8 px-1.5 py-0.5 text-[10px] font-mono text-slate-400">
                      {stream.logLines.length}
                    </span>
                  )}
                </div>
                <ChevronDown
                  size={14}
                  className={`text-slate-500 transition-transform duration-200 ${logsOpen ? 'rotate-180' : ''}`}
                />
              </button>
              {logsOpen && (
                <div className="border-t border-white/10">
                  <div className="rounded-b-xl overflow-hidden bg-slate-950/70">
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
        usesRemaining={deepAnalysisUsesRemaining}
        onRun={handleRunDeepAnalysis}
        isRunning={isDeepAnalysisRunning}
      />

      {/* Import modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl shadow-black/60 p-6">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-base font-semibold text-zinc-100">Import Resume File</h3>
              <button
                onClick={() => setShowImportModal(false)}
                className="rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-zinc-500 mb-5">
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
