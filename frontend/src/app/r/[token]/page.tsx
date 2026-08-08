'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { FileText, Loader2, AlertCircle } from 'lucide-react'
import { apiClient, type SharedResumeResponse } from '@/lib/api-client'

export default function SharedResumePage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<SharedResumeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (!token) return
    apiClient
      .getSharedResume(token)
      .then(setData)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('404') || msg.includes('not found') || msg.includes('revoked')) {
          setError('This share link has been revoked or does not exist.')
        } else if (msg.includes('compiled') || msg.includes('PDF')) {
          setError('No compiled PDF available for this resume. The owner needs to compile it first.')
        } else {
          setError('Something went wrong loading this resume.')
        }
      })
      .finally(() => setIsLoading(false))
  }, [token])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <div className="flex flex-col items-center gap-3">
          <Loader2 size={28} className="animate-spin text-fg-3" />
          <p className="text-sm text-fg-3">Loading resume…</p>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-bg px-4">
        <div className="w-full max-w-md rounded-[var(--radius-md)] border border-line bg-surface p-8 text-center">
          <div className="mb-4 flex justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-err/10 ring-1 ring-err/20">
              <AlertCircle size={22} className="text-err" />
            </div>
          </div>
          <h1 className="text-lg font-semibold text-fg">Link unavailable</h1>
          <p className="mt-2 text-sm text-fg-2">
            {error ?? 'This share link is not available.'}
          </p>
          <a
            href="/"
            className="mt-6 inline-block rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2"
          >
            Go to Latexy
          </a>
        </div>
        <p className="mt-6 text-[11px] text-fg-3">
          Powered by{' '}
          <a href="/" className="text-fg-3 hover:text-fg-2 transition">
            Latexy
          </a>{' '}
          — Build your LaTeX resume
        </p>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      {/* Minimal header */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
        <div className="flex items-center gap-2">
          <FileText size={13} className="text-fg-3" />
          <span className="text-sm font-medium text-fg-2 truncate max-w-[300px]">
            {data.resume_title}
          </span>
        </div>
        <span className="text-[10px] text-fg-3 hidden sm:block">
          View only · powered by{' '}
          <a href="/" className="text-fg-3 hover:text-fg-2 transition">
            Latexy
          </a>
        </span>
      </header>

      {/* PDF viewer */}
      <main className="flex flex-1">
        <iframe
          src={data.pdf_url}
          className="h-full w-full flex-1"
          style={{ minHeight: 'calc(100vh - 40px)' }}
          title={data.resume_title}
        />
      </main>

      {/* Footer */}
      <footer className="flex h-8 shrink-0 items-center justify-center border-t border-line bg-surface">
        <p className="text-[10px] text-fg-3">
          Powered by{' '}
          <a href="/" className="text-fg-3 hover:text-fg-2 transition">
            Latexy
          </a>{' '}
          — Build your LaTeX resume at latexy.io
        </p>
      </footer>
    </div>
  )
}
