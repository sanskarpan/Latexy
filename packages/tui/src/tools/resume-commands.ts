/**
 * Resume-centric commands: creation, variants, versions, sharing and export.
 *
 * All of these were registered in the command palette but had no handler, so
 * choosing one from autocomplete answered "Unknown command". Each maps onto
 * backend endpoints that already existed.
 */
import { writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { getApiClient } from '../lib/api-client.js'
import { addMessage } from '../stores/messages.js'
import type { ParsedCommand } from '../commands/parser.js'
import { describeError, formatAge, report, requireAuth, resolveResumeId, type Resume } from './shared.js'

interface Checkpoint {
  id: string
  created_at: string
  // The API names these `checkpoint_label` / `is_checkpoint` / `is_auto_save` —
  // not `label`/`kind`. Assuming otherwise printed a row of bare ids.
  checkpoint_label?: string | null
  is_checkpoint?: boolean
  is_auto_save?: boolean
  optimization_level?: string | null
  ats_score?: number | null
}

function checkpointKind(c: Checkpoint): string {
  if (c.is_checkpoint === true) return 'checkpoint'
  if (c.is_auto_save === true) return 'auto-save'
  if (c.optimization_level != null) return 'optimization'
  return 'version'
}

function checkpointLabel(c: Checkpoint): string {
  return c.checkpoint_label
    ?? (c.optimization_level != null ? `${c.optimization_level} optimization` : c.id.slice(0, 8))
}

export async function runNew(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const title = parsed.positional.join(' ').trim() || 'Untitled Resume'
  try {
    const created = await getApiClient().post<Resume>('/resumes/', {
      title,
      latex_content:
        '\\documentclass[11pt,letterpaper]{article}\n' +
        '\\usepackage[margin=0.75in]{geometry}\n' +
        '\\begin{document}\n\n\\section*{Your Name}\n\n\\end{document}\n',
    })
    report('Resume created', [['title', created.title], ['id', created.id]])
  } catch (err) {
    addMessage({ role: 'error', content: `Could not create the resume: ${describeError(err)}` })
  }
}

export async function runEdit(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const editor = process.env['EDITOR'] ?? process.env['VISUAL']
  if (!editor) {
    addMessage({ role: 'error', content: 'No $EDITOR set — export with /export or set EDITOR first.' })
    return
  }

  const client = getApiClient()
  try {
    const resume = await client.get<Resume & { latex_content: string }>(`/resumes/${resumeId}`)
    const path = join(tmpdir(), `latexy-${resumeId}.tex`)
    await writeFile(path, resume.latex_content, 'utf-8')

    addMessage({ role: 'system', content: `Opening ${resume.title} in ${editor}…` })
    // Inherit the terminal so the editor takes over the screen, and wait: the
    // TUI cannot repaint underneath a full-screen editor anyway.
    await new Promise<void>((resolve, reject) => {
      const child = spawn(editor, [path], { stdio: 'inherit' })
      child.on('exit', () => resolve())
      child.on('error', reject)
    })

    const { readFile } = await import('node:fs/promises')
    const edited = await readFile(path, 'utf-8')
    if (edited === resume.latex_content) {
      addMessage({ role: 'system', content: 'No changes made.' })
      return
    }
    await client.put(`/resumes/${resumeId}`, { latex_content: edited })
    addMessage({ role: 'system', content: `Saved ${resume.title}. Run /compile to rebuild the PDF.` })
  } catch (err) {
    addMessage({ role: 'error', content: `Edit failed: ${describeError(err)}` })
  }
}

export async function runFork(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  const title = parsed.positional.filter(p => !/^[0-9a-f-]{36}$/i.test(p)).join(' ').trim()
  try {
    const forked = await getApiClient().post<Resume>(`/resumes/${resumeId}/fork`,
      title ? { title } : {})
    report('Variant created', [['title', forked.title], ['id', forked.id], ['parent', resumeId]])
  } catch (err) {
    addMessage({ role: 'error', content: `Fork failed: ${describeError(err)}` })
  }
}

export async function runDiff(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  try {
    const diff = await getApiClient().get<{ diff?: string; changes?: unknown[]; message?: string }>(
      `/resumes/${resumeId}/diff-with-parent`,
    )
    if (diff.diff) {
      addMessage({ role: 'system', content: `Diff with parent:\n${diff.diff}` })
      return
    }
    if (Array.isArray(diff.changes) && diff.changes.length > 0) {
      addMessage({
        role: 'system',
        content: `Diff with parent — ${diff.changes.length} change(s):\n` +
          diff.changes.slice(0, 40).map(c => `  ${JSON.stringify(c)}`).join('\n'),
      })
      return
    }
    addMessage({ role: 'system', content: diff.message ?? 'No differences from the parent resume.' })
  } catch (err) {
    addMessage({ role: 'error', content: `Diff failed: ${describeError(err)}` })
  }
}

export async function runShare(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const client = getApiClient()
  if (parsed.args['revoke'] === true) {
    try {
      await client.delete(`/resumes/${resumeId}/share`)
      addMessage({ role: 'system', content: 'Share link revoked.' })
    } catch (err) {
      addMessage({ role: 'error', content: `Could not revoke: ${describeError(err)}` })
    }
    return
  }

  try {
    const res = await client.post<{ share_token?: string; share_url?: string }>(
      `/resumes/${resumeId}/share`, {},
    )
    const url = res.share_url ?? (res.share_token != null ? `/share/${res.share_token}` : null)
    if (url == null) {
      addMessage({ role: 'error', content: 'The server returned no share link.' })
      return
    }
    report('Share link', [['url', url], ['revoke with', '/share --revoke']])
  } catch (err) {
    addMessage({ role: 'error', content: `Share failed: ${describeError(err)}` })
  }
}

export async function runExport(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const fmt = (parsed.args['format'] as string | undefined) ?? parsed.positional.find(p => !/^[0-9a-f-]{36}$/i.test(p))
  if (!fmt) {
    try {
      const formats = await getApiClient().get<{ formats?: Array<{ id?: string; name?: string }> }>('/export/formats')
      const names = (formats.formats ?? []).map(f => f.id ?? f.name).filter(Boolean).join(', ')
      addMessage({ role: 'error', content: `Specify a format: /export --format <fmt>\nAvailable: ${names}` })
    } catch {
      addMessage({ role: 'error', content: 'Specify a format, e.g. /export --format docx' })
    }
    return
  }

  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  try {
    const data = await getApiClient().get<unknown>(`/export/${resumeId}/${fmt}`)
    const out = join(process.cwd(), `resume-${resumeId.slice(0, 8)}.${fmt}`)
    await writeFile(out, typeof data === 'string' ? data : JSON.stringify(data, null, 2), 'utf-8')
    report('Exported', [['format', fmt], ['file', out]])
  } catch (err) {
    addMessage({ role: 'error', content: `Export failed: ${describeError(err)}` })
  }
}

export async function runCheckpoint(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  const label = parsed.positional.filter(p => !/^[0-9a-f-]{36}$/i.test(p)).join(' ').trim()
    || `Checkpoint ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`
  try {
    await getApiClient().post(`/resumes/${resumeId}/checkpoints`, { label })
    report('Checkpoint saved', [['label', label], ['restore with', '/restore']])
  } catch (err) {
    addMessage({ role: 'error', content: `Checkpoint failed: ${describeError(err)}` })
  }
}

export async function runHistory(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  try {
    const list = await getApiClient().get<Checkpoint[] | { checkpoints?: Checkpoint[] }>(
      `/resumes/${resumeId}/checkpoints`,
    )
    const items = Array.isArray(list) ? list : (list.checkpoints ?? [])
    if (items.length === 0) {
      addMessage({ role: 'system', content: 'No history yet — save one with /checkpoint.' })
      return
    }
    addMessage({
      role: 'system',
      content: `Version history (${items.length}):\n` + items.slice(0, 25).map(c =>
        `  ${checkpointKind(c).padEnd(13)} ${checkpointLabel(c).padEnd(30)} ` +
        `${formatAge(c.created_at)}${c.ats_score != null ? `  ATS ${c.ats_score}` : ''}`,
      ).join('\n'),
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load history: ${describeError(err)}` })
  }
}
