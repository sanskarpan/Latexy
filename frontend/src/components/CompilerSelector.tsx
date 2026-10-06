'use client'

import { useState, useRef, useEffect, useId, useCallback } from 'react'
import { ChevronDown, Cpu } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type LatexCompiler } from '@/lib/api-client'

interface CompilerOption {
  id: LatexCompiler
  label: string
  description: string
}

const COMPILER_OPTIONS: CompilerOption[] = [
  {
    id: 'pdflatex',
    label: 'pdfLaTeX',
    description: 'Standard (fastest, widest compatibility)',
  },
  {
    id: 'xelatex',
    label: 'XeLaTeX',
    description: 'Unicode + custom fonts via fontspec',
  },
  {
    id: 'lualatex',
    label: 'LuaLaTeX',
    description: 'Modern engine with Lua scripting',
  },
]

interface CompilerSelectorProps {
  resumeId: string
  current: LatexCompiler
  onChange: (compiler: LatexCompiler) => void
  disabled?: boolean
}

export default function CompilerSelector({
  resumeId,
  current,
  onChange,
  disabled = false,
}: CompilerSelectorProps) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [flipUp, setFlipUp] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const currentOption = COMPILER_OPTIONS.find((o) => o.id === current) ?? COMPILER_OPTIONS[0]

  const closeMenu = useCallback(() => {
    setOpen(false)
    requestAnimationFrame(() => triggerRef.current?.focus())
  }, [])

  useEffect(() => {
    if (!open) return
    const frame = requestAnimationFrame(() => {
      const options = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])
      const selected = options.find((option) => option.getAttribute('aria-checked') === 'true') ?? options[0]
      selected?.focus()
    })
    return () => cancelAnimationFrame(frame)
  }, [open])

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (open && ref.current && !ref.current.contains(e.target as Node)) {
        closeMenu()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [closeMenu, open])

  const handleSelect = async (compiler: LatexCompiler) => {
    if (compiler === current) { closeMenu(); return }
    closeMenu()
    setSaving(true)
    try {
      await apiClient.updateResumeSettings(resumeId, { compiler })
      onChange(compiler)
      const option = COMPILER_OPTIONS.find((o) => o.id === compiler)
      toast.success(`Compiler changed to ${option?.label ?? compiler} — next compile will use it`)
    } catch {
      toast.error('Failed to update compiler preference')
    } finally {
      setSaving(false)
    }
  }

  const toggleOpen = () => {
    if (disabled || saving) return
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      const spaceAbove = rect.top
      // Flip up when there isn't enough room below and there's more room above.
      setFlipUp(spaceBelow < 260 && spaceAbove > spaceBelow)
    }
    setOpen((v) => !v)
  }

  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    if (!open) toggleOpen()
  }

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const options = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])
    if (!options.length) return
    const currentIndex = options.indexOf(document.activeElement as HTMLButtonElement)
    let nextIndex: number | null = null
    if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1 + options.length) % options.length
    if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + options.length) % options.length
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = options.length - 1
    if (nextIndex !== null) {
      event.preventDefault()
      options[nextIndex]?.focus()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      closeMenu()
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={toggleOpen}
        onKeyDown={handleTriggerKeyDown}
        disabled={disabled || saving}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={menuId}
        title="LaTeX compiler engine"
        className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium transition ${
          open
            ? 'bg-surface-2 text-fg'
            : 'text-fg-3 hover:bg-surface-2 hover:text-fg-2'
        } disabled:opacity-40`}
      >
        <Cpu size={11} className={current !== 'pdflatex' ? 'text-accent-strong' : undefined} />
        <span className={current !== 'pdflatex' ? 'text-accent-strong' : undefined}>
          {currentOption.label}
        </span>
        <ChevronDown size={10} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div ref={menuRef} id={menuId} role="menu" aria-label="LaTeX compiler options" onKeyDown={handleMenuKeyDown} className={`absolute right-0 z-50 max-h-[min(20rem,calc(100vh-6rem))] w-56 overflow-y-auto rounded-[var(--radius-md)] border border-line bg-bg py-1 shadow-[var(--shadow-2)] ${
          flipUp ? 'bottom-full mb-1' : 'top-full mt-1'
        }`}>
          {COMPILER_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              role="menuitemradio"
              aria-checked={option.id === current}
              tabIndex={option.id === current ? 0 : -1}
              onClick={() => handleSelect(option.id)}
              className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition hover:bg-surface-2 ${
                option.id === current ? 'text-accent-strong' : 'text-fg-2'
              }`}
            >
              <span className="text-[12px] font-medium">{option.label}</span>
              <span className="text-[10px] text-fg-3">{option.description}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
