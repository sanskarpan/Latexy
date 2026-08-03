/**
 * Account, artefact and listing commands — plain REST, printed immediately.
 */
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'

import { getApiClient } from '../lib/api-client.js'
import { addMessage } from '../stores/messages.js'
import type { ParsedCommand } from '../commands/parser.js'
import { describeError, formatAge, report, requireAuth } from './shared.js'

export async function runJobs(): Promise<void> {
  if (!requireAuth()) return
  try {
    const res = await getApiClient().get<{ jobs?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>('/jobs/')
    const jobs = Array.isArray(res) ? res : (res.jobs ?? [])
    if (jobs.length === 0) {
      addMessage({ role: 'system', content: 'No recent jobs.' })
      return
    }
    addMessage({
      role: 'system',
      content: `Recent jobs (${jobs.length}):\n` + jobs.slice(0, 20).map(j =>
        `  ${String(j['job_id'] ?? '').slice(0, 8)}  ${String(j['job_type'] ?? '').padEnd(20)} ` +
        `${String(j['status'] ?? '').padEnd(10)} ${j['created_at'] != null ? formatAge(String(j['created_at'])) : ''}`,
      ).join('\n'),
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not list jobs: ${describeError(err)}` })
  }
}

export async function runPdf(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const jobId = parsed.positional[0]
  if (!jobId) {
    addMessage({ role: 'error', content: 'Which job? /pdf <job-id> — see /jobs for recent ones.' })
    return
  }
  try {
    const client = getApiClient()
    const res = await fetch(`${(client as unknown as { baseUrl: string }).baseUrl ?? ''}/download/${jobId}`)
    if (!res.ok) throw new Error(`server returned ${res.status}`)
    const buf = Buffer.from(await res.arrayBuffer())
    const out = join(process.cwd(), `resume-${jobId.slice(0, 8)}.pdf`)
    await writeFile(out, buf)
    report('PDF downloaded', [['file', out], ['bytes', buf.length]])
  } catch (err) {
    addMessage({ role: 'error', content: `Download failed: ${describeError(err)}` })
  }
}

export async function runLog(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const jobId = parsed.positional[0]
  if (!jobId) {
    addMessage({ role: 'error', content: 'Which job? /log <job-id> — see /jobs for recent ones.' })
    return
  }
  try {
    const res = await getApiClient().get<{ logs?: string } | string>(`/logs/${jobId}`)
    const text = typeof res === 'string' ? res : (res.logs ?? '')
    addMessage({
      role: 'log_stream',
      content: '',
      jobId,
      resultData: { lines: text.split('\n').slice(-200) },
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not fetch logs: ${describeError(err)}` })
  }
}

export async function runAnalytics(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const period = (parsed.args['period'] as string | undefined) ?? '30d'
  try {
    const res = await getApiClient().get<Record<string, unknown>>(`/analytics/me?period=${period}`)
    report(`Your analytics (${period})`, Object.entries(res)
      .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
      .slice(0, 20) as Array<[string, unknown]>)
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load analytics: ${describeError(err)}` })
  }
}

export async function runBilling(): Promise<void> {
  if (!requireAuth()) return
  try {
    const client = getApiClient()
    const [me, ent] = await Promise.all([
      client.get<Record<string, unknown>>('/me'),
      client.get<Record<string, unknown>>('/config/entitlements').catch(() => ({} as Record<string, unknown>)),
    ])
    const quotas = (ent['quotas'] ?? {}) as Record<string, Record<string, unknown>>
    const rows: Array<[string, unknown]> = [['plan', me['plan']], ['email', me['email']]]
    for (const [dim, q] of Object.entries(quotas)) {
      rows.push([dim, `${q['used'] ?? '?'} / ${q['limit'] ?? 'unlimited'}`])
    }
    report('Subscription', rows)
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load billing: ${describeError(err)}` })
  }
}

export async function runTracker(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  try {
    const client = getApiClient()
    // The API groups by pipeline stage: {by_status: {applied: [...], offer: [...]}}.
    // Reading `.applications` (which does not exist) reported "no applications"
    // however many were tracked.
    const res = await client.get<{
      by_status?: Record<string, Array<Record<string, unknown>>>
      applications?: Array<Record<string, unknown>>
    } | Array<Record<string, unknown>>>('/tracker/applications')
    const apps: Array<Record<string, unknown>> = Array.isArray(res)
      ? res
      : res.by_status != null
        ? Object.entries(res.by_status).flatMap(([status, list]) =>
            list.map((a): Record<string, unknown> => ({ ...a, status: a['status'] ?? status })))
        : (res.applications ?? [])
    if (apps.length === 0) {
      addMessage({ role: 'system', content: 'No tracked applications yet.' })
      return
    }
    const status = parsed.args['status'] as string | undefined
    const shown = status ? apps.filter(a => String(a['status']) === status) : apps
    addMessage({
      role: 'system',
      content: `Applications (${shown.length}):\n` + shown.slice(0, 30).map(a =>
        `  ${String(a['company_name'] ?? '').padEnd(22)} ` +
        `${String(a['role_title'] ?? '').padEnd(28)} ${String(a['status'] ?? '')}`,
      ).join('\n'),
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load the tracker: ${describeError(err)}` })
  }
}

export async function runSnippets(parsed: ParsedCommand): Promise<void> {
  const q = parsed.positional.join(' ')
  try {
    const res = await getApiClient().get<{ snippets?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(
      `/snippets${q ? `?search=${encodeURIComponent(q)}` : ''}`,
    )
    const snips = Array.isArray(res) ? res : (res.snippets ?? [])
    if (snips.length === 0) {
      addMessage({ role: 'system', content: 'No snippets found.' })
      return
    }
    addMessage({
      role: 'system',
      content: `Snippets (${snips.length}):\n` + snips.slice(0, 25).map(s =>
        `  ${String(s['title'] ?? s['name'] ?? '').padEnd(34)} ` +
        `${String(s['category'] ?? '').padEnd(12)} ▲${String(s['upvotes_count'] ?? 0)}` +
        `  ⇩${String(s['installs_count'] ?? 0)}`,
      ).join('\n'),
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load snippets: ${describeError(err)}` })
  }
}

