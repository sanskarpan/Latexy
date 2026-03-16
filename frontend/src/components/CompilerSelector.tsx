'use client'

import { useState, useRef, useEffect } from 'react'
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
  const ref = useRef<HTMLDivElement>(null)

  const currentOption = COMPILER_OPTIONS.find((o) => o.id === current) ?? COMPILER_OPTIONS[0]

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSelect = async (compiler: LatexCompiler) => {
    if (compiler === current) { setOpen(false); return }
    setOpen(false)
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

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => !disabled && !saving && setOpen((v) => !v)}
        disabled={disabled || saving}
        title="LaTeX compiler engine"
        className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition ${
          open
            ? 'bg-white/[0.07] text-zinc-200'
            : 'text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300'
        } disabled:opacity-40`}
      >
        <Cpu size={11} className={current !== 'pdflatex' ? 'text-cyan-400' : undefined} />
        <span className={current !== 'pdflatex' ? 'text-cyan-300' : undefined}>
          {currentOption.label}
        </span>
        <ChevronDown size={10} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-white/10 bg-zinc-950 py-1 shadow-xl">
          {COMPILER_OPTIONS.map((option) => (
            <button
              key={option.id}
              onClick={() => handleSelect(option.id)}
              className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition hover:bg-white/[0.05] ${
                option.id === current ? 'text-cyan-300' : 'text-zinc-300'
              }`}
            >
              <span className="text-[12px] font-medium">{option.label}</span>
              <span className="text-[10px] text-zinc-600">{option.description}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
