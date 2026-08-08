'use client'

import { useEffect, useRef } from 'react'
import type { LogLine } from '@/hooks/useJobStream'

interface LogViewerProps {
  lines: LogLine[]
  maxHeight?: string
  className?: string
  /** Show line numbers (default true) */
  showLineNumbers?: boolean
}

export default function LogViewer({
  lines,
  maxHeight = '280px',
  className = '',
  showLineNumbers = true,
}: LogViewerProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom whenever new lines arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'auto' })
  }, [lines.length])

  if (lines.length === 0) {
    return (
      <div
        className={`flex items-center justify-center rounded-[var(--radius-md)] bg-[var(--code-bg)] text-sm font-mono text-fg-3 ${className}`}
        style={{ minHeight: '80px' }}
      >
        No log output yet
      </div>
    )
  }

  return (
    <div
      className={`scrollbar-subtle overflow-y-auto rounded-[var(--radius-md)] bg-[var(--code-bg)] font-mono text-xs text-fg ${className}`}
      style={{ maxHeight }}
    >
      <div className="p-3 space-y-0.5">
        {lines.map((entry, i) => (
          <div
            key={`${i}-${entry.source}-${entry.line?.substring(0, 20) ?? ''}`}
            className={`leading-5 whitespace-pre-wrap break-all ${
              entry.is_error ? 'text-err' : 'text-fg-2'
            }`}
          >
            {showLineNumbers && (
              <span className="mr-2 inline-block w-8 select-none text-right text-fg-3">
                {i + 1}
              </span>
            )}
            {entry.line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
