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
    // The exit code matters. Discarding it meant a crashed, killed, or
    // nonzero-exiting editor still had whatever bytes were on disk written back
    // — a truncated file silently replaced the user's resume and was reported as
    // "Saved". Refuse to save unless the editor exited cleanly.
    const { code, signal } = await new Promise<{ code: number | null; signal: string | null }>(
      (resolve, reject) => {
        // "code --wait" and "subl -w" are the documented values for VS Code and
        // Sublime; treating the whole variable as one executable name reported
        // `spawn code --wait ENOENT`, naming a binary the user never set. git
        // solves this by going through a shell; so do we.
        const [bin, ...editorArgs] = editor.trim().split(/\s+/)
        const child = spawn(bin!, [...editorArgs, path], { stdio: 'inherit' })
        child.on('exit', (c, sig) => resolve({ code: c, signal: sig }))
        child.on('error', reject)
      },
    )
    if (signal != null) {
      addMessage({
        role: 'error',
        content: `${editor} was killed (${signal}) — nothing saved. Your resume is unchanged, ` +
          `and the draft is at ${path}.`,
      })
      return
    }
    if (code !== 0) {
      addMessage({
        role: 'error',
        content: `${editor} exited with code ${code} — nothing saved. Your resume is unchanged, ` +
          `and the draft is at ${path}.`,
      })
      return
    }

    const { readFile } = await import('node:fs/promises')
    // Read bytes, not text. readFile(path,'utf-8') substitutes U+FFFD for any
    // byte it cannot decode, so a latin-1 editor writing "Résumé" silently
    // saved "R\uFFFDsum\uFFFD" and reported success — three characters
    // destroyed irreversibly.
    const rawBytes = await readFile(path)
    const edited = new TextDecoder('utf-8', { fatal: false }).decode(rawBytes)
    if (edited.includes('\uFFFD') && !resume.latex_content.includes('\uFFFD')) {
      addMessage({
        role: 'error',
        content: `The edited file is not valid UTF-8 — refusing to save, since converting it ` +
          `would destroy characters. Re-save it as UTF-8. The draft is at ${path}.`,
      })
      return
    }
    if (edited === resume.latex_content) {
      addMessage({ role: 'system', content: 'No changes made.' })
      return
    }
    // A clean exit over an emptied buffer is almost always an accident, and the
    // saved version is the only copy unless the user happened to /checkpoint.
    if (edited.trim() === '') {
      addMessage({
        role: 'error',
        content: `The edited file is empty — refusing to overwrite ${resume.title}. ` +
          `The draft is at ${path} if that was intentional.`,
      })
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
    // The endpoint hands back both documents, not a computed diff — reading
    // `diff`/`changes`/`message` matched nothing, so it always claimed the
    // variant was identical to its parent however different it was.
    const res = await getApiClient().get<{
      parent_latex?: string
      parent_title?: string
      variant_latex?: string
      variant_title?: string
      detail?: string
    }>(`/resumes/${resumeId}/diff-with-parent`)

    if (res.parent_latex == null || res.variant_latex == null) {
      addMessage({
        role: 'system',
        content: res.detail ?? 'This resume has no parent to compare against — fork one with /fork.',
      })
      return
    }
    if (res.parent_latex === res.variant_latex) {
      addMessage({ role: 'system', content: 'Identical to the parent resume.' })
      return
    }
    // LogStreamCard keeps only the last 25 lines and is titled "Build Log",
    // which hid three-quarters of the removals and dropped the ---/+++ headers
    // that say which side is which. A diff is not a log; render it as text.
    const lines = unifiedDiff(
      res.parent_latex, res.variant_latex,
      res.parent_title ?? 'parent', res.variant_title ?? 'variant',
    )
    // Keeping the head hid every addition, because unifiedDiff emits all
    // removals first — the mirror of the earlier bug that kept the tail and hid
    // every removal. Budget each side separately so the user always sees both
    // what went and what replaced it.
    const shown = boundedDiff(lines, 60)
    addMessage({ role: 'system', content: shown.join('\n') })
  } catch (err) {
    // The API answers 400 for a resume with no parent, so ApiClient throws
    // before the friendly branch above can run. Recognise it here instead of
    // leaving the user a bare red error with no next step.
    const msg = describeError(err)
    if (/no parent/i.test(msg)) {
      addMessage({
        role: 'system',
        content: 'This resume has no parent to compare against — make a variant with /fork first.',
      })
      return
    }
    addMessage({ role: 'error', content: `Diff failed: ${msg}` })
  }
}

/**
 * Trim a diff to *budget* lines while keeping both sides visible.
 *
 * Removals and additions are emitted in blocks, so a naive head or tail slice
 * shows only one of them. This splits the budget between the two.
 */
