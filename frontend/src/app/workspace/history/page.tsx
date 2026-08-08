'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { apiClient, type JobStateResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'

type StatusFilter = 'all' | 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'

const statusFilters: StatusFilter[] = ['all', 'queued', 'processing', 'completed', 'failed', 'cancelled']

export default function WorkspaceHistoryPage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const [jobs, setJobs] = useState<JobStateResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [status, setStatus] = useState<StatusFilter>('all')

  useEffect(() => {
    if (!session) return

    const load = async () => {
      setIsLoading(true)
      try {
        const response = await apiClient.listJobs()
        const sorted = [...(response.jobs || [])].sort((a, b) => b.last_updated - a.last_updated)
        setJobs(sorted)
      } catch (error) {
        console.error('Failed to load history', error)
      } finally {
        setIsLoading(false)
      }
    }

    load()
  }, [session])

  const filteredJobs = useMemo(() => {
    if (status === 'all') return jobs
    return jobs.filter((job) => job.status === status)
  }, [jobs, status])

  if (sessionLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="content-shell">
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface mx-auto max-w-2xl p-8 text-center">
          <h1 className="text-2xl font-semibold text-fg">Sign in to view history</h1>
          <p className="mt-2 text-fg-2">Execution history is available only for authenticated workspaces.</p>
          <Link href="/login" className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 mt-6 inline-block">
            Continue to Login
          </Link>
        </section>
      </div>
    )
  }

  return (
    <div className="content-shell space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Run History</h1>
          <p className="mt-1 text-sm text-fg-2">Inspect pipeline runs, status changes, and recent execution timelines.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs text-fg hover:bg-surface-2">
            Back to Workspace
          </Link>
          <Link href="/workspace/new" className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110">
            New Resume
          </Link>
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap gap-2">
          {statusFilters.map((filter) => (
            <button
              key={filter}
              onClick={() => setStatus(filter)}
              className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] transition ${
                status === filter
                  ? 'border-accent bg-accent-soft text-accent-strong'
                  : 'border-line bg-surface-2 text-fg-2 hover:border-line-2 hover:text-fg'
              }`}
            >
              {filter}
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface overflow-hidden">
        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        ) : filteredJobs.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <p className="text-base text-fg">No runs found for this filter.</p>
            <p className="mt-2 text-sm text-fg-3">Start a compile or optimization run to populate history.</p>
          </div>
        ) : (
          <div className="overflow-x-auto scrollbar-subtle">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-[0.14em] text-fg-3">
                  <th className="px-5 py-3 font-semibold">Run ID</th>
                  <th className="px-5 py-3 font-semibold">Status</th>
                  <th className="px-5 py-3 font-semibold">Stage</th>
                  <th className="px-5 py-3 font-semibold">Progress</th>
                  <th className="px-5 py-3 font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {filteredJobs.map((job, index) => (
                  <tr key={job.job_id ?? `${job.last_updated}-${index}`} className="bg-bg/10">
                    <td className="px-5 py-4 text-sm font-medium text-fg">{job.job_id ? job.job_id.slice(0, 12) : 'N/A'}</td>
                    <td className="px-5 py-4 text-sm capitalize text-fg-2">{job.status}</td>
                    <td className="px-5 py-4 text-sm text-fg-2">{job.stage || 'waiting'}</td>
                    <td className="px-5 py-4">
                      <div className="w-full max-w-[180px] rounded-full bg-surface-2">
                        <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.max(2, job.percent)}%` }} />
                      </div>
                      <p className="mt-1 text-xs text-fg-3">{job.percent}%</p>
                    </td>
                    <td className="px-5 py-4 text-sm text-fg-2">
                      {new Date(job.last_updated * 1000).toLocaleString([], {
                        year: 'numeric',
                        month: 'short',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
