import type { ResumeEngineDocument } from './resume-engine-types'

export interface PdfImportOriginal {
  filename: string
  mime_type: 'application/pdf'
  size_bytes: number
  sha256: string
  preview_url: string
}

export interface PdfImportReceipt {
  import_id: string
  original: PdfImportOriginal
  extraction: {
    status: 'ready' | 'partial' | 'unavailable'
    fields: Array<{
      field_id: string; node_revision: string; label: string; text: string
      confidence: 'high' | 'medium' | 'low' | 'unknown'; warnings: string[]
    }>
    warnings: string[]
  }
  supported_templates: Array<{ template_id: string; name: string; category: string }>
  expires_at: string | null
}

export interface PdfImportAdaptation {
  resume_id: string
  document: ResumeEngineDocument
  latex_content: string
  original: PdfImportOriginal
}
