/**
 * Compatibility layer for useApi.ts and other legacy imports.
 * Re-exports api-client.ts + provides legacy type shapes + maps
 * old method signatures to the new job-submission API.
 *
 * This file fixes:  import { apiClient, ... } from '@/lib/api'
 */

export * from './api-client'
export { apiClient as default } from './api-client'

import { apiClient as _base } from './api-client'

// ------------------------------------------------------------------ //
//  Legacy types expected by useApi.ts                                //
// ------------------------------------------------------------------ //

export interface CompilationResponse {
  success: boolean
  job_id: string
  message: string
  compilation_time?: number
  pdf_size?: number
  log_output?: string
}

export interface OptimizationRequest {
  latex_content: string
  job_description: string
  optimization_level?: string
}

export interface OptimizationResponse {
  success: boolean
  optimized_latex?: string
  original_latex?: string
  changes_made?: Array<{ section: string; change_type: string; reason: string }>
  ats_score?: { overall_score: number; category_scores: Record<string, number> }
  tokens_used?: number
  model_used?: string
  optimization_time?: number
  error_message?: string
}

export interface OptimizeAndCompileResponse {
  success: boolean
  optimization: OptimizationResponse
  compilation?: CompilationResponse
}

export interface ApiError {
  detail: string
  status_code: number
}

export function isApiError(err: unknown): err is ApiError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'detail' in err &&
    typeof (err as Record<string, unknown>).detail === 'string'
  )
}

// ------------------------------------------------------------------ //
//  Extended apiClient with legacy method shapes                      //
// ------------------------------------------------------------------ //

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export const apiClient = {
  ..._base,

  /** Legacy: compile via job submission, returns CompilationResponse shape */
  async compileLatex(latexContent: string): Promise<CompilationResponse> {
    const res = await _base.submitJob({
      job_type: 'latex_compilation',
      latex_content: latexContent,
    })
    return {
      success: res.success,
      job_id: res.job_id,
      message: res.message,
    }
  },

  /** Legacy: compile from File via form upload */
  async compileLatexFile(file: File): Promise<CompilationResponse> {
    const text = await file.text()
    return this.compileLatex(text)
  },

  /** Legacy: optimize via job submission, returns OptimizationResponse shape */
  async optimizeResume(req: OptimizationRequest): Promise<OptimizationResponse> {
    // Submit as async job — caller should use useJobStream to get streaming results
    const res = await _base.submitJob({
      job_type: 'llm_optimization',
      latex_content: req.latex_content,
      job_description: req.job_description,
      optimization_level: (req.optimization_level as 'conservative' | 'balanced' | 'aggressive') ?? 'balanced',
    })
    // Return a pending-style response. Real results come via WebSocket events.
    return {
      success: res.success,
      error_message: res.success ? undefined : res.message,
    }
  },

  /** Legacy: optimize + compile in one shot */
  async optimizeAndCompile(req: OptimizationRequest): Promise<OptimizeAndCompileResponse> {
    const res = await _base.submitJob({
      job_type: 'combined',
      latex_content: req.latex_content,
      job_description: req.job_description,
      optimization_level: (req.optimization_level as 'conservative' | 'balanced' | 'aggressive') ?? 'balanced',
    })
    return {
      success: res.success,
      optimization: {
        success: res.success,
        error_message: res.success ? undefined : res.message,
      },
    }
  },

  /** Returns a blob URL for the PDF (revoke after use) */
  async getPdfBlobUrl(jobId: string): Promise<string> {
    return _base.getPdfBlobUrl(jobId)
  },

  /** Returns a raw Response for the PDF (for blob extraction) */
  async downloadPdf(jobId: string): Promise<Response> {
    const res = await fetch(`${API_BASE}/download/${encodeURIComponent(jobId)}`)
    if (!res.ok) throw new Error(`PDF download failed: HTTP ${res.status}`)
    return res
  },

  /** Health check */
  async health(): Promise<{ status: string; version: string; latex_available: boolean }> {
    return _base.health()
  },
}
