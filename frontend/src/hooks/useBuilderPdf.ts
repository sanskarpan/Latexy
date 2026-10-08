'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type BuilderResumeResponse } from '@/lib/api-client'
import { downloadBlob } from '@/lib/download'

type Options = {
  resumeId: string
  prepareResume: () => Promise<BuilderResumeResponse | null>
  isCurrent: () => boolean
}

/** Compile the exact saved builder revision, without opening the source editor. */
export function useBuilderPdf({ resumeId, prepareResume, isCurrent }: Options) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const urlRef = useRef<string | null>(null)
  const mountedRef = useRef(true)
  const cachedRef = useRef<{ version: number | null | undefined; latex: string; blob: Blob } | null>(null)

  const clearPreview = useCallback(() => {
    controllerRef.current?.abort()
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = null
    cachedRef.current = null
    setPdfUrl(null)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      controllerRef.current?.abort()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])

  async function generate(download: boolean) {
    if (controllerRef.current) throw new Error('Your PDF is already being prepared.')
    const controller = new AbortController()
    controllerRef.current = controller
    const current = () => mountedRef.current && !controller.signal.aborted && isCurrent()
    const assertCurrent = () => {
      if (!current()) throw new Error('The resume or signed-in account changed. Please retry.')
    }
    setIsGenerating(true)
    setError(null)
    try {
      assertCurrent()
      const saved = await prepareResume()
      assertCurrent()
      if (!saved || saved.resume.id !== resumeId || !saved.resume.latex_content.trim()) {
        throw new Error('Save your resume before creating the PDF.')
      }
      if (cachedRef.current && cachedRef.current.version === saved.resume.structured_version && cachedRef.current.latex === saved.resume.latex_content) {
        if (download) downloadBlob(cachedRef.current.blob, `${saved.resume.title || 'resume'}.pdf`)
        return
      }
      const submission = await apiClient.compileLatex({
        latex_content: saved.resume.latex_content,
        resume_id: resumeId,
        compiler: saved.resume.metadata?.compiler === 'pdflatex' ? 'pdflatex' : 'lualatex',
      })
      assertCurrent()
      if (!submission.success || !submission.job_id) throw new Error('PDF generation could not be started. Please retry.')
      const deadline = Date.now() + 180_000
      while (Date.now() < deadline) {
        assertCurrent()
        const state = await apiClient.getJobState(submission.job_id)
        assertCurrent()
        if (state.job_id && state.job_id !== submission.job_id) throw new Error('PDF job identity mismatch.')
        if (state.status === 'failed' || state.status === 'cancelled') {
          throw new Error('PDF generation did not finish. Your saved resume is safe; please retry.')
        }
        if (state.status === 'completed') {
          const result = await apiClient.getJobResult(submission.job_id)
          assertCurrent()
          if (!result.success || result.pdf_job_id !== submission.job_id) {
            throw new Error('The PDF output is unavailable. Please retry generation.')
          }
          const blob = await apiClient.downloadPdf(submission.job_id, controller.signal)
          assertCurrent()
          if (urlRef.current) URL.revokeObjectURL(urlRef.current)
          urlRef.current = URL.createObjectURL(blob)
          setPdfUrl(urlRef.current)
          cachedRef.current = { version: saved.resume.structured_version, latex: saved.resume.latex_content, blob }
          if (download) downloadBlob(blob, `${saved.resume.title || 'resume'}.pdf`)
          return
        }
        await new Promise<void>((resolve) => {
          const done = () => {
            clearTimeout(timer)
            controller.signal.removeEventListener('abort', done)
            resolve()
          }
          const timer = setTimeout(done, 2000)
          controller.signal.addEventListener('abort', done, { once: true })
        })
      }
      throw new Error('Your PDF is taking longer than expected. Your resume is saved; please retry.')
    } catch (failure) {
      if (current()) setError(failure instanceof Error ? failure.message : 'PDF generation failed. Please retry.')
      throw failure
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null
      if (mountedRef.current) setIsGenerating(false)
    }
  }

  return { previewPdf: () => generate(false), downloadPdf: () => generate(true), pdfUrl, isGenerating, error, clearPreview }
}