export async function runByok(): Promise<void> {
  if (!requireAuth()) return
  try {
    const client = getApiClient()
    const [keys, providers] = await Promise.all([
      client.get<{ api_keys?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>('/byok/api-keys'),
      client.get<{ providers?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>('/byok/providers')
        .catch(() => [] as Array<Record<string, unknown>>),
    ])
    const list = Array.isArray(keys) ? keys : (keys.api_keys ?? [])
    const provs = Array.isArray(providers) ? providers : (providers.providers ?? [])
    addMessage({
      role: 'system',
      content:
        `Your API keys (${list.length}):\n` +
        (list.length
          ? list.map(k => `  ${String(k['provider'] ?? k['provider_name'] ?? '').padEnd(14)} ` +
              `${String(k['name'] ?? k['key_name'] ?? '')}`).join('\n')
          : '  (none — the platform key is used)') +
        `\n\nSupported providers: ${provs.map(p => String(p['name'])).join(', ')}` +
        `\n\nKeys are added on the web app at /byok.`,
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load API keys: ${describeError(err)}` })
  }
}

export async function runModel(): Promise<void> {
  try {
    const res = await getApiClient().get<{ providers?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(
      '/byok/providers',
    )
    const provs = Array.isArray(res) ? res : (res.providers ?? [])
    addMessage({
      role: 'system',
      content: `Providers (${provs.length}):\n` + provs.map(p => {
        const models = (p['available_models'] as string[] | undefined) ?? []
        const caps = (p['capabilities'] ?? {}) as Record<string, unknown>
        return `  ${String(p['name'] ?? '').padEnd(12)} ${String(p['display_name'] ?? '').padEnd(14)}` +
          `${models.length} model(s)` +
          (caps['max_context_length'] != null ? `  ctx ${caps['max_context_length']}` : '')
      }).join('\n') + '\n\nAdd a key on the web app at /byok; it is then used automatically.',
    })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load providers: ${describeError(err)}` })
  }
}

export async function runSettings(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const client = getApiClient()
  try {
    if (parsed.args['set'] != null) {
      const [key, value] = String(parsed.args['set']).split('=')
      if (!key || value === undefined) {
        addMessage({ role: 'error', content: 'Usage: /settings --set <key>=<true|false>' })
        return
      }
      await client.put('/settings/notifications', { [key]: value === 'true' })
      addMessage({ role: 'system', content: `Set ${key} = ${value}` })
      return
    }
    const res = await client.get<Record<string, unknown>>('/settings/notifications')
    report('Notification settings', Object.entries(res) as Array<[string, unknown]>)
    addMessage({ role: 'system', content: 'Change one with /settings --set <key>=<true|false>' })
  } catch (err) {
    addMessage({ role: 'error', content: `Could not load settings: ${describeError(err)}` })
  }
}

export async function runRestore(parsed: ParsedCommand): Promise<void> {
  if (!requireAuth()) return
  const { resolveResumeId } = await import('./shared.js')
  const resumeId = await resolveResumeId(parsed)
  if (!resumeId) return

  const client = getApiClient()
  try {
    const list = await client.get<Array<Record<string, unknown>> | { checkpoints?: Array<Record<string, unknown>> }>(
      `/resumes/${resumeId}/checkpoints`,
    )
    const items = Array.isArray(list) ? list : (list.checkpoints ?? [])
    if (items.length === 0) {
      addMessage({ role: 'system', content: 'No checkpoints to restore — save one with /checkpoint.' })
      return
    }

    const { SelectOverlay } = await import('../components/overlays/SelectOverlay.js')
    const { beginPick } = await import('../lib/pick.js')
    const { openOverlay } = await import('../stores/overlay.js')
    const React = await import('react')

    const chosen = await new Promise<string | null>(resolve => {
      beginPick(resolve)
      openOverlay(React.createElement(SelectOverlay, {
        title: 'Restore which version?',
        load: async () => items.map(c => ({
          id: String(c['id']),
          label: String(c['checkpoint_label'] ?? c['optimization_level'] ?? String(c['id']).slice(0, 8)),
          detail: c['created_at'] != null ? formatAge(String(c['created_at'])) : undefined,
        })),
      }))
    })
    if (!chosen) return

    const content = await client.get<{ latex_content?: string }>(
      `/resumes/${resumeId}/checkpoints/${chosen}/content`,
    )
    if (content.latex_content == null) {
      addMessage({ role: 'error', content: 'That checkpoint has no stored content.' })
      return
    }
    await client.put(`/resumes/${resumeId}`, { latex_content: content.latex_content })
    addMessage({ role: 'system', content: 'Restored. Run /compile to rebuild the PDF.' })
  } catch (err) {
    addMessage({ role: 'error', content: `Restore failed: ${describeError(err)}` })
  }
}
