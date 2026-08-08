'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { FileText, Mail, Zap } from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type CoverLetterResponse,
  type CoverLetterTone,
  type CoverLetterLength,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { useJobStream } from '@/hooks/useJobStream'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import LoadingSpinner from '@/components/LoadingSpinner'

const TONE_OPTIONS: { value: CoverLetterTone; label: string; desc: string }[] = [
  { value: 'formal', label: 'Formal', desc: 'Professional and polished' },
  { value: 'conversational', label: 'Conversational', desc: 'Warm and approachable' },
  { value: 'enthusiastic', label: 'Enthusiastic', desc: 'Energetic and passionate' },
]

const LENGTH_OPTIONS: { value: CoverLetterLength; label: string; desc: string }[] = [
  { value: '3_paragraphs', label: '3 Paragraphs', desc: 'Concise and focused' },
  { value: '4_paragraphs', label: '4 Paragraphs', desc: 'More detail' },
  { value: 'detailed', label: 'Detailed', desc: 'Comprehensive (5+)' },
]

export default function CoverLetterPage() {
  const params = useParams()
  const router = useRouter()
  const { data: session, isPending: sessionLoading } = useSession()
  const resumeId = params.resumeId as string

  const [resume, setResume] = useState<{ title: string; latex_content: string } | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Form state
  const [jobDescription, setJobDescription] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [tone, setTone] = useState<CoverLetterTone>('formal')
  const [lengthPref, setLengthPref] = useState<CoverLetterLength>('3_paragraphs')

  // Generation state
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [activeCoverLetterId, setActiveCoverLetterId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [existingCoverLetters, setExistingCoverLetters] = useState<CoverLetterResponse[]>([])
  const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false)

  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!sessionLoading && !session) {
      router.push('/login')
    }
  }, [session, sessionLoading, router])

  // Load resume + existing cover letters
  useEffect(() => {
    if (!session) return
    const fetchData = async () => {
      try {
        const [data, cls] = await Promise.all([
          apiClient.getResume(resumeId),
          apiClient.getResumeCoverLetters(resumeId),
        ])
        setResume(data)
        setExistingCoverLetters(cls)

        // If there are existing cover letters, load the most recent one
        if (cls.length > 0 && cls[0].latex_content) {
          editorRef.current?.setValue(cls[0].latex_content)
          setActiveCoverLetterId(cls[0].id)
          // Auto-compile the existing cover letter
          try {
            const r = await apiClient.compileLatex({ latex_content: cls[0].latex_content })
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
    fetchData()
  }, [resumeId, router, session])

  // Stream LLM tokens into editor
  useEffect(() => {
    if (!stream.streamingLatex || !editorRef.current) return
    editorRef.current.setValue(stream.streamingLatex)
  }, [stream.streamingLatex])

  // Auto-compile after LLM generation completes (worker emits pdf_job_id: null)
  const generationJobIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (stream.status !== 'completed') return
    // If pdfJobId is set and different from the generation job, it's a compile job — fetch PDF
    if (stream.pdfJobId && stream.pdfJobId !== generationJobIdRef.current) {
      const fetchPdf = async () => {
        try {
          const blob = await apiClient.downloadPdf(stream.pdfJobId!)
          const nextUrl = URL.createObjectURL(blob)
          if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
          pdfUrlRef.current = nextUrl
          setPdfUrl(nextUrl)
        } catch {
          toast.error('Failed to load PDF')
        }
      }
      fetchPdf()
      return
    }
    // Generation just completed (no real pdf_job_id) — auto-compile the generated LaTeX
    if (activeJobId && activeJobId === generationJobIdRef.current) {
      const content = editorRef.current?.getValue()
      if (content && content.length > 50) {
        apiClient.compileLatex({ latex_content: content }).then((r) => {
          if (r.success && r.job_id) {
            setActiveJobId(r.job_id)
          }
        }).catch(() => {
          // Silent — user can manually compile
        })
      }
      // Re-fetch cover letter from DB to get saved latex_content
      if (activeCoverLetterId) {
        apiClient.getCoverLetter(activeCoverLetterId).then((cl) => {
          setExistingCoverLetters((prev) =>
            prev.map((item) => (item.id === cl.id ? cl : item))
          )
        }).catch(() => {})
      }
    }

    // Track analytics
    if (activeJobId) {
      apiClient.trackCompilation(activeJobId, 'completed')
      apiClient.trackFeatureUsage('cover_letter_generation')
    }
  }, [stream.status, stream.pdfJobId, activeJobId, activeCoverLetterId])

  // Track failed jobs
  useEffect(() => {
    if (stream.status === 'failed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'failed')
    }
  }, [stream.status, activeJobId])

  // Cleanup PDF URLs
  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = null
      }
    }
  }, [])

  const runGeneration = async () => {
    if (!jobDescription.trim()) {
      toast.error('Please provide a job description')
      return
    }
    setIsSubmitting(true)
    setPdfUrl(null)
    setHasUnsavedEdits(false)

    try {
      const response = await apiClient.generateCoverLetter({
        resume_id: resumeId,
        job_description: jobDescription,
        company_name: companyName || undefined,
        role_title: roleTitle || undefined,
        tone,
        length_preference: lengthPref,
      })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to start generation')
      }

      generationJobIdRef.current = response.job_id
      setActiveJobId(response.job_id)
      setActiveCoverLetterId(response.cover_letter_id)

      // Add partial entry to sidebar immediately
      const newEntry: CoverLetterResponse = {
        id: response.cover_letter_id,
        user_id: null,
        resume_id: resumeId,
        job_description: jobDescription,
        company_name: companyName || null,
        role_title: roleTitle || null,
        tone,
        length_preference: lengthPref,
        latex_content: null,
        pdf_path: null,
        generation_job_id: response.job_id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      setExistingCoverLetters((prev) => [newEntry, ...prev])

      toast.success('Cover letter generation started')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Generation failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const compileCurrentContent = async () => {
    const content = editorRef.current?.getValue()
    if (!content || content.length < 50) {
      toast.error('No content to compile')
      return
    }
    setIsSubmitting(true)
    try {
      const response = await apiClient.compileLatex({ latex_content: content })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      setActiveJobId(response.job_id)
    } catch {
      toast.error('Compilation failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const saveChanges = async () => {
    if (!activeCoverLetterId) return
    const content = editorRef.current?.getValue()
    if (!content) return
    try {
      await apiClient.updateCoverLetter(activeCoverLetterId, content)
      setHasUnsavedEdits(false)
      toast.success('Cover letter saved')
    } catch {
      toast.error('Failed to save')
    }
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      const response = await apiClient.compileLatex({ latex_content: content })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      setActiveJobId(response.job_id)
    } catch {
      // Silent
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting])

  const loadCoverLetter = async (cl: CoverLetterResponse) => {
    if (!cl.latex_content) return
    editorRef.current?.setValue(cl.latex_content)
    setActiveCoverLetterId(cl.id)
    setJobDescription(cl.job_description || '')
    setCompanyName(cl.company_name || '')
    setRoleTitle(cl.role_title || '')
    setTone(cl.tone as CoverLetterTone)
    setLengthPref(cl.length_preference as CoverLetterLength)
    setHasUnsavedEdits(false)
    // Compile loaded cover letter
    try {
      const r = await apiClient.compileLatex({ latex_content: cl.latex_content })
      if (r.success && r.job_id) setActiveJobId(r.job_id)
    } catch {
      // Silent
    }
  }

  const deleteCoverLetter = async (id: string) => {
    try {
      await apiClient.deleteCoverLetter(id)
      setExistingCoverLetters(prev => prev.filter(cl => cl.id !== id))
      if (activeCoverLetterId === id) {
        setActiveCoverLetterId(null)
        editorRef.current?.setValue('')
        setPdfUrl(null)
      }
      toast.success('Cover letter deleted')
    } catch {
      toast.error('Failed to delete')
    }
  }

  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  if (sessionLoading || isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!session) {
    return null // Redirecting to login
  }

  return (
    <div className="content-shell min-h-screen space-y-6 pb-12">
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Cover Letter</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">
            AI Cover Letter Generator
          </h1>
          <p className="mt-1 text-sm text-fg-2">
            Generate a tailored cover letter for &quot;{resume?.title}&quot; — matching your resume&apos;s style.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href={`/workspace/${resumeId}/edit`}
            className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2"
          >
            Back to Editor
          </Link>
          <span className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-accent-strong">
            <Mail size={10} className="mr-1 inline" />
            Cover Letter
          </span>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        {/* Left sidebar — configuration */}
        <aside className="space-y-6">
          {/* Job Description */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                Job Description
              </h2>
              <span className="text-[10px] text-fg-3">required</span>
            </div>
            <textarea
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              placeholder="Paste the job description to tailor the cover letter to a specific role..."
              disabled={isProcessing}
              className="scrollbar-subtle mt-3 h-40 w-full resize-none rounded-[var(--radius-lg)] border border-line bg-bg p-4 text-sm text-fg outline-none transition focus:border-accent"
            />
            <p className="mt-1 text-right text-[10px] text-fg-3">
              {jobDescription.length.toLocaleString()} chars
            </p>
          </section>

          {/* Company & Role */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
              Details <span className="text-fg-3 font-normal">(optional)</span>
            </h2>
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="Company name"
              disabled={isProcessing}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            />
            <input
              type="text"
              value={roleTitle}
              onChange={(e) => setRoleTitle(e.target.value)}
              placeholder="Role title"
              disabled={isProcessing}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            />
          </section>

          {/* Tone */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
              Tone
            </h2>
            <div className="flex gap-2">
              {TONE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setTone(opt.value)}
                  disabled={isProcessing}
                  title={opt.desc}
                  className={`flex-1 rounded-[var(--radius-md)] border px-3 py-2 text-xs font-medium transition ${
                    tone === opt.value
                      ? 'border-accent bg-accent-soft text-accent-strong'
                      : 'border-line text-fg-3 hover:text-fg-2'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </section>

          {/* Length */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
              Length
            </h2>
            <div className="flex gap-2">
              {LENGTH_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setLengthPref(opt.value)}
                  disabled={isProcessing}
                  title={opt.desc}
                  className={`flex-1 rounded-[var(--radius-md)] border px-3 py-2 text-xs font-medium transition ${
                    lengthPref === opt.value
                      ? 'border-accent bg-accent-soft text-accent-strong'
                      : 'border-line text-fg-3 hover:text-fg-2'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </section>

          {/* Generate Button */}
          <button
            onClick={runGeneration}
            disabled={isProcessing || isSubmitting || !jobDescription.trim()}
            className="w-full rounded-[var(--radius-md)] bg-accent py-3 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isProcessing || isSubmitting ? 'Generating...' : 'Generate Cover Letter'}
          </button>

          {/* Pipeline Status */}
          <AnimatePresence>
            {activeJobId && (stream.status === 'queued' || stream.status === 'processing') && (
              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
              >
                <div className="mb-4 flex items-start justify-between gap-3">
                  <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                    Generation Status
                  </h2>
                  <span className="font-mono text-[10px] text-fg-3">
                    {activeJobId.slice(0, 8)}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${stream.percent}%` }}
                  />
                </div>
                <p className="mt-3 text-sm capitalize text-fg">
                  {stream.stage || 'Initializing'}
                </p>
                <p className="mt-1 text-xs text-fg-3">
                  {stream.message || 'Connecting to workers...'}
                </p>
              </motion.section>
            )}
          </AnimatePresence>

          {/* Live Logs */}
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
              Live Logs
            </h2>
            <div className="mt-4 h-40 overflow-hidden rounded-[var(--radius-md)] bg-bg">
              <LogViewer
                lines={stream.logLines}
                maxHeight="100%"
                className="h-full text-[10px]"
              />
            </div>
          </section>

          {/* Existing Cover Letters */}
          {existingCoverLetters.length > 0 && (
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                Previous Cover Letters ({existingCoverLetters.length})
              </h2>
              <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-subtle">
                {existingCoverLetters.map((cl) => (
                  <div
                    key={cl.id}
                    className={`flex items-center justify-between rounded-[var(--radius-md)] border p-3 transition ${
                      activeCoverLetterId === cl.id
                        ? 'border-accent bg-accent-soft'
                        : 'border-line hover:border-line-2'
                    }`}
                  >
                    <button
                      onClick={() => loadCoverLetter(cl)}
                      className="flex-1 text-left"
                    >
                      <p className="text-xs font-medium text-fg truncate">
                        {cl.company_name || cl.role_title || 'Cover Letter'}
                      </p>
                      <p className="text-[10px] text-fg-3">
                        {new Date(cl.created_at).toLocaleDateString()}
                      </p>
                    </button>
                    <button
                      onClick={() => deleteCoverLetter(cl.id)}
                      className="ml-2 text-[10px] text-fg-3 hover:text-err transition"
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </aside>

        {/* Right main — editor + preview */}
        <main className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-2">
            {/* LaTeX Editor */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-[620px] flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between border-b border-line bg-surface-2 px-4">
                <div className="flex items-center gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                    <FileText size={12} className="mr-1 inline" />
                    Cover Letter LaTeX
                  </p>
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
                </div>
                <div className="flex items-center gap-2">
                  {hasUnsavedEdits && activeCoverLetterId && (
                    <button
                      onClick={saveChanges}
                      className="text-xs font-semibold text-accent-strong transition hover:text-fg"
                    >
                      Save Changes
                    </button>
                  )}
                  <button
                    onClick={compileCurrentContent}
                    disabled={isProcessing || isSubmitting}
                    className="text-xs font-semibold text-fg-2 transition hover:text-fg disabled:opacity-50"
                  >
                    Compile PDF
                  </button>
                </div>
              </div>
              <div className="min-h-0 flex-1 bg-bg">
                <LaTeXEditor
                  ref={editorRef}
                  value=""
                  onChange={() => setHasUnsavedEdits(true)}
                  readOnly={isProcessing}
                  onAutoCompile={autoCompile && !isProcessing ? handleAutoCompile : undefined}
                  hideEmptyAction
                />
              </div>
            </section>

            {/* PDF Preview */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-[620px] flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between border-b border-line bg-surface-2 px-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                  Output Preview
                </p>
                {pdfUrl && (
                  <a
                    href={pdfUrl}
                    download="cover_letter.pdf"
                    className="text-xs font-semibold text-fg-2 transition hover:text-fg"
                  >
                    Download PDF
                  </a>
                )}
              </div>
              <div className="min-h-0 flex-1 bg-bg">
                <PDFPreview
                  pdfUrl={pdfUrl}
                  isLoading={isProcessing && stream.percent > 40}
                />
              </div>
            </section>
          </div>

          {/* Completion actions */}
          <AnimatePresence>
            {stream.status === 'completed' && activeCoverLetterId && (
              <motion.section
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-[var(--radius-lg)] border border-line bg-surface p-6"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold text-fg">
                      Cover Letter Ready
                    </h2>
                    <p className="text-sm text-fg-2">
                      {stream.tokensUsed ? `${stream.tokensUsed} tokens` : ''}
                      {stream.optimizationTime
                        ? ` in ${stream.optimizationTime.toFixed(1)}s`
                        : ''}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={saveChanges}
                      className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2"
                    >
                      Save to Resume
                    </button>
                    <button
                      className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110"
                      onClick={async () => {
                        if (!stream.pdfJobId) return
                        try {
                          const blob = await apiClient.downloadPdf(stream.pdfJobId)
                          const url = URL.createObjectURL(blob)
                          const a = document.createElement('a')
                          a.href = url
                          a.download = 'cover_letter.pdf'
                          a.click()
                          URL.revokeObjectURL(url)
                        } catch {
                          toast.error('Failed to download PDF')
                        }
                      }}
                    >
                      Download PDF
                    </button>
                  </div>
                </div>
              </motion.section>
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}
