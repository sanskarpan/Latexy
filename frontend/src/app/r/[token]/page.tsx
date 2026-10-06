'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { FileText, Loader2, AlertCircle, EyeOff, RefreshCw } from 'lucide-react'
import { apiClient, type SharedResumeResponse } from '@/lib/api-client'
import ReviewCommentsPanel from '@/components/ReviewCommentsPanel'

export default function SharedResumePage() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<SharedResumeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [view, setView] = useState<'pdf' | 'text'>('pdf')
  const [retryKey, setRetryKey] = useState(0)
  const requestGeneration = useRef(0)

  useEffect(() => {
    const generation = ++requestGeneration.current
    if (!token) {
      setData(null)
      setError(null)
      setIsLoading(false)
      return () => {
        if (requestGeneration.current === generation) requestGeneration.current += 1
      }
    }

    setData(null)
    setError(null)
    setIsLoading(true)

    const isCurrent = () => requestGeneration.current === generation
    apiClient
      .getSharedResume(token)
      .then((response) => {
        if (isCurrent()) setData(response)
      })
      .catch((err: unknown) => {
        if (!isCurrent()) return
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('404') || msg.includes('not found') || msg.includes('revoked')) {
          setError('This share link has been revoked or does not exist.')
        } else if (msg.includes('compiled') || msg.includes('PDF')) {
          setError('No compiled PDF available for this resume. The owner needs to compile it first.')
        } else {
          setError('Something went wrong loading this resume.')
        }
      })
      .finally(() => {
        if (isCurrent()) setIsLoading(false)
      })

    return () => {
      if (requestGeneration.current === generation) requestGeneration.current += 1
    }
  }, [token, retryKey])

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
          <Link
            href="/"
            className="mt-6 inline-block rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2"
          >
            Go to Latexy
          </Link>
        </div>
        <p className="mt-6 text-[11px] text-fg-3">
          Powered by{' '}
          <Link href="/" className="text-fg-3 hover:text-fg-2 transition">
            Latexy
          </Link>{' '}
          — Build your LaTeX resume
        </p>
      </div>
    )
  }

  if (data.anonymous_processing || !data.pdf_url) {
    return (
      <div className="flex min-h-screen flex-col bg-bg">
        <div className="content-shell flex flex-1 items-center justify-center py-12">
          <div className="w-full max-w-3xl rounded-[var(--radius-md)] border border-line bg-surface p-6 sm:p-8">
            <div role="status" className="flex items-start gap-3">
              <Loader2 size={20} className="mt-0.5 shrink-0 animate-spin text-accent-strong" />
              <div>
                <h1 className="text-lg font-semibold text-fg">Anonymous PDF is being prepared</h1>
                <p className="mt-1 text-sm text-fg-2">
                  The original PDF is never shown while redaction is in progress. The redacted text
                  alternative is available below.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => { setIsLoading(true); setRetryKey((key) => key + 1) }}
              className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm font-semibold text-fg-2 hover:text-fg"
            >
              <RefreshCw size={14} /> Check again
            </button>
            <section aria-labelledby="accessible-resume-heading" className="mt-8 border-t border-line pt-6">
              <h2 id="accessible-resume-heading" className="text-base font-semibold text-fg">
                Accessible text
              </h2>
              <pre className="mt-3 max-h-[60vh] overflow-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-fg-2">
                {data.accessible_text || 'The text alternative is not available yet.'}
              </pre>
            </section>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      {data.is_anonymous && (
        <div role="status" className="flex items-center justify-center gap-2 border-b border-warn/30 bg-warn/10 px-4 py-2 text-xs font-medium text-warn">
          <EyeOff size={13} aria-hidden="true" />
          Anonymous review copy — detected personal identifiers have been redacted.
        </div>
      )}
      {/* Minimal header */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
        <div className="flex items-center gap-2">
          <FileText size={13} className="text-fg-3" />
          <span className="text-sm font-medium text-fg-2 truncate max-w-[300px]">
            {data.resume_title}
          </span>
          <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-fg-3">
            View only
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-pressed={view === 'pdf'}
            onClick={() => setView('pdf')}
            className={`rounded px-2 py-1 text-xs ${view === 'pdf' ? 'bg-surface-2 text-fg' : 'text-fg-3'}`}
          >
            PDF
          </button>
          <button
            type="button"
            aria-pressed={view === 'text'}
            onClick={() => setView('text')}
            className={`rounded px-2 py-1 text-xs ${view === 'text' ? 'bg-surface-2 text-fg' : 'text-fg-3'}`}
          >
            Accessible text
          </button>
        </div>
      </header>

      {/* PDF viewer */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {view === 'pdf' && data.review_comments && data.pdf_url ? (
          <div className="min-h-0 min-w-0 flex-1">
            <ReviewCommentsPanel shareToken={token} pdfUrl={data.pdf_url} title="Review comments" />
          </div>
        ) : <div className="min-h-0 min-w-0 flex-1">
          {view === 'pdf' ? (
            <iframe
              src={data.pdf_url}
              className="h-full w-full"
              style={{ minHeight: 'calc(100vh - 40px)' }}
              title={`${data.resume_title} PDF`}
            />
          ) : (
            <article className="content-shell w-full py-10" aria-labelledby="shared-resume-title">
              <h1 id="shared-resume-title" className="font-display text-3xl font-semibold text-fg">
                {data.resume_title}
              </h1>
              <pre className="mt-6 whitespace-pre-wrap font-sans text-base leading-relaxed text-fg-2">
                {data.accessible_text || 'The text alternative is not available for this document.'}
              </pre>
            </article>
          )}
        </div>}
        {data.review_comments && token && !(view === 'pdf' && data.pdf_url) && (
          <aside className="min-h-[24rem] w-full shrink-0 border-t border-line bg-surface md:min-h-0 md:w-80 md:border-l md:border-t-0">
            <ReviewCommentsPanel shareToken={token} pdfUrl={data.pdf_url} />
          </aside>
        )}
      </div>

      {/* Footer */}
      <footer className="flex h-8 shrink-0 items-center justify-center border-t border-line bg-surface">
        <p className="text-[10px] text-fg-3">
          Powered by{' '}
          <Link href="/" className="text-fg-3 hover:text-fg-2 transition">
            Latexy
          </Link>{' '}
          — Build your LaTeX resume at latexy.xyz
        </p>
      </footer>
    </div>
  )
}
