'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import { FileText, Mail, Zap } from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type CoverLetterResponse,
  type CoverLetterTone,
  type CoverLetterLength,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import SessionLoadError from '@/components/SessionLoadError'
import { useJobStream } from '@/hooks/useJobStream'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import CapabilityGate from '@/components/CapabilityGate'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import ModeToggle from '@/components/theme/ModeToggle'
import ContrastToggle from '@/components/theme/ContrastToggle'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import LoadingSpinner from '@/components/LoadingSpinner'
import CoverLetterSignaturePanel from '@/components/CoverLetterSignaturePanel'
import { downloadBlob } from '@/lib/download'

const TONE_OPTIONS: { value: CoverLetterTone; label: string; desc: string }[] = [
  { value: 'formal', label: 'Formal', desc: 'Professional and polished' },
  { value: 'conversational', label: 'Conversational', desc: 'Warm and approachable' },
  { value: 'enthusiastic', label: 'Enthusiastic', desc: 'Energetic and passionate' },
]

// Fall back through company/role -> a job-description snippet -> a stable
// ordinal, so entries created without a company/role stay distinguishable
// instead of collapsing to identical "Cover Letter" rows.
function getCoverLetterLabel(cl: CoverLetterResponse, blankIndex: number): string {
  if (cl.company_name || cl.role_title) {
    return [cl.company_name, cl.role_title].filter(Boolean).join(' — ')
  }
  if (cl.job_description) {
    const snippet = cl.job_description.trim().slice(0, 48)
    return snippet.length < cl.job_description.trim().length ? `${snippet}…` : snippet
  }
  return `Cover Letter #${blankIndex}`
}

const LENGTH_OPTIONS: { value: CoverLetterLength; label: string; desc: string }[] = [
  { value: '3_paragraphs', label: '3 Paragraphs', desc: 'Concise and focused' },
  { value: '4_paragraphs', label: '4 Paragraphs', desc: 'More detail' },
  { value: 'detailed', label: 'Detailed', desc: 'Comprehensive (5+)' },
]

