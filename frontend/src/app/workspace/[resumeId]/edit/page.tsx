'use client'

import { useEffect, useMemo, useState, useRef } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Toaster, toast } from 'sonner'
import { Save, Play, ChevronLeft, Download, FileText, Settings, History } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { useJobStream } from '@/hooks/useJobStream'
import LaTeXEditor, { LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function ResumeEditPage() {
  const params = useParams()
  const router = useRouter()
  const resumeId = params.resumeId as string

  const [title, setTitle] = useState('')
  const [latexContent, setLatexContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  
  const editorRef = useRef<LaTeXEditorRef>(null)
  const { state: stream } = useJobStream(activeJobId)

  // Fetch resume on mount
  useEffect(() => {
    async function fetchResume() {
      try {
        const data = await apiClient.getResume(resumeId)
        setTitle(data.title)
        setLatexContent(data.latex_content)
        editorRef.current?.setValue(data.latex_content)
      } catch (err) {
        toast.error('Failed to load resume')
        router.push('/workspace')
      } finally {
        setLoading(false)
      }
    }
    fetchResume()
  }, [resumeId, router])

  // Stream handler: Direct Monaco mutation
  useEffect(() => {
    if (stream.streamingLatex && editorRef.current) {
      editorRef.current.setValue(stream.streamingLatex)
      
      if (stream.status === 'completed' || stream.status === 'failed') {
        setLatexContent(stream.streamingLatex)
      }
    }
  }, [stream.streamingLatex, stream.status])

  // PDF Fetcher
  useEffect(() => {
    let active = true
    const fetchPdf = async () => {
      if (stream.status === 'completed' && stream.pdfJobId) {
        try {
          const blob = await apiClient.downloadPdf(stream.pdfJobId)
          if (active) {
            const url = URL.createObjectURL(blob)
            setPdfUrl(url)
          }
        } catch (err) {
          console.error('Failed to auto-fetch PDF:', err)
          toast.error('Failed to load PDF preview')
        }
      } else if (stream.status === 'queued' || stream.status === 'processing') {
        setPdfUrl(null)
      }
    }
    fetchPdf()
    return () => {
      active = false
      if (pdfUrl) URL.revokeObjectURL(pdfUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.status, stream.pdfJobId])

  const handleSave = async () => {
    const content = editorRef.current?.getValue() || latexContent
    setIsSaving(true)
    try {
      await apiClient.updateResume(resumeId, { 
        title, 
        latex_content: content 
      })
      setLatexContent(content)
      toast.success('Resume saved successfully')
    } catch (err) {
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
        user_plan: 'pro' // Workspace users are authenticated
      })

      if (!response.success || !response.job_id) {
        throw new Error(response.message || 'Failed to submit job')
      }

      setActiveJobId(response.job_id)
      toast.success('Compilation started...')
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
      const a = document.createElement('a')
      a.href = url
      a.download = `${title.replace(/\s+/g, '_').toLowerCase()}_resume.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
  }

  const isProcessing = stream.status === 'queued' || stream.status === 'processing'

  if (loading) return (
    <div className="flex h-screen items-center justify-center">
      <LoadingSpinner />
    </div>
  )

  return (
    <div className="flex h-screen flex-col bg-slate-950 overflow-hidden">
      <Toaster richColors position="top-right" />
      
      {/* Editor Header */}
      <header className="flex h-14 items-center justify-between border-b border-white/10 bg-slate-900/50 px-4">
        <div className="flex items-center gap-4">
          <Link href="/workspace" className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white transition">
            <ChevronLeft size={20} />
          </Link>
          <div className="h-6 w-px bg-white/10" />
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-orange-300" />
            <input 
              type="text" 
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="bg-transparent text-sm font-medium text-white outline-none focus:text-orange-200 transition min-w-[200px]"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/10 disabled:opacity-50"
          >
            <Save size={14} />
            {isSaving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={runCompile}
            disabled={isSubmitting || isProcessing}
            className="flex items-center gap-2 rounded-lg bg-orange-300 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-orange-200 disabled:opacity-50"
          >
            <Play size={14} fill="currentColor" />
            Run
          </button>
          <div className="h-6 w-px bg-white/10" />
          <Link href={`/workspace/${resumeId}/optimize`} className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white transition">
            <Settings size={18} />
          </Link>
        </div>
      </header>

      {/* Editor Body */}
      <main className="flex flex-1 overflow-hidden">
        {/* Left: Code Editor */}
        <div className="flex-1 border-r border-white/10">
          <LaTeXEditor
            ref={editorRef}
            value={latexContent}
            onChange={setLatexContent}
          />
        </div>

        {/* Right: Preview & Logs */}
        <div className="flex w-[450px] flex-col bg-slate-900/30">
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex h-10 items-center justify-between border-b border-white/10 px-4 bg-black/20">
              <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Live Preview</span>
              {stream.status === 'completed' && (
                <button onClick={handleDownload} className="text-zinc-400 hover:text-orange-200 transition">
                  <Download size={14} />
                </button>
              )}
            </div>
            <div className="flex-1 bg-black/40">
              <PDFPreview 
                pdfUrl={pdfUrl} 
                isLoading={isProcessing}
                onDownload={handleDownload}
              />
            </div>
          </div>

          <div className="h-[200px] border-t border-white/10 flex flex-col overflow-hidden bg-black/20">
            <div className="flex h-8 items-center justify-between px-4 border-b border-white/5">
              <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Compilation Logs</span>
              <div className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${isProcessing ? 'bg-orange-400 animate-pulse' : 'bg-zinc-600'}`} />
                <span className="text-[10px] text-zinc-500 capitalize">{stream.status}</span>
              </div>
            </div>
            <div className="flex-1 overflow-hidden">
              <LogViewer 
                lines={stream.logLines} 
                maxHeight="100%" 
                className="font-mono text-[10px] p-2" 
              />
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
