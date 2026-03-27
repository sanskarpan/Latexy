'use client'

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Plus, X, Search, Package } from 'lucide-react'
import {
  LATEX_PACKAGES,
  ALL_CATEGORIES,
  CATEGORY_LABELS,
  type PackageCategory,
  type LaTeXPackage,
} from '@/data/latex-packages'
import {
  getInstalledPackages,
  addPackageToPreamble,
  removePackageFromPreamble,
} from '@/lib/latex-preamble'

// ─── Props ────────────────────────────────────────────────────────────────────

interface PackageManagerPanelProps {
  currentLatex: string
  onAddPackage: (newLatex: string, packageName: string) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PackageManagerPanel({
  currentLatex,
  onAddPackage,
}: PackageManagerPanelProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<PackageCategory | 'all'>('all')
  const [expandedPackage, setExpandedPackage] = useState<string | null>(null)

  const installedPackages = useMemo(
    () => new Set(getInstalledPackages(currentLatex)),
    [currentLatex]
  )

  const filteredPackages = useMemo(() => {
    const q = searchQuery.toLowerCase()
    return LATEX_PACKAGES.filter((pkg) => {
      if (selectedCategory !== 'all' && pkg.category !== selectedCategory) return false
      if (!q) return true
      return pkg.name.toLowerCase().includes(q) || pkg.description.toLowerCase().includes(q)
    })
  }, [searchQuery, selectedCategory])

  function handleAdd(pkg: LaTeXPackage) {
    const newLatex = addPackageToPreamble(currentLatex, pkg.name)
    onAddPackage(newLatex, pkg.name)
  }

  function handleRemove(pkgName: string) {
    const newLatex = removePackageFromPreamble(currentLatex, pkgName)
    onAddPackage(newLatex, pkgName)
  }

  function toggleExpand(pkgName: string) {
    setExpandedPackage((prev) => (prev === pkgName ? null : pkgName))
  }

  // Packages installed but not in our curated list (user-added manually)
  const unknownInstalled = useMemo(() => {
    const known = new Set(LATEX_PACKAGES.map((p) => p.name))
    return [...installedPackages].filter((p) => !known.has(p))
  }, [installedPackages])

  const installedCurated = useMemo(
    () => LATEX_PACKAGES.filter((p) => installedPackages.has(p.name)),
    [installedPackages]
  )

  return (
    <div className="flex h-full flex-col overflow-hidden">

      {/* ── Search ── */}
      <div className="shrink-0 space-y-2 border-b border-white/[0.05] p-3">
        <div className="relative">
          <Search
            size={12}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search packages…"
            className="w-full rounded-lg bg-white/[0.04] py-2 pl-7 pr-3 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none ring-1 ring-white/[0.06] focus:ring-violet-500/40"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400"
            >
              <X size={11} />
            </button>
          )}
        </div>

        {/* Category tabs */}
        <div className="flex gap-1 overflow-x-auto pb-0.5 scrollbar-none">
          <CategoryChip
            label="All"
            active={selectedCategory === 'all'}
            onClick={() => setSelectedCategory('all')}
          />
          {ALL_CATEGORIES.map((cat) => (
            <CategoryChip
              key={cat}
              label={CATEGORY_LABELS[cat]}
              active={selectedCategory === cat}
              onClick={() => setSelectedCategory(cat)}
            />
          ))}
        </div>
      </div>

