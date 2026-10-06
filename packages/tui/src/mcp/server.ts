import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { z } from 'zod'

import { ApiError, initApiClient } from '../lib/api-client.js'
import { readConfig } from '../lib/config.js'
import { createMcpOperations } from './operations.js'
import type { McpOperations } from './operations.js'

declare const __LATEXY_VERSION__: string

const documentType = z.enum(['resume', 'presentation', 'academic_cv', 'cover_letter'])
const resumeIdSchema = z.string().uuid().describe('Latexy resume UUID')
const jobIdSchema = z.string().uuid().describe('Latexy job UUID')

function result(value: object) {
  const structuredContent = value as Record<string, unknown>
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(value, null, 2) }],
    structuredContent,
  }
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return `Latexy API ${error.status}: ${error.message}`
  return error instanceof Error ? error.message : String(error)
}

function guarded<T extends Record<string, unknown>>(
  handler: (args: T) => Promise<object>,
) {
  return async (args: T) => {
    try {
      return result(await handler(args))
    } catch (error) {
      return {
        isError: true,
        content: [{ type: 'text' as const, text: messageFor(error) }],
      }
    }
  }
}

export function createLatexyMcpServer(
  operations: McpOperations,
  version = typeof __LATEXY_VERSION__ === 'string' ? __LATEXY_VERSION__ : 'development',
): McpServer {
  const server = new McpServer(
    { name: 'latexy', version },
    {
      instructions: "Read and edit the authenticated user's Latexy documents. Read a resume before updating it.",
    },
  )

  server.registerTool('list_resumes', {
    title: 'List Latexy documents',
    description: 'List every active or archived Latexy document owned by the authenticated user.',
    inputSchema: {
      archived: z.boolean().default(false).describe('List archived documents instead of active documents'),
      document_type: documentType.optional(),
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  }, guarded(async ({ archived, document_type }) => operations.listResumes({
    archived: Boolean(archived),
    ...(typeof document_type === 'string' ? { documentType: document_type } : {}),
  })))

  server.registerTool('read_resume', {
    title: 'Read a Latexy document',
    description: 'Read one Latexy document, including its complete LaTeX source and metadata.',
    inputSchema: { resume_id: resumeIdSchema },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  }, guarded(async ({ resume_id }) => operations.readResume(String(resume_id))))

  server.registerTool('create_resume', {
    title: 'Create a Latexy document',
    description: 'Create a new Latexy document from complete LaTeX source.',
    inputSchema: {
      title: z.string().min(1).max(255),
      latex_content: z.string().min(1).max(1_000_000),
      document_type: documentType.default('resume'),
      tags: z.array(z.string()).optional(),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  }, guarded(async ({ title, latex_content, document_type, tags }) => operations.createResume({
    title: String(title),
    latex_content: String(latex_content),
    document_type: String(document_type),
    ...(Array.isArray(tags) ? { tags: tags.map(String) } : {}),
  })))

  server.registerTool('update_resume', {
    title: 'Update a Latexy document',
    description: 'Update selected fields. Read the document first and send complete LaTeX when changing source.',
    inputSchema: {
      resume_id: resumeIdSchema,
      title: z.string().min(1).max(255).optional(),
      latex_content: z.string().min(1).max(1_000_000).optional(),
      expected_latex_content: z.string().max(1_000_000).optional(),
      document_type: documentType.optional(),
      tags: z.array(z.string()).optional(),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  }, guarded(async ({ resume_id, title, latex_content, expected_latex_content, document_type, tags }) => {
    const patch = {
      ...(typeof title === 'string' ? { title } : {}),
      ...(typeof latex_content === 'string' ? { latex_content } : {}),
      ...(typeof expected_latex_content === 'string' ? { expected_latex_content } : {}),
      ...(typeof document_type === 'string' ? { document_type } : {}),
      ...(Array.isArray(tags) ? { tags: tags.map(String) } : {}),
    }
    if (Object.keys(patch).length === 0) throw new Error('Provide at least one field to update.')
    return operations.updateResume(String(resume_id), patch)
  }))

  server.registerTool('archive_resume', {
    title: 'Archive a Latexy document',
    description: 'Move a document to the archive. This is reversible and does not permanently delete it.',
    inputSchema: { resume_id: resumeIdSchema },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  }, guarded(async ({ resume_id }) => operations.archiveResume(String(resume_id))))

  server.registerTool('compile_resume', {
    title: 'Compile a Latexy document',
    description: 'Queue compilation. Returns a job ID; call get_job_status for completion details.',
    inputSchema: { resume_id: resumeIdSchema },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  }, guarded(async ({ resume_id }) => operations.submitResumeJob(String(resume_id), 'latex_compilation')))

  server.registerTool('score_resume', {
    title: 'Score a Latexy document',
    description: 'Queue ATS scoring for a stored document, optionally against a job description.',
    inputSchema: {
      resume_id: resumeIdSchema,
      job_description: z.string().max(200_000).optional(),
      industry: z.string().max(100).optional(),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  }, guarded(async ({ resume_id, job_description, industry }) => operations.submitResumeJob(
    String(resume_id),
    'ats_scoring',
    {
      ...(typeof job_description === 'string' ? { job_description } : {}),
      ...(typeof industry === 'string' ? { industry } : {}),
    },
  )))

  server.registerTool('get_job_status', {
    title: 'Get a Latexy job',
    description: 'Read current job state and include the result after the job reaches a terminal state.',
    inputSchema: { job_id: jobIdSchema },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  }, guarded(async ({ job_id }) => operations.getJobStatus(String(job_id))))

  server.registerResource(
    'latexy-resume',
    new ResourceTemplate('resume:///{resume_id}', {
      list: async () => {
        const { resumes } = await operations.listResumes()
        return {
          resources: resumes.map(resume => ({
            uri: `resume:///${resume.id}`,
            name: resume.title,
            title: resume.title,
            description: `${resume.document_type} updated ${resume.updated_at}`,
            mimeType: 'application/x-latex',
          })),
        }
      },
    }),
    {
      title: 'Latexy resume source',
      description: 'Complete LaTeX source for a Latexy document.',
      mimeType: 'application/x-latex',
    },
    async (uri, variables) => {
      const rawId = variables['resume_id']
      const resumeId = Array.isArray(rawId) ? rawId[0] : rawId
      if (!resumeId) throw new Error('Missing resume ID')
      const resume = await operations.readResume(resumeId)
      return {
        contents: [{ uri: uri.href, mimeType: 'application/x-latex', text: resume.latex_content }],
      }
    },
  )

  return server
}

export async function main(): Promise<void> {
  const config = await readConfig()
  if (!config.token) {
    throw new Error(
      'Latexy authentication is required. Set LATEXY_SESSION_TOKEN or sign in once with the latexy TUI.',
    )
  }
  const operations = createMcpOperations(initApiClient(config.backendUrl, config.token))
  const server = createLatexyMcpServer(operations)
  await server.connect(new StdioServerTransport())
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(error => {
    process.stderr.write(`latexy-mcp: ${messageFor(error)}\n`)
    process.exit(1)
  })
}
