import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import type { ParsedCommand } from '../commands/parser.js'
import { getApiClient } from '../lib/api-client.js'
import { wsClient } from '../lib/ws-client.js'
import { $session } from '../stores/session.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import { createJobController } from '../hooks/useJobStream.js'

interface JobSubmitResponse {
  job_id: string
  status: string
}

interface ResumeListResponse {
  resumes: Array<{ id: string; title: string }>
}

export async function runCompile(parsed: ParsedCommand): Promise<void> {
  const client = getApiClient()
  const session = $session.get()

  if (!session.isAuthenticated) {
    addMessage({ role: 'error', content: 'Not logged in. Use /login or restart to authenticate.' })
    return
  }

  const compiler = (parsed.args['compiler'] as string | undefined) ?? 'pdflatex'
  const resumeIdFlag = parsed.args['resume-id'] as string | undefined
  // Positional: if it looks like a UUID (contains dashes), treat as resume-id; otherwise treat as file path
  const firstPositional = parsed.positional[0]
  const looksLikeUUID = firstPositional ? /^[0-9a-f-]{36}$/i.test(firstPositional) : false
  const resumeId = resumeIdFlag ?? (looksLikeUUID ? firstPositional : undefined)
  const filePath = !looksLikeUUID ? firstPositional : undefined

  // Case 1: local .tex file upload
  if (filePath) {
    const toolMsgId = addMessage({
      role: 'tool_use',
      content: '',
      toolName: 'compile_pdf',
      toolState: 'running',
      toolArgs: { file: basename(filePath), compiler },
    })

    try {
      const fileBytes = await readFile(filePath)
      const form = new FormData()
      form.append('file', new Blob([fileBytes], { type: 'application/octet-stream' }), basename(filePath))
      form.append('compiler', compiler)

      const res = await client.postForm<JobSubmitResponse>('/compile', form)
      const jobId = res.job_id

      $activeJobId.set(jobId)
      const ctrl = createJobController(jobId)
      ctrl.setToolMsgId(toolMsgId)
      wsClient.subscribe(jobId, '0')
    } catch (err) {
      updateMessage(toolMsgId, {
        toolState: 'error',
        toolResult: { error: String(err) },
        durationMs: 0,
      })
    }
    return
  }

  // Case 2: resume ID given — submit job directly
  let actualResumeId = resumeId

  if (!actualResumeId) {
    // No resume specified — fetch first resume
    try {
      const list = await client.get<ResumeListResponse>('/resumes?limit=1')
      actualResumeId = list.resumes[0]?.id
      if (!actualResumeId) {
        addMessage({ role: 'error', content: 'No resumes found. Create one first with /new.' })
        return
      }
    } catch (err) {
      addMessage({ role: 'error', content: `Failed to fetch resumes: ${String(err)}` })
      return
    }
  }

  const toolMsgId = addMessage({
    role: 'tool_use',
    content: '',
    toolName: 'compile_pdf',
    toolState: 'running',
    toolArgs: { resume_id: actualResumeId, compiler },
  })

  try {
    const resume = await client.get<{ latex_content: string }>(`/resumes/${actualResumeId}`)
    const res = await client.post<JobSubmitResponse>('/jobs/submit', {
      job_type: 'latex_compilation',
      latex_content: resume.latex_content,
      compiler,
    })
    const jobId = res.job_id

    $activeJobId.set(jobId)
    const ctrl = createJobController(jobId)
    ctrl.setToolMsgId(toolMsgId)
    wsClient.subscribe(jobId, '0')
  } catch (err) {
    updateMessage(toolMsgId, {
      toolState: 'error',
      toolResult: { error: String(err) },
      durationMs: 0,
    })
  }
}
