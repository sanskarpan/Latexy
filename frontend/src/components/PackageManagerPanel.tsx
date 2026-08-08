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
      <div className="shrink-0 space-y-2 border-b border-line p-3">
        <div className="relative">
          <Search
            size={12}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search packages…"
            className="w-full rounded-[var(--radius-md)] bg-surface-2 py-2 pl-7 pr-3 text-[12px] text-fg placeholder-fg-3 outline-none ring-1 ring-line focus:ring-accent"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-3 hover:text-fg-2"
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
        <div className="shrink-0 border-b border-line p-3 space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
            Installed ({installedPackages.size})
          </p>
          <div className="flex flex-wrap gap-1">
            {installedCurated.map((pkg) => (
              <InstalledChip key={pkg.name} name={pkg.name} onRemove={handleRemove} />
            ))}
            {unknownInstalled.map((name) => (
              <InstalledChip key={name} name={name} onRemove={handleRemove} />
            ))}
          </div>
        </div>
      )}

      {/* ── Package list ── */}
      <div className="flex-1 overflow-y-auto">
        {filteredPackages.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <Package size={20} className="text-fg-3" />
            <p className="text-[11px] text-fg-3">No packages match your search.</p>
          </div>
        ) : (
          <div className="divide-y divide-line">
            {filteredPackages.map((pkg) => {
              const installed = installedPackages.has(pkg.name)
              const expanded = expandedPackage === pkg.name
              return (
                <div key={pkg.name} className="px-3">
                  {/* Header row */}
                  <div className="flex items-center gap-2 py-2">
                    <button
                      onClick={() => toggleExpand(pkg.name)}
                      aria-expanded={expanded}
                      aria-label={`${expanded ? 'Collapse' : 'Expand'} ${pkg.name} details`}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      {expanded ? (
                        <ChevronDown size={10} className="shrink-0 text-fg-3" />
                      ) : (
                        <ChevronRight size={10} className="shrink-0 text-fg-3" />
                      )}
                      <span className="font-mono text-[12px] text-fg">{pkg.name}</span>
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
                        className="flex shrink-0 items-center gap-1 rounded-[var(--radius-md)] bg-surface-2 px-2 py-1 text-[10px] text-ok ring-1 ring-line transition hover:text-err"
                      >
                        <X size={9} />
                        Installed
                      </button>
                    ) : (
                      <button
                        onClick={() => handleAdd(pkg)}
                        title="Add to preamble"
                        className="flex shrink-0 items-center gap-1 rounded-[var(--radius-md)] bg-surface-2 px-2 py-1 text-[10px] text-fg-2 ring-1 ring-line transition hover:bg-accent-soft hover:text-accent-strong hover:ring-accent"
                      >
                        <Plus size={9} />
                        Add
                      </button>
                    )}
                  </div>

                  {/* Description (always visible) */}
                  <p className="mb-2 pl-4 text-[11px] leading-relaxed text-fg-3">
                    {pkg.description}
                  </p>

                  {/* Expanded details */}
                  {expanded && (
                    <div className="mb-2.5 ml-4 space-y-2">
                      {/* Usage */}
                      <div>
                        <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                          Usage
                        </p>
                        <pre className="overflow-x-auto rounded bg-surface-2 p-2 font-mono text-[10px] text-accent-strong">
                          {pkg.usage}
                        </pre>
                      </div>

                      {/* Example */}
                      {pkg.example && (
                        <div>
                          <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                            Example
                          </p>
                          <pre className="overflow-x-auto rounded bg-surface-2 p-2 font-mono text-[10px] text-fg-2">
                            {pkg.example}
                          </pre>
                        </div>
                      )}

                      {/* Note */}
                      {pkg.note && (
                        <p className="rounded bg-surface-2 px-2 py-1.5 text-[10px] leading-relaxed text-warn ring-1 ring-line">
                          {pkg.note}
                        </p>
                      )}

                      {/* Conflict warning */}
                      {pkg.conflicts && pkg.conflicts.some((c) => installedPackages.has(c)) && (
                        <p className="rounded bg-surface-2 px-2 py-1.5 text-[10px] leading-relaxed text-err ring-1 ring-line">
                          Conflicts with installed:{' '}
                          {pkg.conflicts.filter((c) => installedPackages.has(c)).join(', ')}
                        </p>
                      )}

                      {/* Related */}
                      {pkg.related && pkg.related.length > 0 && (
                        <p className="text-[10px] text-fg-3">
                          Related:{' '}
                          {pkg.related.map((r) => (
                            <code key={r} className="font-mono text-fg-3">
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
      <div className="shrink-0 border-t border-line px-3 py-2">
        <p className="text-[10px] text-fg-3">
          {filteredPackages.length} package{filteredPackages.length === 1 ? '' : 's'}
          {searchQuery || selectedCategory !== 'all' ? ' matching' : ' in database'}
          {installedPackages.size > 0 && (
            <span className="ml-2 text-ok">
              · {installedPackages.size} installed
            </span>
          )}
        </p>
      </div>
    </div>
  )
}

// ─── InstalledChip ────────────────────────────────────────────────────────────

function InstalledChip({
  name,
  onRemove,
}: {
  name: string
  onRemove: (name: string) => void
}) {
  return (
    <span className="flex items-center gap-1 rounded-[var(--radius-md)] bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-ok ring-1 ring-line">
      <span className="font-mono">{name}</span>
      <button
        onClick={() => onRemove(name)}
        title={`Remove ${name}`}
        className="rounded transition hover:text-err"
      >
        <X size={9} />
      </button>
    </span>
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
      className={`shrink-0 rounded-[var(--radius-md)] px-2 py-1 text-[10px] font-medium transition ${
        active
          ? 'bg-accent-soft text-accent-strong ring-1 ring-accent'
          : 'text-fg-3 hover:text-fg'
      }`}
    >
      {label}
    </button>
  )
}

// ─── Category badge colors ────────────────────────────────────────────────────

const CATEGORY_BADGE: Record<PackageCategory, string> = {
  layout: 'bg-surface-2 text-fg-3',
  fonts: 'bg-surface-2 text-fg-3',
  math: 'bg-surface-2 text-fg-3',
  tables: 'bg-surface-2 text-fg-3',
  graphics: 'bg-surface-2 text-fg-3',
  colors: 'bg-surface-2 text-fg-3',
  links: 'bg-surface-2 text-fg-3',
  bibliography: 'bg-surface-2 text-fg-3',
  utils: 'bg-surface-2 text-fg-3',
}
