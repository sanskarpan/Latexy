'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function ResumeEditPage() {
  const params = useParams()
  const router = useRouter()
  const resumeId = params.resumeId as string

  const [title, setTitle] = useState('')
  const [latexContent, setLatexContent] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)

  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const { state: stream } = useJobStream(activeJobId)

  useEffect(() => {
    const fetchResume = async () => {
      try {
        const data = await apiClient.getResume(resumeId)
        setTitle(data.title)
        setLatexContent(data.latex_content)
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
    if (stream.status === 'completed' || stream.status === 'failed') {
      setLatexContent(stream.streamingLatex)
    }
  }, [stream.streamingLatex, stream.status])

  useEffect(() => {
    const fetchPdf = async () => {
      if (stream.status !== 'completed' || !stream.pdfJobId) {
        if (stream.status === 'queued' || stream.status === 'processing') {
          if (pdfUrlRef.current) {
            URL.revokeObjectURL(pdfUrlRef.current)
            pdfUrlRef.current = null
          }
          setPdfUrl(null)
        }
        return
      }

      try {
        const blob = await apiClient.downloadPdf(stream.pdfJobId)
        const nextUrl = URL.createObjectURL(blob)

        if (pdfUrlRef.current) {
          URL.revokeObjectURL(pdfUrlRef.current)
        }

        pdfUrlRef.current = nextUrl
        setPdfUrl(nextUrl)
      } catch {
        toast.error('Failed to load PDF preview')
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

  const handleSave = async () => {
    const content = editorRef.current?.getValue() || latexContent
    setIsSaving(true)

    try {
      await apiClient.updateResume(resumeId, {
        title,
        latex_content: content,
      })
      setLatexContent(content)
      toast.success('Resume saved')
    } catch {
      toast.error('Failed to save resume')
    } finally {
      setIsSaving(false)
    }
  }

  const runCompile = async () => {
    const currentContent = editorRef.current?.getValue() || latexContent
    if (!currentContent.trim()) {
      toast.error('LaTeX content is required')
      return
    }

    setIsSubmitting(true)
    try {
      const response = await apiClient.compileLatex({
        latex_content: currentContent,
        user_plan: 'pro',
      })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to submit compile job')
      }

      setActiveJobId(response.job_id)
      toast.success('Compilation started')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Submission failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDownload = async () => {
    const downloadId = stream.pdfJobId ?? activeJobId
    if (!downloadId) return

    try {
      const blob = await apiClient.downloadPdf(downloadId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${title.replace(/\s+/g, '_').toLowerCase()}_resume.pdf`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
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
    <div className="flex h-screen flex-col overflow-hidden bg-slate-950">
      <header className="flex h-14 items-center justify-between border-b border-white/10 bg-black/30 px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/workspace" className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:border-white/20 hover:text-white">
            Workspace
          </Link>
          <input
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="min-w-[220px] max-w-[420px] border-none bg-transparent text-sm font-semibold text-white outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:bg-white/10 disabled:opacity-50"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={runCompile}
            disabled={isSubmitting || isProcessing}
            className="rounded-lg bg-orange-300 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-orange-200 disabled:opacity-50"
          >
            {isSubmitting || isProcessing ? 'Running...' : 'Run Compile'}
          </button>
          <Link
            href={`/workspace/${resumeId}/optimize`}
            className="rounded-lg border border-orange-300/20 bg-orange-300/10 px-3 py-1.5 text-xs font-semibold text-orange-200 transition hover:bg-orange-300/20"
          >
            Optimize
          </Link>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        <section className="flex min-h-0 flex-1 flex-col border-r border-white/10">
          <div className="flex h-9 items-center border-b border-white/10 px-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
            LaTeX Source
          </div>
          <div className="min-h-0 flex-1">
            <LaTeXEditor ref={editorRef} value={latexContent} onChange={setLatexContent} />
          </div>
        </section>

        <aside className="flex w-[460px] min-w-[360px] flex-col bg-black/20">
          <section className="flex min-h-0 flex-1 flex-col border-b border-white/10">
            <div className="flex h-9 items-center justify-between border-b border-white/10 px-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
              <span>Live Preview</span>
              {stream.status === 'completed' && (
                <button onClick={handleDownload} className="text-[10px] text-zinc-300 transition hover:text-white">
                  Download PDF
                </button>
              )}
            </div>
            <div className="min-h-0 flex-1 bg-black/35">
              <PDFPreview pdfUrl={pdfUrl} isLoading={isProcessing} onDownload={handleDownload} />
            </div>
          </section>

          <section className="flex h-[220px] min-h-0 flex-col">
            <div className="flex h-9 items-center justify-between border-b border-white/10 px-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
              <span>Compilation Logs</span>
              <span className="capitalize">{stream.status}</span>
            </div>
            <div className="min-h-0 flex-1 p-2">
              <LogViewer lines={stream.logLines} maxHeight="100%" className="h-full text-[10px]" />
            </div>
          </section>
        </aside>
      </main>
    </div>
  )
}
