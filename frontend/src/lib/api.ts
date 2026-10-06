/**
 * API client for Latexy backend services
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export interface CompilationResponse {
  success: boolean
  job_id: string
  message: string
  compilation_time?: number
  pdf_size?: number
  log_output?: string
}

export interface HealthResponse {
  status: string
  version: string
  latex_available: boolean
}

export interface LogsResponse {
  job_id: string
  logs: string
}

export interface OptimizationRequest {
  latex_content: string
  job_description: string
  optimization_level?: 'conservative' | 'balanced' | 'aggressive'
}

export interface KeywordMatch {
  keyword: string
  relevance_score: number
  found_in_resume: boolean
  suggested_context?: string
}

export interface OptimizationChange {
  section: string
  change_type: 'added' | 'modified' | 'removed'
  original_text?: string
  new_text?: string
  reason: string
}

export interface ATSScore {
  overall_score: number
  keyword_score: number
  format_score: number
  content_score: number
  recommendations: string[]
}

export interface OptimizationResponse {
  success: boolean
  optimized_latex?: string
  original_latex: string
  job_description: string
  keywords_found: KeywordMatch[]
  changes_made: OptimizationChange[]
  ats_score?: ATSScore
  optimization_time?: number
  tokens_used?: number
  model_used?: string
  error_message?: string
  warnings: string[]
}

export interface OptimizeAndCompileResponse {
  optimization: OptimizationResponse
  compilation: CompilationResponse | null
  success: boolean
}

export interface ApiError {
  detail: string
  status?: number
}

class ApiClient {
  private baseUrl: string
  private abortController: AbortController | null = null

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl
  }

  /**
   * Cancel any ongoing requests
   */
  cancelRequests() {
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
  }

  /**
   * Make a request with proper error handling
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    // Create new abort controller for this request
    this.abortController = new AbortController()
    
    const url = `${this.baseUrl}${endpoint}`
    
    try {
      const response = await fetch(url, {
        ...options,
        signal: this.abortController.signal,
        headers: {
          'Accept': 'application/json',
          ...options.headers,
        },
      })

      if (!response.ok) {
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        
        try {
          const errorData = await response.json()
          errorMessage = errorData.detail || errorMessage
        } catch {
          // If JSON parsing fails, use the default error message
        }
        
        throw new Error(errorMessage)
      }

      // Handle different content types
      const contentType = response.headers.get('content-type')
      if (contentType?.includes('application/json')) {
        return await response.json()
      } else {
        return response as unknown as T
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Request was cancelled')
      }
      throw error
    } finally {
      this.abortController = null
    }
  }

  /**
   * Check backend health
   */
  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health')
  }

  /**
   * Compile LaTeX content
   */
  async compileLatex(latexContent: string): Promise<CompilationResponse> {
    const formData = new FormData()
    formData.append('latex_content', latexContent)

    return this.request<CompilationResponse>('/compile', {
      method: 'POST',
      body: formData,
    })
  }

  /**
   * Upload and compile LaTeX file
   */
  async compileLatexFile(file: File): Promise<CompilationResponse> {
    const formData = new FormData()
    formData.append('file', file)

    return this.request<CompilationResponse>('/compile', {
      method: 'POST',
      body: formData,
    })
  }

  /**
   * Download compiled PDF
   */
  async downloadPdf(jobId: string): Promise<Response> {
    return this.request<Response>(`/download/${jobId}`, {
      method: 'GET',
    })
  }

  /**
   * Get compilation logs
   */
  async getLogs(jobId: string): Promise<LogsResponse> {
    return this.request<LogsResponse>(`/logs/${jobId}`)
  }

  /**
   * Create a blob URL for PDF preview
   */
  async getPdfBlobUrl(jobId: string): Promise<string> {
    const response = await this.downloadPdf(jobId)
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  }

  /**
   * Optimize resume using LLM
   */
  async optimizeResume(request: OptimizationRequest): Promise<OptimizationResponse> {
    return this.request<OptimizationResponse>('/optimize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
  }

  /**
   * Optimize and compile resume in one step
   */
  async optimizeAndCompile(request: OptimizationRequest): Promise<OptimizeAndCompileResponse> {
    return this.request<OptimizeAndCompileResponse>('/optimize-and-compile', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
  }
}

// Export singleton instance
export const apiClient = new ApiClient()

// Export utility functions
export const createApiError = (message: string, status?: number): ApiError => ({
  detail: message,
  status,
})

export const isApiError = (error: unknown): error is ApiError => {
  return typeof error === 'object' && error !== null && 'detail' in error
}
