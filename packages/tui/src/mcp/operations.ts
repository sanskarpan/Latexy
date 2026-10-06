import type { ApiClient } from '../lib/api-client.js'

export const MCP_RESUME_PAGE_SIZE = 200

export interface McpResume {
  id: string
  title: string
  latex_content: string
  document_type: string
  tags?: string[] | null
  pinned?: boolean
  archived_at?: string | null
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown> | null
}

export type McpResumeSummary = Omit<McpResume, 'latex_content' | 'metadata'>

interface ResumePage {
  resumes: unknown[]
  total: number
  pages: number
}

export interface McpApi {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  put<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body?: unknown): Promise<T>
}

export interface ListResumeOptions {
  archived?: boolean
  documentType?: string
}

const COMPILE_METADATA_KEYS = [
  'compiler', 'main_file', 'extra_packages', 'latexmk_flags',
  'texlive_version', 'bibtex', 'halt_on_error', 'draft_mode',
] as const

/** Do not forward share tokens, owner ids, or unrelated backend internals to an MCP client. */
function normalizeResume(value: unknown): McpResume {
  if (value == null || typeof value !== 'object') throw new Error('Latexy returned an invalid resume')
  const source = value as Record<string, unknown>
  const rawMetadata = source['metadata']
  const metadata = rawMetadata != null && typeof rawMetadata === 'object'
    ? Object.fromEntries(COMPILE_METADATA_KEYS.flatMap(key =>
        key in rawMetadata ? [[key, (rawMetadata as Record<string, unknown>)[key]]] : []))
    : undefined
  return {
    id: String(source['id'] ?? ''),
    title: String(source['title'] ?? ''),
    latex_content: String(source['latex_content'] ?? ''),
    document_type: String(source['document_type'] ?? 'resume'),
    ...(Array.isArray(source['tags']) ? { tags: source['tags'].map(String) } : {}),
    ...(typeof source['pinned'] === 'boolean' ? { pinned: source['pinned'] } : {}),
    ...(typeof source['archived_at'] === 'string' || source['archived_at'] === null
      ? { archived_at: source['archived_at'] }
      : {}),
    created_at: String(source['created_at'] ?? ''),
    updated_at: String(source['updated_at'] ?? ''),
    ...(metadata && Object.keys(metadata).length > 0 ? { metadata } : {}),
  }
}

function summarizeResume(value: unknown): McpResumeSummary {
  const { latex_content: _latex, metadata: _metadata, ...summary } = normalizeResume(value)
  return summary
}

/** API operations shared by the MCP transport and its contract tests. */
export function createMcpOperations(client: McpApi | ApiClient) {
  const listResumes = async (options: ListResumeOptions = {}): Promise<{
    resumes: McpResumeSummary[]
    total: number
  }> => {
    const query = (page: number): string => {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(MCP_RESUME_PAGE_SIZE),
        archived: String(options.archived ?? false),
      })
      if (options.documentType) params.set('document_type', options.documentType)
      return params.toString()
    }

    const first = await client.get<ResumePage>(`/resumes/?${query(1)}`)
    const pages = Math.max(first.pages ?? 1, Math.ceil(first.total / MCP_RESUME_PAGE_SIZE))
    const resumes = (first.resumes ?? []).map(summarizeResume)
    for (let page = 2; page <= pages; page += 1) {
      const next = await client.get<ResumePage>(`/resumes/?${query(page)}`)
      resumes.push(...(next.resumes ?? []).map(summarizeResume))
    }
    return { resumes, total: first.total ?? resumes.length }
  }

  const readResume = async (resumeId: string): Promise<McpResume> =>
    normalizeResume(await client.get<unknown>(`/resumes/${encodeURIComponent(resumeId)}`))

  const createResume = (input: {
    title: string
    latex_content: string
    document_type?: string
    tags?: string[]
  }): Promise<McpResume> => client.post<unknown>('/resumes/', {
      title: input.title,
      latex_content: input.latex_content,
      document_type: input.document_type ?? 'resume',
      tags: input.tags,
      is_template: false,
    }).then(normalizeResume)

  const updateResume = async (resumeId: string, patch: {
    title?: string
    latex_content?: string
    expected_latex_content?: string
    document_type?: string
    tags?: string[]
  }): Promise<McpResume> => {
    // MCP callers may predate the document CAS contract. Resolve the latest
    // source here and attach it to any full-content write; the server-side
    // row lock still decides whether that baseline remains valid.
    const requestPatch = typeof patch.latex_content === 'string' && patch.expected_latex_content === undefined
      ? {
          ...patch,
          expected_latex_content: (await readResume(resumeId)).latex_content,
        }
      : patch
    return client.put<unknown>(`/resumes/${encodeURIComponent(resumeId)}`, requestPatch).then(normalizeResume)
  }

  const archiveResume = (resumeId: string): Promise<McpResume> =>
    client.patch<unknown>(`/resumes/${encodeURIComponent(resumeId)}/archive`).then(normalizeResume)

  const submitResumeJob = async (
    resumeId: string,
    jobType: 'latex_compilation' | 'ats_scoring',
    extra: Record<string, unknown> = {},
  ): Promise<{ job_id: string; status: 'queued' }> => {
    const resume = await readResume(resumeId)
    const compiler = resume.metadata?.['compiler']
    const submitted = await client.post<{ job_id: string }>('/jobs/submit', {
      job_type: jobType,
      latex_content: resume.latex_content,
      metadata: { resume_id: resumeId, submitted_via: 'mcp' },
      ...(jobType === 'latex_compilation' && typeof compiler === 'string' ? { compiler } : {}),
      ...extra,
    })
    return { job_id: submitted.job_id, status: 'queued' }
  }

  const getJobStatus = async (jobId: string): Promise<Record<string, unknown>> => {
    const id = encodeURIComponent(jobId)
    const state = await client.get<Record<string, unknown>>(`/jobs/${id}/state`)
    if (!['completed', 'failed', 'cancelled'].includes(String(state['status'] ?? ''))) {
      return { job_id: jobId, ...state }
    }
    const jobResult = await client.get<Record<string, unknown>>(`/jobs/${id}/result`)
    return { job_id: jobId, ...state, result: jobResult }
  }

  return {
    listResumes,
    readResume,
    createResume,
    updateResume,
    archiveResume,
    submitResumeJob,
    getJobStatus,
  }
}

export type McpOperations = ReturnType<typeof createMcpOperations>
