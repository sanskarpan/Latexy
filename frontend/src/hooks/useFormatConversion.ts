'use client'

import { useEffect, useState } from 'react'
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

export function useFormatConversion(): UseFormatConversionReturn {
  const [status, setStatus] = useState<ConversionStatus>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [convertedLatex, setConvertedLatex] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { state } = useJobStream(jobId)

  // Watch job stream for completion
  useEffect(() => {
    if (!jobId) return
    if (state.status === 'completed') {
      // The latex_content is in the job result — fetch it
      const fetchResult = async () => {
        try {
          const token = apiClient.getAuthToken()
          const result = await fetch(
            `${apiClient.baseUrl}/jobs/${jobId}/result`,
            { headers: token ? { Authorization: `Bearer ${token}` } : {} }
          )
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
            setError('Failed to fetch conversion result')
            setStatus('error')
          }
        } catch (err) {
          setError(String(err))
          setStatus('error')
        }
      }
      fetchResult()
    } else if (state.status === 'failed') {
      setError(state.error || 'Conversion failed')
      setStatus('error')
    }
  }, [state.status, state.error, jobId])

  async function startConversion(file: File): Promise<string | null> {
    setStatus('uploading')
    setError(null)
    setConvertedLatex(null)
    setJobId(null)

    try {
      const response = await apiClient.uploadForConversion(file)

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
        return null  // Will be set via useEffect when job completes
      }

      throw new Error('Invalid upload response')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      setStatus('error')
      return null
    }
  }

  function reset() {
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
