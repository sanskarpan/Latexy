/**
 * AI-backed commands: optimization, ATS scoring, cover letters, interview prep.
 *
 * The long-running ones go through the job queue and render as tool cards with
 * live progress; the fast ones are plain REST and print immediately.
 */
import { getApiClient } from '../lib/api-client.js'
import { addMessage } from '../stores/messages.js'
import type { ParsedCommand } from '../commands/parser.js'
import {
  jdFailureAlreadyReported,
  withJobSlot,
  describeError,
  report,
  requireAuth,
  resolveJobDescription,
  resolveResumeId,
  submitJob,
} from './shared.js'

async function latexOf(resumeId: string): Promise<string> {
  const r = await getApiClient().get<{ latex_content: string }>(`/resumes/${resumeId}`)
  return r.latex_content
}

export async function runOptimize(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  await withJobSlot(async () => {
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const jd = await resolveJobDescription(parsed)
  if (!jd) {
    // resolveJobDescription already said why, if it knew.
    if (!jdFailureAlreadyReported()) {
      addMessage({ role: 'error', content: 'A job description is required: /optimize --jd <url|file|text>' })
    }
    return
  }
  const level = (parsed.args['level'] as string | undefined) ?? 'balanced'

  try {
    await submitJob({
      toolName: 'optimize_resume',
      toolArgs: { resume_id: resumeId, level },
      body: {
        job_type: 'llm_optimization',
        latex_content: await latexOf(resumeId),
        job_description: jd,
        optimization_level: level,
        resume_id: resumeId,
      },
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not start optimization: ${describeError(err)}` })
  }
  })
}

export async function runCombined(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  await withJobSlot(async () => {
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const jd = await resolveJobDescription(parsed)
  if (!jd) {
    if (!jdFailureAlreadyReported()) {
      addMessage({ role: 'error', content: 'A job description is required: /combined --jd <url|file|text>' })
    }
    return
  }

  try {
    await submitJob({
      toolName: 'optimize_and_compile',
      toolArgs: { resume_id: resumeId },
      body: {
        job_type: 'combined',
        latex_content: await latexOf(resumeId),
        job_description: jd,
        optimization_level: (parsed.args['level'] as string | undefined) ?? 'balanced',
        resume_id: resumeId,
      },
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not start the pipeline: ${describeError(err)}` })
  }
  })
}

export async function runAts(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  await withJobSlot(async () => {
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  // --jd is optional here, but a --jd that FAILED is not the same as none: the
  // user asked for a JD-targeted analysis and would otherwise silently get a
  // generic one, after an error message saying the posting could not be read.
  const jd = await resolveJobDescription(parsed)
  if (jd == null && jdFailureAlreadyReported()) return

  try {
    await submitJob({
      toolName: 'ats_deep_analysis',
      toolArgs: { resume_id: resumeId },
      path: '/ats/deep-analyze',
      body: {
        latex_content: await latexOf(resumeId),
        job_description: jd ?? undefined,
        industry_override: parsed.args['industry'] as string | undefined,
      },
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not start ATS analysis: ${describeError(err)}` })
  }
  })
}

export async function runQuickAts(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  try {
    // Rule-based and synchronous — no job, no LLM, so print it straight away.
    // The response carries sections_found / missing_sections /
    // keyword_match_percent. Declaring `sections` and `issues` — neither of
    // which exists — threw away the only actionable output, leaving a bare score.
    const res = await getApiClient().post<{
      score?: number
      grade?: string
      sections_found?: string[]
      missing_sections?: string[]
      keyword_match_percent?: number
    }>('/ats/quick-score', { latex_content: await latexOf(resumeId) })

    const rows: Array<[string, unknown]> = [
      ['score', res.score],
      ['grade', res.grade],
      ['keywords', res.keyword_match_percent != null ? `${res.keyword_match_percent}%` : undefined],
      ['sections found', res.sections_found?.join(', ')],
    ]
    addMessage({
      role: 'system',
      content: `Quick ATS score\n` +
        rows.filter(([, v]) => v != null && v !== '')
          .map(([k, v]) => `  ${k.padEnd(15)} ${String(v)}`).join('\n') +
        (res.missing_sections?.length
          ? `\n\nMissing sections (fix these first):\n` +
            res.missing_sections.map(m => `  · ${m}`).join('\n')
          : ''),
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Quick ATS failed: ${describeError(err)}` })
  }
}

export async function runCover(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  // No claimJobSlot() here — /cover does not hold the slot, so it must not
  // release one either, or it would free a slot a concurrent /optimize owns.
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const jd = await resolveJobDescription(parsed)
  if (!jd) {
    if (!jdFailureAlreadyReported()) {
      addMessage({ role: 'error', content: 'A job description is required: /cover --jd <url|file|text>' })
    }
    return
  }

  try {
    const res = await getApiClient().post<{ job_id?: string; cover_letter_id?: string }>(
      '/cover-letters/generate',
      {
        resume_id: resumeId,
        job_description: jd,
        company_name: parsed.args['company'] as string | undefined,
        role_title: parsed.args['role'] as string | undefined,
        tone: (parsed.args['tone'] as string | undefined) ?? 'formal',
        length_preference: (parsed.args['length'] as string | undefined) ?? '3_paragraphs',
      },
    )
    report('Cover letter queued', [
      ['job', res.job_id],
      ['cover letter', res.cover_letter_id],
      ['note', 'generation runs in the background'],
    ])
  } catch (err) {
    addMessage({ role: 'error', content: `Cover letter failed: ${describeError(err)}` })
  }
}

export async function runInterview(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  // Same as /ats: a failed --jd must stop, not degrade into a generic run
  // announced by a success card immediately after an error.
  const jd = await resolveJobDescription(parsed)
  if (jd == null && jdFailureAlreadyReported()) return

  try {
    const res = await getApiClient().post<{ job_id?: string; prep_id?: string }>(
      '/interview-prep/generate',
      {
        resume_id: resumeId,
        job_description: jd ?? undefined,
        company_name: parsed.args['company'] as string | undefined,
        role_title: parsed.args['role'] as string | undefined,
      },
    )
    report('Interview prep queued', [
      ['job', res.job_id],
      ['prep', res.prep_id],
      ['note', 'questions generate in the background'],
    ])
  } catch (err) {
    addMessage({ role: 'error', content: `Interview prep failed: ${describeError(err)}` })
  }
}
