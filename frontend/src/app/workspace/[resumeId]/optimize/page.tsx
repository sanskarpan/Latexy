'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import ATSScoreCard from '@/components/ATSScoreCard'
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
          <Link href={`/workspace/${resumeId}/edit`} className="btn-ghost px-4 py-2 text-xs">
            Back to Editor
          </Link>
          <span className="rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-orange-200">
            Pro Pipeline
          </span>
        </div>
      </header>

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
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">LaTeX Source</p>
                <button onClick={restoreOriginal} className="text-xs font-semibold text-zinc-300 transition hover:text-white">
                  Restore Original
                </button>
              </div>
              <div className="min-h-0 flex-1 bg-black/20">
                <LaTeXEditor ref={editorRef} value={resume?.latex_content || ''} onChange={() => {}} readOnly={isProcessing} />
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
    </div>
  )
}
