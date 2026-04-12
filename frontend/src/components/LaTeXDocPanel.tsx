'use client'

import { useState, useMemo, useEffect } from 'react'
import { Search, ChevronLeft } from 'lucide-react'
import { LATEX_DOCS, LATEX_DOCS_MAP, LATEX_DOCS_BY_CATEGORY, type LaTeXDoc } from '@/lib/latex-docs'

interface LaTeXDocPanelProps {
  command?: string
  mode?: 'command' | 'reference'
}

const CATEGORY_LABELS: Record<string, string> = {
  formatting: 'Formatting',
  sectioning: 'Sectioning',
  environments: 'Environments',
  math: 'Math',
  spacing: 'Spacing',
  graphics: 'Graphics & Refs',
  misc: 'Miscellaneous',
}

const CATEGORY_ORDER: LaTeXDoc['category'][] = [
  'formatting',
  'sectioning',
  'environments',
  'math',
  'spacing',
  'graphics',
  'misc',
]

function CommandDetail({
  doc,
  onBack,
  onNavigate,
}: {
  doc: LaTeXDoc
  onBack: () => void
  onNavigate: (cmd: string) => void
}) {
  return (
    <div className="flex h-full flex-col overflow-auto">
      {/* Header */}
      <div className="shrink-0 border-b border-white/[0.05] px-3 py-2">
        <button
          onClick={onBack}
          className="mb-2 flex items-center gap-1 text-[11px] text-zinc-500 transition hover:text-zinc-300"
        >
          <ChevronLeft size={12} />
          Back to reference
        </button>
        <div className="font-mono text-base font-semibold text-orange-400">{doc.command}</div>
        <div className="mt-0.5 font-mono text-xs text-zinc-500">{doc.signature}</div>
      </div>

      {/* Body */}
      <div className="flex-1 space-y-4 overflow-auto p-3">
        {/* Description */}
        <p className="text-xs leading-relaxed text-zinc-300">{doc.description}</p>

        {/* Parameters */}
        {doc.parameters.length > 0 && (
          <div>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              Parameters
            </div>
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-[10px] text-zinc-600">
                  <th className="pb-1 pr-2 font-medium">Name</th>
                  <th className="pb-1 pr-2 font-medium">Required</th>
                  <th className="pb-1 font-medium">Description</th>
                </tr>
              </thead>
              <tbody>
                {doc.parameters.map((p) => (
                  <tr key={p.name} className="border-b border-white/[0.03]">
                    <td className="py-1 pr-2 font-mono text-orange-300">{p.name}</td>
                    <td className="py-1 pr-2">
                      {p.required ? (
                        <span className="rounded bg-orange-500/15 px-1 py-0.5 text-[9px] font-semibold text-orange-300">
                          yes
                        </span>
                      ) : (
                        <span className="rounded bg-zinc-800 px-1 py-0.5 text-[9px] font-semibold text-zinc-500">
                          no
                        </span>
                      )}
                    </td>
                    <td className="py-1 text-zinc-400">{p.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Examples */}
        {doc.examples.length > 0 && (
          <div>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              Examples
            </div>
            <div className="space-y-3">
              {doc.examples.map((ex, i) => (
                <div key={i}>
                  <pre className="rounded bg-zinc-950 p-2 font-mono text-[11px] text-orange-200 whitespace-pre-wrap break-words">
                    {ex.code}
                  </pre>
                  {ex.description && (
                    <p className="mt-1 text-[11px] text-zinc-500">{ex.description}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Packages */}
        <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
            Requires
          </div>
          {doc.packages.length === 0 ? (
            <span className="rounded bg-zinc-800/60 px-2 py-0.5 text-[11px] text-zinc-400">
              Core LaTeX
            </span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {doc.packages.map((pkg) => (
                <span
                  key={pkg}
                  className="rounded bg-violet-500/15 px-2 py-0.5 font-mono text-[11px] text-violet-300 ring-1 ring-violet-500/20"
                >
                  {pkg}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* See also */}
        {doc.seealso.length > 0 && (
          <div>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              See Also
            </div>
            <div className="flex flex-wrap gap-1">
              {doc.seealso.map((cmd) => (
                <button
                  key={cmd}
                  onClick={() => onNavigate(cmd)}
                  className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-[11px] text-zinc-300 transition hover:bg-zinc-700 hover:text-orange-300"
                >
                  {cmd}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function NotFound({ command, onBack }: { command: string; onBack: () => void }) {
  return (
    <div className="flex h-full flex-col p-3">
      <button
        onClick={onBack}
        className="mb-3 flex items-center gap-1 text-[11px] text-zinc-500 transition hover:text-zinc-300"
      >
        <ChevronLeft size={12} />
        Back to reference
      </button>
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
        <span className="font-mono text-sm text-zinc-500">{command}</span>
        <p className="text-xs text-zinc-600">No documentation found for this command.</p>
      </div>
    </div>
  )
}

export default function LaTeXDocPanel({ command, mode = 'reference' }: LaTeXDocPanelProps) {
  const [activeCommand, setActiveCommand] = useState<string | null>(command ?? null)
  const [query, setQuery] = useState('')

  // Sync when command prop changes (e.g. from right-click)
  useEffect(() => {
    if (command !== undefined) {
      setActiveCommand(command)
    }
  }, [command])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return LATEX_DOCS
    return LATEX_DOCS.filter(
      (doc) =>
        doc.command.toLowerCase().includes(q) ||
        doc.description.toLowerCase().includes(q) ||
        doc.signature.toLowerCase().includes(q),
    )
  }, [query])

  // Group filtered results by category in the defined order
  const grouped = useMemo(() => {
    const map: Partial<Record<LaTeXDoc['category'], LaTeXDoc[]>> = {}
    for (const doc of filtered) {
      if (!map[doc.category]) map[doc.category] = []
      map[doc.category]!.push(doc)
    }
    return map
  }, [filtered])

  // ── Command detail view ──
  if (activeCommand !== null) {
    const doc = LATEX_DOCS_MAP.get(activeCommand)
    if (!doc) {
      return (
        <NotFound
          command={activeCommand}
          onBack={() => setActiveCommand(null)}
        />
      )
    }
    return (
      <CommandDetail
        doc={doc}
        onBack={() => setActiveCommand(null)}
        onNavigate={(cmd) => setActiveCommand(cmd)}
      />
    )
  }

  // ── Reference list view ──
  return (
    <div className="flex h-full flex-col">
      {/* Search */}
      <div className="shrink-0 border-b border-white/[0.05] p-3">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search commands…"
            className="w-full rounded-md border border-white/[0.06] bg-white/[0.03] py-1.5 pl-7 pr-3 text-xs text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-white/[0.12]"
          />
        </div>
        {query && (
          <p className="mt-1.5 text-[10px] text-zinc-600">
            {filtered.length} result{filtered.length !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      {/* List */}
      <div className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-xs text-zinc-600">
            No commands match &ldquo;{query}&rdquo;
          </div>
        ) : (
          CATEGORY_ORDER.map((cat) => {
            const docs = grouped[cat]
            if (!docs || docs.length === 0) return null
            return (
              <div key={cat}>
                {/* Sticky category header */}
                <div className="sticky top-0 z-10 border-b border-white/[0.04] bg-zinc-950/90 px-3 py-1.5 backdrop-blur-sm">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
                    {CATEGORY_LABELS[cat] ?? cat}
                  </span>
                </div>
                {docs.map((doc) => (
                  <button
                    key={doc.command}
                    onClick={() => setActiveCommand(doc.command)}
                    className="flex w-full flex-col items-start border-b border-white/[0.03] px-3 py-2 text-left transition hover:bg-white/[0.03]"
                  >
                    <span className="font-mono text-xs font-medium text-orange-400">
                      {doc.command}
                    </span>
                    <span className="mt-0.5 line-clamp-1 text-[11px] text-zinc-500">
                      {doc.description}
                    </span>
                  </button>
                ))}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
