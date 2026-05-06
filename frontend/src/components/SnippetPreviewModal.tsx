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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose()
      }}
    >
      <div className="flex w-full max-w-2xl flex-col rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-white/[0.06] p-4">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              {snippet.is_official && (
                <Star size={12} className="text-amber-400" fill="currentColor" />
              )}
              <h2 className="text-[13px] font-bold text-zinc-100">{snippet.title}</h2>
            </div>
            <p className="mt-0.5 text-[11px] text-zinc-500">{snippet.description}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-zinc-600">
              <span className="rounded bg-white/[0.05] px-1.5 py-0.5 capitalize">{snippet.category}</span>
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
                    className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[9px] text-violet-400"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 rounded p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        {/* Code preview */}
        <div className="min-h-0 flex-1 overflow-auto">
          <pre className="p-4 text-[11px] leading-relaxed text-zinc-300 font-mono whitespace-pre-wrap break-words">
            {snippet.content}
          </pre>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-white/[0.06] p-4">
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-[11px] text-zinc-500 transition hover:text-zinc-300"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              onInsert(snippet.content)
              onClose()
            }}
            className="flex items-center gap-1.5 rounded-lg bg-violet-500/20 px-4 py-1.5 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-400/30 transition hover:bg-violet-500/30"
          >
            <Package size={11} />
            Insert at Cursor
          </button>
        </div>
      </div>
    </div>
  )
}