export default function CoverLetterPage() {
  const { can } = useEntitlements()
  const canRef = useRef(can)
  canRef.current = can
  const params = useParams()
  const searchParams = useSearchParams()
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()
  const resumeId = params.resumeId as string
  const requestedCoverLetterId = searchParams.get('cl')

  const [resume, setResume] = useState<{ title: string; latex_content: string } | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
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
  const [editorContent, setEditorContent] = useState('')

  // Unsaved-changes guard: don't silently lose cover-letter edits on reload/nav.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => { if (hasUnsavedEdits) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [hasUnsavedEdits])
  const confirmDiscardIfDirty = useCallback(() => {
    if (!hasUnsavedEdits) return true
    return window.confirm('You have unsaved cover-letter changes that will be lost. Leave without saving?')
  }, [hasUnsavedEdits])
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const activeJobIdRef = useRef<string | null>(null)
  const activeCoverLetterIdRef = useRef<string | null>(null)
  const resumeIdRef = useRef(resumeId)
  const sessionUserId = session?.user?.id ?? null
  const sessionUserIdRef = useRef<string | null>(sessionUserId)
  const requestedCoverLetterIdRef = useRef<string | null>(requestedCoverLetterId)
  const mountedRef = useRef(false)
  const generationJobIdRef = useRef<string | null>(null)
  const generationCompileStartedRef = useRef<string | null>(null)
  const completionTrackedJobIdRef = useRef<string | null>(null)
  const ownerKey = JSON.stringify([resumeId, sessionUserId, requestedCoverLetterId])
  const ownerKeyRef = useRef(ownerKey)
  const ownerContextVersionRef = useRef(0)
  const invalidatedOwnerKeyRef = useRef<string | null>(null)
  const revokePdfPreview = useCallback(() => {
    if (pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current)
      pdfUrlRef.current = null
    }
    setPdfUrl(null)
  }, [])
  activeJobIdRef.current = activeJobId
  activeCoverLetterIdRef.current = activeCoverLetterId
  resumeIdRef.current = resumeId
  sessionUserIdRef.current = sessionUserId
  requestedCoverLetterIdRef.current = requestedCoverLetterId
  // Keep the old stream detached for the render/effect boundary where the
  // route or authenticated owner changes. Clearing only in an effect briefly
  // exposes the previous completed job to the new owner and can autocompile
  // its LaTeX under the new resume.
  if (ownerKeyRef.current !== ownerKey) {
    ownerKeyRef.current = ownerKey
    ownerContextVersionRef.current += 1
    invalidatedOwnerKeyRef.current = ownerKey
    activeJobIdRef.current = null
    activeCoverLetterIdRef.current = null
    generationJobIdRef.current = null
    generationCompileStartedRef.current = null
    completionTrackedJobIdRef.current = null
  }
  const ownerContextVersion = ownerContextVersionRef.current
  const streamJobId = invalidatedOwnerKeyRef.current === ownerKey ? null : activeJobId
  const { state: stream } = useJobStream(streamJobId)
  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  const isCurrentPage = useCallback((
    expectedResumeId: string,
    expectedUserId: string | null,
    expectedCoverLetterId?: string | null,
  ) => (
    mountedRef.current &&
    ownerContextVersionRef.current === ownerContextVersion &&
    resumeIdRef.current === expectedResumeId &&
    sessionUserIdRef.current === expectedUserId &&
    requestedCoverLetterIdRef.current === requestedCoverLetterId &&
    (expectedCoverLetterId === undefined || activeCoverLetterIdRef.current === expectedCoverLetterId)
  ), [requestedCoverLetterId, ownerContextVersion])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    if (invalidatedOwnerKeyRef.current !== ownerKey) return
    invalidatedOwnerKeyRef.current = null
    revokePdfPreview()
    setResume(null)
    setActiveJobId(null)
    setActiveCoverLetterId(null)
    setPdfUrl(null)
    setExistingCoverLetters([])
    setEditorContent('')
    editorRef.current?.setValue('')
    setJobDescription('')
    setCompanyName('')
    setRoleTitle('')
    setHasUnsavedEdits(false)
    setIsSubmitting(false)
  }, [ownerKey, revokePdfPreview])

  // Load resume + existing cover letters
  useEffect(() => {
    if (sessionLoading) return
    if (!session) {
      setIsLoading(false)
      return
    }
    let cancelled = false
    const fetchData = async () => {
      setIsLoading(true)
      setLoadError(null)
      try {
        const [data, cls] = await Promise.all([
          apiClient.getResume(resumeId),
          apiClient.getResumeCoverLetters(resumeId),
        ])
        if (cancelled) return
        setResume(data)
        setExistingCoverLetters(cls)

        // Open the specific cover letter requested via ?cl=<id>, otherwise the most recent one
        const requested = requestedCoverLetterId
          ? cls.find((c) => c.id === requestedCoverLetterId)
          : undefined
        if (requestedCoverLetterId && !requested) {
          setLoadError('The requested cover letter was not found for this resume.')
          return
        }
        const initial = requested ?? (cls.length > 0 ? cls[0] : undefined)
        if (initial) {
          setActiveCoverLetterId(initial.id)
          setJobDescription(initial.job_description || '')
          setCompanyName(initial.company_name || '')
          setRoleTitle(initial.role_title || '')
          setTone(initial.tone as CoverLetterTone)
          setLengthPref(initial.length_preference as CoverLetterLength)
          if (initial.latex_content) {
            editorRef.current?.setValue(initial.latex_content)
            setEditorContent(initial.latex_content)
            // Auto-compile the existing cover letter
            try {
              const r = await apiClient.compileLatex({ latex_content: initial.latex_content })
              if (!cancelled && r.success && r.job_id) setActiveJobId(r.job_id)
            } catch {
              // Silent
            }
          }
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : 'Failed to load cover-letter workspace')
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void fetchData()
    return () => { cancelled = true }
  }, [loadAttempt, resumeId, session, sessionLoading, requestedCoverLetterId])

  // Stream LLM tokens into editor
  useEffect(() => {
    if (!stream.streamingLatex || !editorRef.current) return
    editorRef.current.setValue(stream.streamingLatex)
    setEditorContent(stream.streamingLatex)
  }, [stream.streamingLatex])

  // Auto-compile after LLM generation completes (worker emits pdf_job_id: null)
  // Set before the compile request starts. This is deliberately separate from
  // activeJobId: a REST replay and a late WS completion can both re-run the
  // completed effect while the compile request is still in flight.
  useEffect(() => {
    if (stream.status !== 'completed') return
    const completedJobId = activeJobId
    const completedResumeId = resumeId
    const completedCoverLetterId = activeCoverLetterId
    const completedUserId = sessionUserId
    const completedRequestedCoverLetterId = requestedCoverLetterId
    const isCurrentRoute = () => (
      mountedRef.current &&
      ownerContextVersionRef.current === ownerContextVersion &&
      resumeIdRef.current === completedResumeId &&
      activeCoverLetterIdRef.current === completedCoverLetterId &&
      sessionUserIdRef.current === completedUserId &&
      requestedCoverLetterIdRef.current === completedRequestedCoverLetterId
    )
    const isCurrentRun = () => (
      isCurrentRoute() &&
      activeJobIdRef.current === completedJobId &&
      generationJobIdRef.current === completedJobId
    )

    // If pdfJobId is set and different from the generation job, it's a compile job — fetch PDF
    if (stream.pdfJobId && stream.pdfJobId !== generationJobIdRef.current) {
      const pdfJobId = stream.pdfJobId
      const fetchPdf = async () => {
        try {
          const blob = await apiClient.downloadPdf(pdfJobId)
          if (!isCurrentRoute() || activeJobIdRef.current !== completedJobId) return
          const nextUrl = URL.createObjectURL(blob)
          if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
          pdfUrlRef.current = nextUrl
          setPdfUrl(nextUrl)
        } catch {
          if (isCurrentRoute() && activeJobIdRef.current === completedJobId) {
            toast.error('Failed to load PDF')
          }
        }
      }
      void fetchPdf()
    }
    // Generation just completed (no real pdf_job_id) — auto-compile the generated LaTeX
    if (
      activeJobId &&
      activeJobId === generationJobIdRef.current &&
      generationCompileStartedRef.current !== activeJobId
    ) {
      const content = editorRef.current?.getValue()
      if (content && content.length > 50) {
        const generationJobId = activeJobId
        generationCompileStartedRef.current = generationJobId
        void apiClient.compileLatex({ latex_content: content }).then((r) => {
          if (isCurrentRun() && r.success && r.job_id) {
            setActiveJobId(r.job_id)
          }
        }).catch(() => {
          // Silent — user can manually compile
        })
      }
      // Re-fetch cover letter from DB to get saved latex_content
      if (activeCoverLetterId) {
        const generationJobId = activeJobId
        void apiClient.getCoverLetter(activeCoverLetterId).then((cl) => {
          if (!isCurrentRoute() || generationJobIdRef.current !== generationJobId) return
          setExistingCoverLetters((prev) =>
            prev.map((item) => (item.id === cl.id ? cl : item))
          )
        }).catch(() => {})
      }
    }

    // Track analytics
    if (activeJobId && completionTrackedJobIdRef.current !== activeJobId) {
      completionTrackedJobIdRef.current = activeJobId
      apiClient.trackCompilation(activeJobId, 'completed')
      apiClient.trackFeatureUsage('cover_letter_generation')
    }
  }, [stream.status, stream.pdfJobId, stream.streamingLatex, activeJobId, activeCoverLetterId, resumeId, sessionUserId, requestedCoverLetterId, ownerContextVersion])

  // Track failed jobs
  useEffect(() => {
    if (stream.status === 'failed' && activeJobId) {
      apiClient.trackCompilation(activeJobId, 'failed')
      toast.error(stream.error || 'Cover letter generation failed. Please try again.')
    }
  }, [stream.status, activeJobId, stream.error])

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
    if (!canRef.current('e01')) return
    if (!jobDescription.trim()) {
      toast.error('Please provide a job description')
      return
    }
    setIsSubmitting(true)
    revokePdfPreview()
    setHasUnsavedEdits(false)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestCoverLetterId = activeCoverLetterId

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
      if (!isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) return

      generationJobIdRef.current = response.job_id
      generationCompileStartedRef.current = null
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
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) {
        toast.error(error instanceof Error ? error.message : 'Generation failed')
      }
    } finally {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) setIsSubmitting(false)
    }
  }

  const compileCurrentContent = async () => {
    if (isProcessing || isSubmitting) return
    const content = editorRef.current?.getValue()
    if (!content || content.length < 50) {
      toast.error('No content to compile')
      return
    }
    setIsSubmitting(true)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestCoverLetterId = activeCoverLetterId
    try {
      const response = await apiClient.compileLatex({ latex_content: content })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      if (!isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) return
      editorRef.current?.markAutoCompileCompiled?.(content)
      setActiveJobId(response.job_id)
    } catch {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) toast.error('Compilation failed')
    } finally {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) setIsSubmitting(false)
    }
  }

  const saveChanges = async () => {
    if (!activeCoverLetterId) return
    const content = editorRef.current?.getValue()
    if (!content) return
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestCoverLetterId = activeCoverLetterId
    try {
      await apiClient.updateCoverLetter(requestCoverLetterId, content)
      if (!isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) return
      setHasUnsavedEdits(false)
      toast.success('Cover letter saved')
    } catch {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) toast.error('Failed to save')
    }
  }

  const handleAutoCompile = useCallback(async (content: string) => {
    if (!canRef.current('c06')) return
    if (isProcessing || isSubmitting) return
    setIsSubmitting(true)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestCoverLetterId = activeCoverLetterId
    try {
      const response = await apiClient.compileLatex({ latex_content: content })
      if (!response.success || !response.job_id) throw new Error(response.message || 'Failed')
      if (!isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) return
      editorRef.current?.markAutoCompileCompiled?.(content)
      setActiveJobId(response.job_id)
    } catch {
      // Silent
    } finally {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) setIsSubmitting(false)
    }
  }, [activeCoverLetterId, isCurrentPage, isProcessing, isSubmitting, resumeId, sessionUserId])

  const loadCoverLetter = async (cl: CoverLetterResponse) => {
    // Detach the old generation before selecting another letter, including
    // empty letters. Its stream must not refill the newly cleared editor.
    activeJobIdRef.current = null
    generationJobIdRef.current = null
    generationCompileStartedRef.current = null
    completionTrackedJobIdRef.current = null
    setActiveJobId(null)
    setActiveCoverLetterId(cl.id)
    setJobDescription(cl.job_description || '')
    setCompanyName(cl.company_name || '')
    setRoleTitle(cl.role_title || '')
    setTone(cl.tone as CoverLetterTone)
    setLengthPref(cl.length_preference as CoverLetterLength)
    setHasUnsavedEdits(false)
    revokePdfPreview()
    if (!cl.latex_content) {
      editorRef.current?.setValue('')
      setEditorContent('')
      return
    }
    editorRef.current?.setValue(cl.latex_content)
    setEditorContent(cl.latex_content)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    // Compile loaded cover letter
    try {
      const r = await apiClient.compileLatex({ latex_content: cl.latex_content })
      if (isCurrentPage(requestResumeId, requestUserId, cl.id) && r.success && r.job_id) setActiveJobId(r.job_id)
    } catch {
      // Silent
    }
  }

  const deleteCoverLetter = async (id: string) => {
    setConfirmDeleteId(null)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestActiveCoverLetterId = activeCoverLetterId
    try {
      await apiClient.deleteCoverLetter(id)
      if (!isCurrentPage(requestResumeId, requestUserId)) return
      setExistingCoverLetters(prev => prev.filter(cl => cl.id !== id))
      if (requestActiveCoverLetterId === id && activeCoverLetterIdRef.current === id) {
        activeJobIdRef.current = null
        generationJobIdRef.current = null
        generationCompileStartedRef.current = null
        completionTrackedJobIdRef.current = null
        setActiveJobId(null)
        setActiveCoverLetterId(null)
        editorRef.current?.setValue('')
        setEditorContent('')
        revokePdfPreview()
      }
      toast.success('Cover letter deleted')
    } catch {
      if (isCurrentPage(requestResumeId, requestUserId)) toast.error('Failed to delete')
    }
  }

  const saveSignature = async (nextLatex: string): Promise<boolean> => {
    if (!activeCoverLetterId) throw new Error('Generate or open a cover letter before adding a signature.')
    editorRef.current?.setValue(nextLatex)
    setEditorContent(nextLatex)
    setHasUnsavedEdits(true)
    const requestResumeId = resumeId
    const requestUserId = sessionUserId
    const requestCoverLetterId = activeCoverLetterId
    let saved: CoverLetterResponse
    try {
      saved = await apiClient.updateCoverLetter(requestCoverLetterId, nextLatex)
    } catch {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) toast.error('Failed to save signature')
      return false
    }
    if (!isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) return false
    setExistingCoverLetters((previous) => previous.map((item) => item.id === saved.id ? saved : item))
    setHasUnsavedEdits(false)
    try {
      const compiled = await apiClient.compileLatex({ latex_content: nextLatex })
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId) && compiled.success && compiled.job_id) setActiveJobId(compiled.job_id)
    } catch {
      if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) {
        toast.warning('Signature saved; compile the PDF to refresh the preview.')
      }
    }
    // The compile response can arrive after another route/owner/letter was
    // selected even though persistence itself succeeded earlier.
    return isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)
  }

  if (sessionLoading || isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (sessionError && !session) {
    return <SessionLoadError area="Cover-letter workspace" />
  }

  if (loadError) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center px-6">
        <div role="alert" className="max-w-md rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-6 text-center">
          <h1 className="text-lg font-semibold text-fg">Cover-letter workspace could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-2">{loadError}</p>
          <div className="mt-5 flex justify-center gap-2">
            <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2">Back to workspace</Link>
            <button type="button" onClick={() => setLoadAttempt(value => value + 1)} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg">Retry</button>
          </div>
        </div>
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
        <div className="flex items-center gap-2">
          <ContrastToggle />
          <ModeToggle />
          <Link
            href={`/workspace/${resumeId}/edit`}
            onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }}
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
                  type="button"
                  onClick={() => setTone(opt.value)}
                  disabled={isProcessing}
                  aria-pressed={tone === opt.value}
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
                  type="button"
                  onClick={() => setLengthPref(opt.value)}
                  disabled={isProcessing}
                  aria-pressed={lengthPref === opt.value}
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

          {/* Generation is optional; existing letters and source recovery stay available. */}
          {!can('e01') && <p role="status" className="text-xs text-fg-3">Cover-letter generation is unavailable for your current plan or feature settings. Existing letters remain available.</p>}
          <CapabilityGate feature="e01"><button
            onClick={runGeneration}
            disabled={!can('e01') || isProcessing || isSubmitting || !jobDescription.trim()}
            aria-description={!can('e01') ? 'Cover-letter generation is unavailable for your current plan or feature settings.' : undefined}
            className="w-full rounded-[var(--radius-md)] bg-accent py-3 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isProcessing || isSubmitting ? 'Generating...' : 'Generate Cover Letter'}
          </button></CapabilityGate>

          <CoverLetterSignaturePanel
            latex={editorContent}
            disabled={isProcessing || !activeCoverLetterId || !editorContent}
            onApply={saveSignature}
          />

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
            {activeJobId && stream.status === 'failed' && (
              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="rounded-[var(--radius-lg)] border border-err/30 bg-err/10 p-5"
              >
                <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-err">
                  Generation Failed
                </h2>
                <p className="mt-2 text-sm text-fg">
                  {stream.error || 'Something went wrong. Please try again.'}
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
                {(() => {
                  let blankCount = 0
                  return existingCoverLetters.map((cl) => {
                    const isBlank = !cl.company_name && !cl.role_title && !cl.job_description
                    if (isBlank) blankCount += 1
                    const label = getCoverLetterLabel(cl, blankCount)
                    return (
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
                      aria-pressed={activeCoverLetterId === cl.id}
                      className="flex-1 text-left"
                    >
                      <p className="text-xs font-medium text-fg truncate" title={label}>
                        {label}
                      </p>
                      <p className="text-[10px] text-fg-3">
                        {new Date(cl.created_at).toLocaleDateString()} {new Date(cl.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </button>
                    {confirmDeleteId === cl.id ? (
                      <div className="ml-2 flex shrink-0 items-center gap-1.5">
                        <button
                          onClick={() => deleteCoverLetter(cl.id)}
                          aria-label={`Confirm delete cover letter ${label}`}
                          className="text-[10px] font-semibold text-err transition hover:brightness-110"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="text-[10px] text-fg-3 transition hover:text-fg-2"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(cl.id)}
                        className="ml-2 shrink-0 text-[10px] text-fg-3 hover:text-err transition"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                    )
                  })
                })()}
              </div>
            </section>
          )}
        </aside>

        {/* Right main — editor + preview */}
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-2">
            {/* LaTeX Editor */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface flex h-[620px] flex-col overflow-hidden">
              <div className="flex h-11 items-center justify-between border-b border-line bg-surface-2 px-4">
                <div className="flex items-center gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">
                    <FileText size={12} className="mr-1 inline" />
                    Cover Letter LaTeX
                  </p>
                  <CapabilityGate feature="c06"><button
                    onClick={toggleAutoCompile}
                    title="Auto-compile on change (5s quiet period; 10s minimum interval)"
                    aria-label="Auto-compile on change"
                    aria-pressed={autoCompile}
                    className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium transition ${
                      autoCompile
                        ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
                        : 'text-fg-3 hover:text-fg-2'
                    }`}
                  >
                    <Zap size={10} />
                    Auto
                  </button></CapabilityGate>
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
                  onChange={(value) => {
                    setEditorContent(value)
                    setHasUnsavedEdits(true)
                  }}
                  readOnly={isProcessing}
                  onCompile={compileCurrentContent}
                  onAutoCompile={handleAutoCompile}
                  autoCompileEnabled={can('c06') && autoCompile}
                  autoCompileBusy={isProcessing || isSubmitting}
                  autoCompileDocumentKey={`${sessionUserId ?? 'anonymous'}:${resumeId}:${activeCoverLetterId ?? 'none'}`}
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
                      Save Cover Letter
                    </button>
                    <button
                      className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110"
                      onClick={async () => {
                        if (!stream.pdfJobId) return
                        try {
                          const blob = await apiClient.downloadPdf(stream.pdfJobId)
                          downloadBlob(blob, 'cover_letter.pdf')
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
        </div>
      </div>
    </div>
  )
}
