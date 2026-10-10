'use client'

import { Contrast } from 'lucide-react'
import { useTheme } from './ThemeProvider'

export default function ContrastToggle({ className = '' }: { className?: string }) {
  const { ready, contrast, toggleContrast } = useTheme()
  const active = contrast === 'high'

  return (
    <button
      type="button"
      disabled={!ready}
      onClick={toggleContrast}
      aria-label={active ? 'Turn off high contrast mode' : 'Turn on high contrast mode'}
      aria-pressed={active}
      title={active ? 'Use standard contrast' : 'Use high contrast'}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-line transition disabled:cursor-wait disabled:opacity-60 ${active ? 'bg-accent text-accent-fg hover:border-accent hover:text-accent-fg' : 'text-fg-2 hover:border-accent hover:text-accent-strong'} ${className}`}
    >
      <Contrast size={15} aria-hidden="true" />
    </button>
  )
}