      {/* ── Installed packages strip ── */}
      {(installedCurated.length > 0 || unknownInstalled.length > 0) && !searchQuery && selectedCategory === 'all' && (
        <div className="shrink-0 border-b border-white/[0.05] p-3 space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
            Installed ({installedPackages.size})
          </p>
          <div className="flex flex-wrap gap-1">
            {[...installedCurated, ...unknownInstalled.map((n) => ({ name: n } as LaTeXPackage))].map((pkg) => (
              <span
                key={pkg.name}
                className="flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/20"
              >
                <span className="font-mono">{pkg.name}</span>
                <button
                  onClick={() => handleRemove(pkg.name)}
                  title={`Remove ${pkg.name}`}
                  className="rounded transition hover:text-emerald-100"
                >
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Package list ── */}
      <div className="flex-1 overflow-y-auto">
        {filteredPackages.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <Package size={20} className="text-zinc-700" />
            <p className="text-[11px] text-zinc-600">No packages match your search.</p>
          </div>
        ) : (
          <div className="divide-y divide-white/[0.03]">
            {filteredPackages.map((pkg) => {
              const installed = installedPackages.has(pkg.name)
              const expanded = expandedPackage === pkg.name
              return (
                <div key={pkg.name} className="px-3">
                  {/* Header row */}
                  <div className="flex items-center gap-2 py-2">
                    <button
                      onClick={() => toggleExpand(pkg.name)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      {expanded ? (
                        <ChevronDown size={10} className="shrink-0 text-zinc-600" />
                      ) : (
                        <ChevronRight size={10} className="shrink-0 text-zinc-600" />
                      )}
                      <span className="font-mono text-[12px] text-zinc-200">{pkg.name}</span>
                      <span
                        className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${CATEGORY_BADGE[pkg.category]}`}
                      >
                        {CATEGORY_LABELS[pkg.category]}
                      </span>
                    </button>

                    {installed ? (
                      <button
                        onClick={() => handleRemove(pkg.name)}
                        title="Remove from preamble"
                        className="flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-400 ring-1 ring-emerald-500/20 transition hover:bg-rose-500/10 hover:text-rose-400 hover:ring-rose-500/20"
                      >
                        <X size={9} />
                        Installed
                      </button>
                    ) : (
                      <button
                        onClick={() => handleAdd(pkg)}
                        title="Add to preamble"
                        className="flex shrink-0 items-center gap-1 rounded-md bg-white/[0.04] px-2 py-1 text-[10px] text-zinc-400 ring-1 ring-white/[0.06] transition hover:bg-violet-500/15 hover:text-violet-300 hover:ring-violet-500/25"
                      >
                        <Plus size={9} />
                        Add
                      </button>
                    )}
                  </div>

                  {/* Description (always visible) */}
                  <p className="mb-2 pl-4 text-[11px] leading-relaxed text-zinc-600">
                    {pkg.description}
                  </p>

                  {/* Expanded details */}
                  {expanded && (
                    <div className="mb-2.5 ml-4 space-y-2">
                      {/* Usage */}
                      <div>
                        <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
                          Usage
                        </p>
                        <pre className="overflow-x-auto rounded bg-black/30 p-2 font-mono text-[10px] text-violet-300">
                          {pkg.usage}
                        </pre>
                      </div>

                      {/* Example */}
                      {pkg.example && (
                        <div>
                          <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
                            Example
                          </p>
                          <pre className="overflow-x-auto rounded bg-black/30 p-2 font-mono text-[10px] text-zinc-400">
                            {pkg.example}
                          </pre>
                        </div>
                      )}

                      {/* Note */}
                      {pkg.note && (
                        <p className="rounded bg-amber-500/5 px-2 py-1.5 text-[10px] leading-relaxed text-amber-400/80 ring-1 ring-amber-500/15">
                          {pkg.note}
                        </p>
                      )}

                      {/* Conflict warning */}
                      {pkg.conflicts && pkg.conflicts.some((c) => installedPackages.has(c)) && (
                        <p className="rounded bg-rose-500/5 px-2 py-1.5 text-[10px] leading-relaxed text-rose-400 ring-1 ring-rose-500/15">
                          Conflicts with installed:{' '}
                          {pkg.conflicts.filter((c) => installedPackages.has(c)).join(', ')}
                        </p>
                      )}

                      {/* Related */}
                      {pkg.related && pkg.related.length > 0 && (
                        <p className="text-[10px] text-zinc-700">
                          Related:{' '}
                          {pkg.related.map((r) => (
                            <code key={r} className="font-mono text-zinc-500">
                              {r}{' '}
                            </code>
                          ))}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── Footer count ── */}
      <div className="shrink-0 border-t border-white/[0.04] px-3 py-2">
        <p className="text-[10px] text-zinc-700">
          {filteredPackages.length} package{filteredPackages.length === 1 ? '' : 's'}
          {searchQuery || selectedCategory !== 'all' ? ' matching' : ' in database'}
          {installedPackages.size > 0 && (
            <span className="ml-2 text-emerald-500/60">
              · {installedPackages.size} installed
            </span>
          )}
        </p>
      </div>
    </div>
  )
}

// ─── CategoryChip ─────────────────────────────────────────────────────────────

function CategoryChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 rounded-md px-2 py-1 text-[10px] font-medium transition ${
        active
          ? 'bg-violet-500/20 text-violet-200 ring-1 ring-violet-400/25'
          : 'text-zinc-600 hover:text-zinc-300'
      }`}
    >
      {label}
    </button>
  )
}

// ─── Category badge colors ────────────────────────────────────────────────────

const CATEGORY_BADGE: Record<PackageCategory, string> = {
  layout: 'bg-sky-500/10 text-sky-400',
  fonts: 'bg-purple-500/10 text-purple-400',
  math: 'bg-blue-500/10 text-blue-400',
  tables: 'bg-teal-500/10 text-teal-400',
  graphics: 'bg-orange-500/10 text-orange-400',
  colors: 'bg-rose-500/10 text-rose-400',
  links: 'bg-cyan-500/10 text-cyan-400',
  bibliography: 'bg-amber-500/10 text-amber-400',
  utils: 'bg-zinc-500/10 text-zinc-400',
}
