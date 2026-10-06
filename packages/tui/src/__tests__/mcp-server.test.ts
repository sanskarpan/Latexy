import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createLatexyMcpServer } from '../mcp/server.js'
import type { McpOperations, McpResume } from '../mcp/operations.js'

const id = '123e4567-e89b-42d3-a456-426614174000'
const doc: McpResume = {
  id,
  title: 'MCP CV',
  latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
  document_type: 'resume',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

const active: Array<{ close(): Promise<void> }> = []
afterEach(async () => {
  await Promise.all(active.splice(0).map(item => item.close()))
})

function operations(): McpOperations {
  return {
    listResumes: vi.fn(async () => ({ resumes: [doc], total: 1 })),
    readResume: vi.fn(async () => doc),
    createResume: vi.fn(async () => doc),
    updateResume: vi.fn(async () => doc),
    archiveResume: vi.fn(async () => doc),
    submitResumeJob: vi.fn(async () => ({ job_id: id, status: 'queued' as const })),
    getJobStatus: vi.fn(async () => ({ job_id: id, status: 'processing' })),
  }
}

async function connected(ops = operations()) {
  const server = createLatexyMcpServer(ops, 'test')
  const client = new Client({ name: 'latexy-test', version: '1.0.0' })
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  await server.connect(serverTransport)
  await client.connect(clientTransport)
  active.push(client, server)
  return { client, ops }
}

describe('Latexy MCP protocol server', () => {
  it('advertises the complete safe tool surface with behavior annotations', async () => {
    const { client } = await connected()
    const listed = await client.listTools()

    expect(listed.tools.map(tool => tool.name)).toEqual([
      'list_resumes', 'read_resume', 'create_resume', 'update_resume',
      'archive_resume', 'compile_resume', 'score_resume', 'get_job_status',
    ])
    expect(listed.tools.find(tool => tool.name === 'read_resume')?.annotations?.readOnlyHint).toBe(true)
    expect(listed.tools.find(tool => tool.name === 'create_resume')?.annotations?.idempotentHint).toBe(false)
    expect(listed.tools.every(tool => tool.annotations?.destructiveHint === false)).toBe(true)
  })

  it('validates input and returns structured resume data', async () => {
    const { client, ops } = await connected()
    const invalid = await client.callTool({ name: 'read_resume', arguments: { resume_id: 'not-a-uuid' } })
    expect(invalid.isError).toBe(true)
    expect(ops.readResume).not.toHaveBeenCalled()

    const valid = await client.callTool({ name: 'read_resume', arguments: { resume_id: id } })
    expect(valid.isError).not.toBe(true)
    expect(valid.structuredContent).toMatchObject({ id, title: 'MCP CV' })
  })

  it('refuses empty updates instead of issuing a no-op write', async () => {
    const { client, ops } = await connected()
    const response = await client.callTool({ name: 'update_resume', arguments: { resume_id: id } })
    expect(response.isError).toBe(true)
    expect(response.content).toEqual(expect.arrayContaining([
      expect.objectContaining({ text: 'Provide at least one field to update.' }),
    ]))
    expect(ops.updateResume).not.toHaveBeenCalled()
  })

  it('lists and reads LaTeX through the resume resource template', async () => {
    const { client, ops } = await connected()
    const resources = await client.listResources()
    expect(resources.resources).toEqual([
      expect.objectContaining({ uri: `resume:///${id}`, name: 'MCP CV', mimeType: 'application/x-latex' }),
    ])

    const resource = await client.readResource({ uri: `resume:///${id}` })
    expect(resource.contents).toEqual([
      expect.objectContaining({ uri: `resume:///${id}`, text: doc.latex_content }),
    ])
    expect(ops.readResume).toHaveBeenCalledWith(id)
  })
})
