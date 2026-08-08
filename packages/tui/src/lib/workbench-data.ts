/**
 * Workbench data layer (#1095) — typed fetchers for the Miller-columns view and
 * the job dock. Every fetch is best-effort: it resolves to a safe empty value on
 * error so a flaky endpoint never blanks the whole Workbench.
 */
import { getApiClient } from './api-client.js'

export interface WbResume {
  id: string
  title: string
  updated_at?: string
  ats_score?: number | null
  grade?: string | null
  type?: string
  is_pinned?: boolean
}

export interface DockJob {
  id: string
  kind: string
  status: string
  percent: number
  label?: string
}

/** The seven collections that make up the first Miller column. */
export const COLLECTIONS: Array<{ key: string; label: string }> = [
  { key: 'resumes', label: 'resumes' },
  { key: 'variants', label: 'variants' },
  { key: 'compile', label: 'compile' },
  { key: 'ats', label: 'ats reports' },
  { key: 'cover', label: 'cover letters' },
  { key: 'tracker', label: 'tracker' },
  { key: 'snippets', label: 'snippets' },
]

function toArray<T>(res: { [k: string]: unknown } | T[], key: string): T[] {
  if (Array.isArray(res)) return res as T[]
  const v = (res as Record<string, unknown>)[key]
  return Array.isArray(v) ? (v as T[]) : []
}

export async function fetchResumes(): Promise<WbResume[]> {
  try {
    const r = await getApiClient().get<{ resumes: WbResume[] }>('/resumes/?limit=50')
    return (r.resumes ?? []).filter(Boolean)
  } catch {
    return []
  }
}

export async function fetchDockJobs(): Promise<DockJob[]> {
  try {
    const r = await getApiClient().get<{ jobs?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>('/jobs/')
    const list = toArray<Record<string, unknown>>(r, 'jobs')
    return list.slice(0, 6).map((j) => ({
      id: String(j['job_id'] ?? j['id'] ?? ''),
      kind: String(j['job_type'] ?? j['type'] ?? 'job'),
      status: String(j['status'] ?? 'unknown'),
      percent: Math.max(0, Math.min(100, Number(j['percent'] ?? j['progress'] ?? 0) || 0)),
      label: (j['resume_title'] ?? j['label'] ?? undefined) as string | undefined,
    }))
  } catch {
    return []
  }
}

/** Best-effort counts for the collections column. Missing endpoints stay at 0. */
export async function fetchCollectionCounts(): Promise<Record<string, number>> {
  const client = getApiClient()
  const out: Record<string, number> = {}
  await Promise.allSettled([
    client.get<{ resumes?: unknown[] }>('/resumes/?limit=50').then((r) => {
      out['resumes'] = (r.resumes ?? []).length
    }),
    client
      .get<{ by_status?: Record<string, unknown[]> } | unknown[]>('/tracker/applications')
      .then((r) => {
        out['tracker'] = Array.isArray(r)
          ? r.length
          : Object.values(r.by_status ?? {}).reduce((n, l) => n + (Array.isArray(l) ? l.length : 0), 0)
      }),
    client.get<{ snippets?: unknown[] } | unknown[]>('/snippets').then((r) => {
      out['snippets'] = toArray<unknown>(r, 'snippets').length
    }),
    client.get<{ jobs?: unknown[] } | unknown[]>('/jobs/').then((r) => {
      out['compile'] = toArray<unknown>(r, 'jobs').length
    }),
  ])
  return out
}
