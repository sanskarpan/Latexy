'use client'

import { useEffect, useMemo, useState, useRef } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useTrialStatus } from '@/hooks/useTrialStatus'
import LaTeXEditor, { LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'

const sampleLatex = `\\documentclass[11pt,a4paper]{article}
\\usepackage[margin=0.72in]{geometry}
\\usepackage{enumitem}
\\setlist{nosep}

\\begin{document}
\\begin{center}
{\\LARGE\\textbf{Alex Morgan}} \\\\
\\vspace{1mm}
Senior Software Engineer \\\\
Email: alex@example.com | linkedin.com/in/alexmorgan
\\end{center}

\\section*{Summary}
Product-focused engineer with 6+ years building resilient SaaS systems, developer tooling,
and observability-first workflows.

\\section*{Experience}
\\textbf{Staff Engineer, Northbeam Labs} \\hfill 2022 - Present
\\begin{itemize}
\\item Led migration to event-driven backend reducing deployment risk by 35\\%
\\item Built internal design system used across 6 product surfaces
\\item Mentored 4 engineers and introduced measurable review standards
\\end{itemize}

\\section*{Skills}
TypeScript, Next.js, Python, PostgreSQL, Redis, Kubernetes, AWS
\\end{document}`

export default function TryPage() {
  const [latexContent, setLatexContent] = useState(sampleLatex)
  const [jobDescription, setJobDescription] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)
  const trialStatus = useTrialStatus()

  // 1. Stream handler: Direct Monaco mutation
  useEffect(() => {
    if (stream.streamingLatex && editorRef.current) {
      editorRef.current.setValue(stream.streamingLatex)
      
      if (stream.status === 'completed' || stream.status === 'failed') {
        setLatexContent(stream.streamingLatex)
      }
    }
  }, [stream.streamingLatex, stream.status])

  // 2. PDF Fetcher
  useEffect(() => {
    const fetchPdf = async () => {
      if (stream.status === 'completed' && stream.pdfJobId) {
        try {
          const blob = await apiClient.downloadPdf(stream.pdfJobId)
          const url = URL.createObjectURL(blob)
          if (pdfUrlRef.current) {
            URL.revokeObjectURL(pdfUrlRef.current)
          }
          pdfUrlRef.current = url
          setPdfUrl(url)
        } catch (err) {
          console.error('Failed to auto-fetch PDF:', err)
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
  }, [stream.status, stream.pdfJobId])

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
    // Get latest content from editor before submitting
    const currentContent = editorRef.current?.getValue() || latexContent
    
    if (!currentContent.trim()) {
      toast.error('LaTeX content is required')
      return
    }
    if (!trialStatus.canRun) {
      toast.error('Trial limit reached. Upgrade to continue.')
      return
    }
    setIsSubmitting(true)
    try {
      await apiClient.trackUsage(trialStatus.fingerprint, mode)
      const response =
        mode === 'compile'
          ? await apiClient.compileLatex({ latex_content: currentContent, device_fingerprint: trialStatus.fingerprint })
          : await apiClient.optimizeAndCompile({
              latex_content: currentContent,
              job_description: jobDescription,
              optimization_level: 'balanced',
              device_fingerprint: trialStatus.fingerprint,
            })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to submit job')
      }

      setActiveJobId(response.job_id)
      trialStatus.incrementUsage()
      toast.success('Job submitted. Streaming updates live.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Submission failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDownload = async () => {
    const downloadId = stream.pdfJobId ?? activeJobId
    if (!downloadId) {
      toast.error('No PDF is ready yet.')
      return
    }
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

  const handleReset = () => {
    setLatexContent(sampleLatex)
    editorRef.current?.setValue(sampleLatex)
  }

  const handleClear = () => {
    setLatexContent('')
    editorRef.current?.setValue('')
  }

  const statusTone = useMemo(() => {
    if (stream.status === 'completed') return 'text-emerald-300'
    if (stream.status === 'failed') return 'text-rose-300'
    if (isProcessing) return 'text-orange-300'
    return 'text-slate-300'
  }, [stream.status, isProcessing])

  return (
    <div className="content-shell">
      <div className="space-y-5">
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['Mode', 'Resume Studio'],
            ['Status', stream.status],
            ['Active Job', activeJobId ? `${activeJobId.slice(0, 12)}...` : 'None'],
            ['Trials Left', String(trialStatus.remaining)],
          ].map(([k, v]) => (
            <article key={k} className="surface-card edge-highlight p-3">
              <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">{k}</p>
              <p className="mt-1 text-base text-white">{v}</p>
            </article>
          ))}
        </section>

        <div className="grid gap-5 xl:grid-cols-[1.12fr_0.88fr]">
          <section className="surface-panel edge-highlight p-5 flex flex-col h-[800px]">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
              <div>
                <h1 className="text-2xl font-semibold text-white">Resume Studio</h1>
                <p className="mt-1 text-sm text-slate-400">Edit LaTeX source, attach job context, and run compile pipelines.</p>
              </div>
              <span className="text-xs font-mono uppercase tracking-[0.24em] text-slate-400">LaTeX Pipeline</span>
            </div>

            <div className="mb-3 flex flex-wrap gap-2 flex-shrink-0">
              <button
                onClick={handleReset}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10"
              >
                Reset Sample
              </button>
              <button
                onClick={handleClear}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10"
              >
                Clear Source
              </button>
            </div>

            <div className="flex-1 min-h-0 flex flex-col gap-4">
              <div className="flex-1 min-h-0 rounded-xl border border-white/10 bg-slate-950/70 overflow-hidden">
                <LaTeXEditor
                  ref={editorRef}
                  value={latexContent}
                  onChange={setLatexContent}
                />
              </div>

              <div className="h-36 flex-shrink-0 flex flex-col">
                 <div className="mb-2 flex items-center justify-between">
                   <label className="block text-xs uppercase tracking-[0.22em] text-slate-400">Job Description</label>
                   <span className="text-[10px] text-slate-600">optional</span>
                 </div>
                 <textarea
                   value={jobDescription}
                   onChange={(e) => setJobDescription(e.target.value)}
                   placeholder="Paste a job description to tailor the optimization. Leave blank for general improvements."
                   className="flex-1 w-full rounded-xl border border-white/10 bg-slate-950/70 p-4 text-sm text-slate-100 outline-none transition focus:border-orange-300/50 resize-none scrollbar-subtle"
                 />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-3 flex-shrink-0">
              <button
                onClick={() => runCompile('compile')}
                disabled={isSubmitting || isProcessing || !trialStatus.canRun}
                className="rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {isSubmitting ? 'Compiling...' : 'Compile'}
              </button>
              <button
                onClick={() => runCompile('combined')}
                disabled={isSubmitting || isProcessing || !trialStatus.canRun}
                className="rounded-lg bg-orange-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-orange-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSubmitting ? 'Running...' : 'Optimize + Compile'}
              </button>
            </div>
          </section>

          <section className="space-y-5">
            <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="surface-panel edge-highlight p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white">Execution Status</h2>
                <span className={`text-sm capitalize ${statusTone}`}>{stream.status}</span>
              </div>

              <div className="mt-3 rounded-xl border border-white/10 bg-slate-950/60 p-4">
                <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
                  <span>{stream.stage || 'waiting for submission'}</span>
                  <span>{stream.percent}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div className="h-full rounded-full bg-orange-300 transition-all" style={{ width: `${stream.percent}%` }} />
                </div>
                <p className="mt-3 text-sm text-slate-300">{stream.message || 'No events yet.'}</p>
              </div>

              <div className="mt-4 h-[500px] overflow-hidden rounded-xl border border-white/10 bg-slate-950/60">
                <PDFPreview 
                  pdfUrl={pdfUrl} 
                  isLoading={isProcessing}
                  onDownload={handleDownload}
                />
              </div>
            </motion.div>

            <div className="surface-panel edge-highlight p-5">
              <h3 className="mb-3 text-lg font-semibold text-white">Live Logs</h3>
              <div className="rounded-xl border border-white/10 bg-slate-950/70 overflow-hidden">
                <LogViewer 
                  lines={stream.logLines} 
                  maxHeight="16rem" 
                  className="font-mono text-xs" 
                />
              </div>
            </div>

            <div className="surface-panel edge-highlight p-5">
              <h3 className="mb-3 text-lg font-semibold text-white">Quality Signals</h3>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="surface-card p-3">
                  <p className="text-slate-400">ATS Score</p>
                  <p className="mt-1 text-xl font-semibold text-orange-200">{stream.atsScore ?? '--'}</p>
                </div>
                <div className="surface-card p-3">
                  <p className="text-slate-400">Tokens Used</p>
                  <p className="mt-1 text-xl font-semibold text-orange-200">{stream.tokensUsed ?? '--'}</p>
                </div>
              </div>

              <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/60 p-3">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Run Guidance</p>
                <div className="mt-2 space-y-2 text-sm text-slate-300">
                  <p>Use Compile for formatting-only checks.</p>
                  <p>Use Optimize + Compile when targeting a specific role.</p>
                  <p>Watch logs for warnings before downloading the final PDF.</p>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
