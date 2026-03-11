'use client'

import { useEffect, useRef, useState } from 'react'
import { useJobStream } from './useJobStream'
import { apiClient } from '@/lib/api-client'

export type ConversionStatus = 'idle' | 'uploading' | 'converting' | 'done' | 'error'

export interface UseFormatConversionReturn {
  status: ConversionStatus
  progress: number
  convertedLatex: string | null
  error: string | null
  startConversion: (file: File) => Promise<string | null>
  reset: () => void
}

// If conversion job doesn't complete within this time, auto-fail
const CONVERSION_TIMEOUT_MS = 90_000

export function useFormatConversion(): UseFormatConversionReturn {
  const [status, setStatus] = useState<ConversionStatus>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [convertedLatex, setConvertedLatex] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { state } = useJobStream(jobId)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  // Watch job stream for completion
  useEffect(() => {
    if (!jobId) return
    if (state.status === 'completed') {
      // Clear timeout — job finished in time
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
      // The latex_content is in the job result — fetch it
      const fetchResult = async () => {
        try {
          const token = apiClient.getAuthToken()
          const result = await fetch(
            `${apiClient.baseUrl}/jobs/${jobId}/result`,
            { headers: token ? { Authorization: `Bearer ${token}` } : {} }
          )
          if (!mountedRef.current) return
          if (result.ok) {
            const data = await result.json()
            const latex = data?.result?.latex_content
            if (latex) {
              setConvertedLatex(latex)
              setStatus('done')
            } else {
              setError('Conversion completed but no LaTeX content returned')
              setStatus('error')
            }
          } else {
            const statusCode = result.status
            let msg = 'Failed to fetch conversion result'
            if (statusCode === 404) msg = 'Conversion result not found — it may have expired'
            else if (statusCode >= 500) msg = 'Server error fetching conversion result'
            setError(msg)
            setStatus('error')
          }
        } catch (err) {
          if (!mountedRef.current) return
          setError(String(err))
          setStatus('error')
        }
      }
      fetchResult()
    } else if (state.status === 'failed') {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
      if (!mountedRef.current) return
      setError(state.error || 'Conversion failed')
      setStatus('error')
    }
  }, [state.status, state.error, jobId])

  async function startConversion(file: File): Promise<string | null> {
    // Cancel any previous timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }

    setStatus('uploading')
    setError(null)
    setConvertedLatex(null)
    setJobId(null)

    try {
      const response = await apiClient.uploadForConversion(file)

      if (!mountedRef.current) return null

      if (!response.success) {
        throw new Error('Upload failed')
      }

      // Direct return (LaTeX passthrough or structured format)
      if (response.is_direct && response.latex_content) {
        setConvertedLatex(response.latex_content)
        setStatus('done')
        return response.latex_content
      }

      // Async conversion job
      if (response.job_id) {
        setJobId(response.job_id)
        setStatus('converting')

        // Start timeout — auto-fail if job hangs
        timeoutRef.current = setTimeout(() => {
          if (!mountedRef.current) return
          setError('Conversion timed out. The server may be busy — please try again.')
          setStatus('error')
          setJobId(null)
        }, CONVERSION_TIMEOUT_MS)

        return null  // Will be set via useEffect when job completes
      }

      throw new Error('Invalid upload response')
    } catch (err: unknown) {
      if (!mountedRef.current) return null
      let message = err instanceof Error ? err.message : String(err)
      // Improve HTTP error messages
      if (message.includes('413')) message = 'File is too large to upload'
      else if (message.includes('415')) message = 'Unsupported file format'
      else if (message.includes('422')) message = 'File could not be parsed — check the file is not corrupted'
      else if (message.includes('500') || message.includes('502') || message.includes('503'))
        message = 'Server error — please try again in a moment'
      setError(message)
      setStatus('error')
      return null
    }
  }

  function reset() {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    setStatus('idle')
    setJobId(null)
    setConvertedLatex(null)
    setError(null)
  }

  return {
    status,
    progress: status === 'converting' ? (state.percent || 0) : status === 'done' ? 100 : 0,
    convertedLatex,
    error,
    startConversion,
    reset,
  }
}
