import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import type { ParsedCommand } from '../commands/parser.js'
import { getApiClient } from '../lib/api-client.js'
import { wsClient } from '../lib/ws-client.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import { createJobController } from '../hooks/useJobStream.js'
import { describeError, requireAuth, resolveResumeId } from './shared.js'

interface JobSubmitResponse {
  job_id: string
  status: string
}

export async function runCompile(parsed: ParsedCommand): Promise<void> {
  const client = getApiClient()

  // Was a bespoke check pointing at "/login", which has never been a registered
  // command — a dead end for anyone who followed it. requireAuth() gives the
  // same guidance as every other command.
  if (!requireAuth()) return

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
      // Submitted through the async job path, like the resume-id branch below.
      // POST /compile is synchronous: it writes no :meta/:state and publishes no
      // events, so the subscribe below never received anything and the tool card
      // spun forever even though the compile itself had succeeded.
      const fileBytes = await readFile(filePath)
      const res = await client.post<JobSubmitResponse>('/jobs/submit', {
        job_type: 'latex_compilation',
        latex_content: new TextDecoder().decode(fileBytes),
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
        toolResult: { error: describeError(err) },
        durationMs: 0,
      })
    }
    return
  }

  // Case 2: resume ID given, or resolved the same way as every other command.
  //
  // This used to take `/resumes?limit=1` and compile whichever resume happened to
  // sort first — ignoring both the default the user had chosen in /list and the
  // picker. With several resumes the user had no way to tell which one had been
  // built, on the single most-used command in the TUI.
  const actualResumeId = resumeId ?? await resolveResumeId(parsed)
  if (!actualResumeId) return   // resolveResumeId already explained, or the user cancelled

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
      toolResult: { error: describeError(err) },
      durationMs: 0,
    })
  }
}
