/**
 * React hooks for API operations
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { 
  apiClient, 
  CompilationResponse, 
  OptimizationRequest,
  OptimizationResponse,
  OptimizeAndCompileResponse,
  ApiError, 
  isApiError 
} from '@/lib/api'
import { useNotifications } from '@/components/NotificationProvider'

export interface UseCompilationResult {
  compile: (latexContent: string) => Promise<CompilationResponse | null>
  compileFile: (file: File) => Promise<CompilationResponse | null>
  isLoading: boolean
  error: string | null
  result: CompilationResponse | null
  cancel: () => void
}

export function useCompilation(): UseCompilationResult {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CompilationResponse | null>(null)
  const { addNotification } = useNotifications()
  const startTimeRef = useRef<number>(0)

  const handleError = useCallback((err: unknown) => {
    const errorMessage = isApiError(err) ? err.detail : 
                        err instanceof Error ? err.message : 
                        'An unexpected error occurred'
    setError(errorMessage)
    addNotification({
      type: 'error',
      title: 'Compilation Failed',
      message: errorMessage,
    })
    return null
  }, [addNotification])

  const compile = useCallback(async (latexContent: string): Promise<CompilationResponse | null> => {
    if (!latexContent.trim()) {
      const errorMsg = 'LaTeX content cannot be empty'
      setError(errorMsg)
      addNotification({
        type: 'error',
        title: 'Invalid Input',
        message: errorMsg,
      })
      return null
    }

    setIsLoading(true)
    setError(null)
    setResult(null)
    startTimeRef.current = Date.now()

    try {
      const response = await apiClient.compileLatex(latexContent)
      setResult(response)
      
      if (response.success) {
        const duration = ((Date.now() - startTimeRef.current) / 1000).toFixed(1)
        addNotification({
          type: 'success',
          title: 'Compilation Successful',
          message: `PDF generated in ${duration}s (${response.pdf_size} bytes)`,
        })
      } else {
        addNotification({
          type: 'error',
          title: 'Compilation Failed',
          message: response.message,
        })
      }
      
      return response
    } catch (err) {
      return handleError(err)
    } finally {
      setIsLoading(false)
    }
  }, [addNotification, handleError])

  const compileFile = useCallback(async (file: File): Promise<CompilationResponse | null> => {
    if (!file) {
      const errorMsg = 'No file provided'
      setError(errorMsg)
      addNotification({
        type: 'error',
        title: 'Invalid Input',
        message: errorMsg,
      })
      return null
    }

    setIsLoading(true)
    setError(null)
    setResult(null)
    startTimeRef.current = Date.now()

    try {
      const response = await apiClient.compileLatexFile(file)
      setResult(response)
      
      if (response.success) {
        const duration = ((Date.now() - startTimeRef.current) / 1000).toFixed(1)
        addNotification({
          type: 'success',
          title: 'Compilation Successful',
          message: `PDF generated in ${duration}s (${response.pdf_size} bytes)`,
        })
      } else {
        addNotification({
          type: 'error',
          title: 'Compilation Failed',
          message: response.message,
        })
      }
      
      return response
    } catch (err) {
      return handleError(err)
    } finally {
      setIsLoading(false)
    }
  }, [addNotification, handleError])

  const cancel = useCallback(() => {
    apiClient.cancelRequests()
    setIsLoading(false)
    addNotification({
      type: 'info',
      title: 'Compilation Cancelled',
      message: 'The compilation request was cancelled',
    })
  }, [addNotification])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      apiClient.cancelRequests()
    }
  }, [])

  return {
    compile,
    compileFile,
    isLoading,
    error,
    result,
    cancel,
  }
}

export interface UsePdfResult {
  pdfUrl: string | null
  isLoading: boolean
  error: string | null
  loadPdf: (jobId: string) => Promise<void>
  downloadPdf: (jobId: string, filename?: string) => Promise<void>
  clearPdf: () => void
}

export function usePdf(): UsePdfResult {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { addNotification } = useNotifications()

  const handleError = useCallback((err: unknown) => {
    const errorMessage = isApiError(err) ? err.detail : 
                        err instanceof Error ? err.message : 
                        'Failed to load PDF'
    setError(errorMessage)
    addNotification({
      type: 'error',
      title: 'PDF Error',
      message: errorMessage,
    })
  }, [addNotification])

  const loadPdf = useCallback(async (jobId: string) => {
    setIsLoading(true)
    setError(null)

    try {
      const blobUrl = await apiClient.getPdfBlobUrl(jobId)
      setPdfUrl(blobUrl)
    } catch (err) {
      handleError(err)
    } finally {
      setIsLoading(false)
    }
  }, [handleError])

  const downloadPdf = useCallback(async (jobId: string, filename = 'resume.pdf') => {
    try {
      const response = await apiClient.downloadPdf(jobId)
      const blob = await response.blob()
      
      // Create download link
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      addNotification({
        type: 'success',
        title: 'Download Started',
        message: `${filename} is being downloaded`,
      })
    } catch (err) {
      handleError(err)
    }
  }, [addNotification, handleError])

  const clearPdf = useCallback(() => {
    if (pdfUrl) {
      URL.revokeObjectURL(pdfUrl)
      setPdfUrl(null)
    }
    setError(null)
  }, [pdfUrl])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl)
      }
    }
  }, [pdfUrl])

  return {
    pdfUrl,
    isLoading,
    error,
    loadPdf,
    downloadPdf,
    clearPdf,
  }
}

export interface UseHealthCheckResult {
  health: {
    status: string
    version: string
    latex_available: boolean
  } | null
  isLoading: boolean
  error: string | null
  checkHealth: () => Promise<void>
}

export function useHealthCheck(): UseHealthCheckResult {
  const [health, setHealth] = useState<UseHealthCheckResult['health']>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const checkHealth = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await apiClient.health()
      setHealth(response)
    } catch (err) {
      const errorMessage = isApiError(err) ? err.detail : 
                          err instanceof Error ? err.message : 
                          'Failed to check backend health'
      setError(errorMessage)
    } finally {
      setIsLoading(false)
    }
  }, [])

  return {
    health,
    isLoading,
    error,
    checkHealth,
  }
}

export interface UseOptimizationResult {
  optimize: (request: OptimizationRequest) => Promise<OptimizationResponse | null>
  optimizeAndCompile: (request: OptimizationRequest) => Promise<OptimizeAndCompileResponse | null>
  isLoading: boolean
  error: string | null
  result: OptimizationResponse | null
}

export function useOptimization(): UseOptimizationResult {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<OptimizationResponse | null>(null)
  const { addNotification } = useNotifications()
  const startTimeRef = useRef<number>(0)

  const handleError = useCallback((err: unknown) => {
    const errorMessage = isApiError(err) ? err.detail : 
                        err instanceof Error ? err.message : 
                        'An unexpected error occurred during optimization'
    setError(errorMessage)
    addNotification({
      type: 'error',
      title: 'Optimization Failed',
      message: errorMessage,
    })
    return null
  }, [addNotification])

  const optimize = useCallback(async (request: OptimizationRequest): Promise<OptimizationResponse | null> => {
    if (!request.latex_content.trim()) {
      const errorMsg = 'LaTeX content cannot be empty'
      setError(errorMsg)
      addNotification({
        type: 'error',
        title: 'Invalid Input',
        message: errorMsg,
      })
      return null
    }

    if (!request.job_description.trim()) {
      const errorMsg = 'Job description cannot be empty'
      setError(errorMsg)
      addNotification({
        type: 'error',
        title: 'Invalid Input',
        message: errorMsg,
      })
      return null
    }

    setIsLoading(true)
    setError(null)
    setResult(null)
    startTimeRef.current = Date.now()

    try {
      const response = await apiClient.optimizeResume(request)
      setResult(response)
      
      if (response.success) {
        const duration = ((Date.now() - startTimeRef.current) / 1000).toFixed(1)
        const tokensUsed = response.tokens_used || 0
        addNotification({
          type: 'success',
          title: 'Optimization Complete',
          message: `Resume optimized in ${duration}s using ${tokensUsed} tokens`,
        })
      } else {
        addNotification({
          type: 'error',
          title: 'Optimization Failed',
          message: response.error_message || 'Unknown error occurred',
        })
      }
      
      return response
    } catch (err) {
      return handleError(err)
    } finally {
      setIsLoading(false)
    }
  }, [addNotification, handleError])

  const optimizeAndCompile = useCallback(async (request: OptimizationRequest): Promise<OptimizeAndCompileResponse | null> => {
    if (!request.latex_content.trim() || !request.job_description.trim()) {
      const errorMsg = 'Both LaTeX content and job description are required'
      setError(errorMsg)
      addNotification({
        type: 'error',
        title: 'Invalid Input',
        message: errorMsg,
      })
      return null
    }

    setIsLoading(true)
    setError(null)
    setResult(null)
    startTimeRef.current = Date.now()

    try {
      const response = await apiClient.optimizeAndCompile(request)
      
      if (response.optimization) {
        setResult(response.optimization)
      }
      
      if (response.success) {
        const duration = ((Date.now() - startTimeRef.current) / 1000).toFixed(1)
        const tokensUsed = response.optimization.tokens_used || 0
        const pdfSize = response.compilation?.pdf_size || 0
        addNotification({
          type: 'success',
          title: 'Optimization & Compilation Complete',
          message: `Resume optimized and compiled in ${duration}s (${tokensUsed} tokens, ${pdfSize} bytes PDF)`,
        })
      } else {
        const errorMsg = response.optimization.error_message || 
                         response.compilation?.message || 
                         'Optimization or compilation failed'
        addNotification({
          type: 'error',
          title: 'Process Failed',
          message: errorMsg,
        })
      }
      
      return response
    } catch (err) {
      return handleError(err)
    } finally {
      setIsLoading(false)
    }
  }, [addNotification, handleError])

  return {
    optimize,
    optimizeAndCompile,
    isLoading,
    error,
    result,
  }
}
