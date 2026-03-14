'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { GitFork, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type DiffWithParentResponse } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import ATSScoreCard from '@/components/ATSScoreCard'
import DiffViewerModal from '@/components/DiffViewerModal'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function OptimizationSuitePage() {
  const params = useParams()
  const router = useRouter()
  const resumeId = params.resumeId as string

  const [resume, setResume] = useState<{ title: string; latex_content: string } | null>(null)
  const [jobDescription, setJobDescription] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [baselineLatex, setBaselineLatex] = useState('')

  // Variant awareness
  const [parentResumeId, setParentResumeId] = useState<string | null>(null)
  const [parentTitle, setParentTitle] = useState<string | null>(null)
  const [parentDiffData, setParentDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showParentDiff, setShowParentDiff] = useState(false)
  const [forkPopoverOpen, setForkPopoverOpen] = useState(false)
  const [forkTitleInput, setForkTitleInput] = useState('')
  const [isForkingResume, setIsForkingResume] = useState(false)

  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)

  useEffect(() => {
    const fetchResume = async () => {
      try {
        const data = await apiClient.getResume(resumeId)
        setResume(data)
        setBaselineLatex(data.latex_content)
        editorRef.current?.setValue(data.latex_content)
        setParentResumeId(data.parent_resume_id ?? null)
        if (data.parent_resume_id) {
          apiClient.getResume(data.parent_resume_id).then(p => setParentTitle(p.title)).catch(() => {
            setParentResumeId(null)
          })
        }

        // Auto-compile on load so user sees PDF immediately
        if (data.latex_content && data.latex_content.length >= 100) {
          try {
            const r = await apiClient.compileLatex({ latex_content: data.latex_content, user_plan: 'pro', resume_id: resumeId })
            if (r.success && r.job_id) setActiveJobId(r.job_id)
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
  }, [resumeId, router])

  useEffect(() => {
    if (!stream.streamingLatex || !editorRef.current) return
    editorRef.current.setValue(stream.streamingLatex)
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
  }, [stream.status, stream.pdfJobId])

  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = null
      }
    }
  }, [])

  const runOptimization = async () => {
    const currentContent = editorRef.current?.getValue() || resume?.latex_content || ''
    setIsSubmitting(true)
    setPdfUrl(null)

    try {
      const response = await apiClient.optimizeAndCompile({
        latex_content: currentContent,
        job_description: jobDescription,
        optimization_level: 'balanced',
        user_plan: 'pro',
      })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to start optimization')
      }

      setActiveJobId(response.job_id)
      toast.success('Optimization pipeline started')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Optimization failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const restoreOriginal = () => {
    if (!baselineLatex || !editorRef.current) return
    editorRef.current.setValue(baselineLatex)
    toast.success('Original resume restored in editor')
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      const response = await apiClient.compileLatex({ latex_content: content, user_plan: 'pro', resume_id: resumeId })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      setActiveJobId(response.job_id)
    } catch {
      // Silent fail
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting, resumeId])

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
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="overline">Optimization</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Targeted Optimization</h1>
          <p className="mt-1 text-sm text-zinc-400">Optimize "{resume?.title}" — add a job description to tailor it to a specific role, or leave blank for general improvements.</p>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <button
              onClick={() => { setForkPopoverOpen(v => !v); setForkTitleInput(`${resume?.title ?? ''} — Variant`) }}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
            >
              <GitFork size={12} />
              Variant
            </button>
            {forkPopoverOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-white/10 bg-zinc-950 p-3 shadow-xl">
                <input
                  type="text"
                  value={forkTitleInput}
                  onChange={e => setForkTitleInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCreateVariant(); if (e.key === 'Escape') setForkPopoverOpen(false) }}
                  placeholder="Variant title"
                  autoFocus
                  className="w-full rounded-md border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-zinc-100 outline-none focus:border-orange-300/40 mb-2"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setForkPopoverOpen(false)} className="px-2 py-1 text-[10px] text-zinc-500 hover:text-zinc-300">Cancel</button>
                  <button onClick={handleCreateVariant} disabled={isForkingResume} className="rounded-md bg-orange-500/20 px-3 py-1 text-[10px] font-semibold text-orange-200 ring-1 ring-orange-400/20 hover:bg-orange-500/30 disabled:opacity-50">
                    {isForkingResume ? 'Creating...' : 'Create'}
                  </button>
                </div>
              </div>
            )}
          </div>
          <Link href={`/workspace/${resumeId}/edit`} className="btn-ghost px-4 py-2 text-xs">
            Back to Editor
          </Link>
          <span className="rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-orange-200">
            Pro Pipeline
          </span>
        </div>
      </header>

      {/* Variant banner */}
      {parentResumeId && parentTitle && (
        <div className="flex items-center justify-between rounded-lg border border-orange-500/10 bg-orange-500/5 px-4 py-2">
          <span className="text-xs text-zinc-400">
            Variant of: <span className="font-medium text-zinc-300">{parentTitle}</span>
          </span>
          <button
            onClick={handleCompareWithParent}
            className="text-xs font-semibold text-orange-300 transition hover:text-orange-200"
          >
            Compare with Parent
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <aside className="space-y-6">
          <section className="surface-panel edge-highlight p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">Job Description</h2>
              <span className="text-[10px] text-zinc-600">optional</span>
            </div>
            <textarea
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder="Paste a job description to tailor the optimization to a specific role. Leave blank for general improvements."
              disabled={isProcessing}
              className="scrollbar-subtle mt-3 h-64 w-full resize-none rounded-xl border border-white/10 bg-black/40 p-4 text-sm text-zinc-100 outline-none transition focus:border-orange-300/50"
            />
            <button
              onClick={runOptimization}
              disabled={isProcessing || isSubmitting}
              className="btn-accent mt-4 w-full py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isProcessing || isSubmitting ? 'Processing...' : jobDescription.trim() ? 'Optimize for this Role' : 'Optimize Resume'}
            </button>
          </section>

          <AnimatePresence>
            {activeJobId && (
              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="surface-panel edge-highlight p-5"
              >
                <div className="mb-4 flex items-start justify-between gap-3">
                  <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">Pipeline Status</h2>
                  <span className="text-[10px] font-mono text-zinc-500">{activeJobId.slice(0, 8)}</span>
                </div>
                <div className="h-2 rounded-full bg-white/10">
                  <div className="h-full rounded-full bg-orange-300 transition-all" style={{ width: `${stream.percent}%` }} />
                </div>
                <p className="mt-3 text-sm capitalize text-zinc-200">{stream.stage || 'Initializing'}</p>
                <p className="mt-1 text-xs text-zinc-500">{stream.message || 'Connecting to workers...'}</p>
              </motion.section>
            )}
          </AnimatePresence>

          <section className="surface-panel edge-highlight p-5">
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">Live Logs</h2>
            <div className="mt-4 h-56 overflow-hidden rounded-lg bg-black/60">
              <LogViewer lines={stream.logLines} maxHeight="100%" className="h-full text-[10px]" />
            </div>
          </section>
        </aside>

        <main className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-2">
            <section className="surface-panel edge-highlight flex h-[620px] flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between border-b border-white/10 bg-white/[0.03] px-4">
                <div className="flex items-center gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">LaTeX Source</p>
                  <button
                    onClick={toggleAutoCompile}
                    title="Auto-compile on change (2s debounce)"
                    className={`flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium transition ${
                      autoCompile
                        ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/30'
                        : 'text-zinc-600 hover:text-zinc-300'
                    }`}
                  >
                    <Zap size={10} />
                    Auto
                  </button>
                </div>
                <button onClick={restoreOriginal} className="text-xs font-semibold text-zinc-300 transition hover:text-white">
                  Restore Original
                </button>
              </div>
              <div className="min-h-0 flex-1 bg-black/20">
                <LaTeXEditor
                  ref={editorRef}
                  value={resume?.latex_content || ''}
                  onChange={() => {}}
                  readOnly={isProcessing}
                  onAutoCompile={autoCompile && !isProcessing ? handleAutoCompile : undefined}
                />
              </div>
            </section>

            <section className="surface-panel edge-highlight flex h-[620px] flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between border-b border-white/10 bg-white/[0.03] px-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">Output Preview</p>
                {pdfUrl && (
                  <a href={pdfUrl} download="optimized_resume.pdf" className="text-xs font-semibold text-zinc-300 transition hover:text-white">
                    Download PDF
                  </a>
                )}
              </div>
              <div className="min-h-0 flex-1 bg-black/30">
                <PDFPreview pdfUrl={pdfUrl} isLoading={isProcessing && stream.percent > 40} />
              </div>
            </section>
          </div>

          <AnimatePresence>
            {stream.status === 'completed' && stream.atsScore !== undefined && (
              <motion.section
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="surface-panel edge-highlight p-6"
              >
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-xl font-semibold text-white">ATS Analysis</h2>
                  <div className="flex gap-2">
                    <button
                      className="btn-ghost px-4 py-2 text-xs"
                      onClick={async () => {
                        try {
                          const latex = editorRef.current?.getValue() || stream.streamingLatex || ''
                          await apiClient.updateResume(resumeId, { latex_content: latex })
                          toast.success('Saved to resume')
                        } catch {
                          toast.error('Failed to save')
                        }
                      }}
                    >
                      Save as New Version
                    </button>
                    <button
                      className="btn-accent px-4 py-2 text-xs"
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
                  score={stream.atsScore ?? undefined}
                  categoryScores={stream.atsDetails?.category_scores}
                  recommendations={stream.atsDetails?.recommendations}
                  warnings={stream.atsDetails?.warnings}
                  strengths={stream.atsDetails?.strengths}
                />
              </motion.section>
            )}
          </AnimatePresence>
        </main>
      </div>

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
    </div>
  )
}