function boundedDiff(lines: string[], budget: number): string[] {
  if (lines.length <= budget) return lines
  const header = lines.filter(l => l.startsWith('---') || l.startsWith('+++') || l.startsWith('    '))
  const removals = lines.filter(l => l.startsWith('- '))
  const additions = lines.filter(l => l.startsWith('+ '))
  const each = Math.max(4, Math.floor((budget - header.length - 2) / 2))
  const out = [...header]
  out.push(...removals.slice(0, each))
  if (removals.length > each) out.push(`  … ${removals.length - each} more removed`)
  out.push(...additions.slice(0, each))
  if (additions.length > each) out.push(`  … ${additions.length - each} more added`)
  return out
}

/** Minimal line diff — enough to see what changed without pulling in a library. */
function unifiedDiff(a: string, b: string, aName: string, bName: string): string[] {
  const left = a.split('\n')
  const right = b.split('\n')
  const seen = new Set(left)
  const kept = new Set(right)
  const removed = left.filter(l => !kept.has(l))
  const added = right.filter(l => !seen.has(l))
  const out: string[] = [
    `--- ${aName}`,
    `+++ ${bName}`,
    `    ${removed.length} removed · ${added.length} added`,
    '',
  ]
  for (const line of removed) out.push(`- ${line}`)
  for (const line of added) out.push(`+ ${line}`)
  if (removed.length === 0 && added.length === 0) {
    out.push('  (only whitespace or ordering differs)')
  }
  return out
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
      // The API keys these `key`, not `id`/`name`; reading the wrong field made
      // filter(Boolean) empty the list, so the "Available:" hint was always blank.
      type Fmt = { key?: string; id?: string; name?: string }
      const formats = await getApiClient().get<{ formats?: Fmt[] } | Fmt[]>('/export/formats')
      const list = Array.isArray(formats) ? formats : (formats.formats ?? [])
      const names = list.map(f => f.key ?? f.id ?? f.name).filter(Boolean).join(', ')
      addMessage({ role: 'error', content: `Specify a format: /export --format <fmt>\nAvailable: ${names}` })
    } catch {
      addMessage({ role: 'error', content: 'Specify a format, e.g. /export --format docx' })
    }
    return
  }

  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return
  try {
    // Always fetch bytes. docx/pdf are binary, and decoding them as text
    // corrupted the file while still reporting success.
    const bytes = await getApiClient().getBinary(`/export/${resumeId}/${fmt}`)
    const out = join(process.cwd(), `resume-${resumeId.slice(0, 8)}.${fmt}`)
    await writeFile(out, bytes)
    report('Exported', [['format', fmt], ['file', out], ['bytes', bytes.length]])
  } catch (err) {
    addMessage({ role: 'error', content: `Export failed: ${describeError(err)}` })
  }
}

export async function runCheckpoint(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  // The server caps manual checkpoints at 20 and answers "Delete older ones
  // first" — which was a dead end, because no TUI command could delete one. The
  // endpoint has always existed; nothing exposed it.
  if (parsed.args['delete'] === true || parsed.args['delete'] === 'true') {
    await deleteCheckpoint(resumeId)
    return
  }

  const label = parsed.positional.filter(p => !/^[0-9a-f-]{36}$/i.test(p)).join(' ').trim()
    || `Checkpoint ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`
  try {
    await getApiClient().post(`/resumes/${resumeId}/checkpoints`, { label })
    report('Checkpoint saved', [['label', label], ['restore with', '/restore']])
  } catch (err) {
    addMessage({ role: 'error', content: `Checkpoint failed: ${describeError(err)}` })
  }
}

/** Pick a manual checkpoint and delete it. Only checkpoints are deletable. */
async function deleteCheckpoint(resumeId: string): Promise<void> {
  const client = getApiClient()
  try {
    const list = await client.get<Checkpoint[] | { checkpoints?: Checkpoint[] }>(
      `/resumes/${resumeId}/checkpoints`,
    )
    const items = (Array.isArray(list) ? list : (list.checkpoints ?? []))
      .filter(c => c.is_checkpoint === true)
    if (items.length === 0) {
      addMessage({ role: 'system', content: 'No manual checkpoints to delete.' })
      return
    }

    const { SelectOverlay } = await import('../components/overlays/SelectOverlay.js')
    const { beginPick } = await import('../lib/pick.js')
    const { openOverlay } = await import('../stores/overlay.js')
    const React = await import('react')

    const chosen = await new Promise<string | null>(resolve => {
      beginPick(resolve)
      openOverlay(React.createElement(SelectOverlay, {
        title: `Delete which checkpoint? (${items.length} of 20 used)`,
        load: async () => items.map(c => ({
          id: c.id,
          label: checkpointLabel(c),
          detail: formatAge(c.created_at),
        })),
      }))
    })
    if (chosen == null) return

    await client.delete(`/resumes/${resumeId}/checkpoints/${chosen}`)
    addMessage({ role: 'system', content: 'Checkpoint deleted.' })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not delete the checkpoint: ${describeError(err)}` })
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
