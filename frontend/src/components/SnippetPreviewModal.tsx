'use client'

/**
 * Snippet Preview Modal — Feature 82.
 * Shows read-only Monaco view of a snippet + insert button.
 */

import { useEffect, useRef } from 'react'
import { X, Download, Star, Package, Calendar } from 'lucide-react'
import type { SnippetResponse } from '@/lib/api-client'

interface SnippetPreviewModalProps {
  snippet: SnippetResponse
  onInsert: (content: string) => void
  onClose: () => void
}

export default function SnippetPreviewModal({
  snippet,
  onInsert,
  onClose,
}: SnippetPreviewModalProps) {
  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose()
      }}
    >
      <div className="flex w-full max-w-2xl flex-col rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-line p-4">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              {snippet.is_official && (
                <Star size={12} className="text-warn" fill="currentColor" />
              )}
              <h2 className="text-[13px] font-bold text-fg">{snippet.title}</h2>
            </div>
            <p className="mt-0.5 text-[11px] text-fg-3">{snippet.description}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
              <span className="rounded bg-surface-2 px-1.5 py-0.5 capitalize">{snippet.category}</span>
              <span className="flex items-center gap-0.5">
                <Download size={9} />
                {snippet.installs_count}
              </span>
              {snippet.author_name && (
                <span>by {snippet.author_name}</span>
              )}
              <span className="flex items-center gap-0.5">
                <Calendar size={9} />
                {new Date(snippet.created_at).toLocaleDateString()}
              </span>
            </div>
            {snippet.tags.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {snippet.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-accent-soft px-1.5 py-0.5 text-[9px] text-accent-strong"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 rounded p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        {/* Code preview */}
        <div className="min-h-0 flex-1 overflow-auto">
          <pre className="p-4 text-[11px] leading-relaxed text-fg-2 font-mono whitespace-pre-wrap break-words">
            {snippet.content}
          </pre>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-line p-4">
          <button
            onClick={onClose}
            className="rounded-[var(--radius-md)] px-3 py-1.5 text-[11px] text-fg-3 transition hover:text-fg-2"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              onInsert(snippet.content)
              onClose()
            }}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-1.5 text-[11px] font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110"
          >
            <Package size={11} />
            Insert at Cursor
          </button>
        </div>
      </div>
    </div>
  )
}
