'use client'

import type { BuilderPreviewResponse, StructuredResume } from '@/lib/api-client'

interface BuilderPreviewProps {
  title: string
  structured: StructuredResume
  preview: BuilderPreviewResponse | null
  templateFamily: string
  completenessScore: number
  pageEstimate: number
  warnings: string[]
}

function headerAccent(templateFamily: string) {
  switch (templateFamily) {
    case 'executive':
      return 'from-black/10 via-black/[0.04] to-transparent'
    case 'ats':
      return 'from-[var(--accent-soft)] via-[var(--accent-soft)] to-transparent'
    case 'minimal':
      return 'from-[var(--accent-soft)] via-[var(--accent-soft)] to-transparent'
    default:
      return 'from-[var(--accent-soft)] via-[var(--accent-soft)] to-transparent'
  }
}

function statTone(value: number) {
  if (value >= 85) return 'text-ok border-ok bg-surface-2'
  if (value >= 65) return 'text-warn border-warn bg-surface-2'
  return 'text-err border-err bg-surface-2'
}

export default function BuilderPreview({
  title,
  structured,
  preview,
  templateFamily,
  completenessScore,
  pageEstimate,
  warnings,
}: BuilderPreviewProps) {
  const basics = structured.basics
  const sectionCount = preview?.sections.length ?? 0
  const activeSections = structured.section_order.filter(section => !structured.hidden_sections.includes(section))

  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface sticky top-24 overflow-hidden">
      <div className="border-b border-line px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-[0.24em] text-fg-3">Live Preview</p>
            <p className="mt-2 text-sm text-fg-2">
              Render-safe snapshot of the structured resume that will drive generated LaTeX.
            </p>
          </div>
          <div className={`rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.18em] ${statTone(completenessScore)}`}>
            {completenessScore}% ready
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Template</p>
            <p className="mt-2 text-sm font-semibold text-fg">{templateFamily}</p>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Page Target</p>
            <p className="mt-2 text-sm font-semibold text-fg">{pageEstimate} page{pageEstimate === 1 ? '' : 's'}</p>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Visible Sections</p>
            <p className="mt-2 text-sm font-semibold text-fg">{sectionCount || activeSections.length}</p>
          </div>
        </div>

        {activeSections.length ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {activeSections.map(section => (
              <span
                key={section}
                className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] text-fg-2"
              >
                {section.replace('_', ' ')}
              </span>
            ))}
          </div>
        ) : null}

        {!!warnings.length && (
          <div className="mt-4 rounded-[var(--radius-lg)] border border-warn bg-surface-2 px-4 py-3">
            <p className="text-[10px] uppercase tracking-[0.18em] text-warn">Preview warnings</p>
            <ul className="mt-2 space-y-1 text-xs text-fg-2">
              {warnings.slice(0, 2).map(warning => (
                <li key={warning}>• {warning}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-5 rounded-[var(--radius-lg)] border border-line bg-[#f7f4ef] p-6 text-[#171717] shadow-[var(--shadow-2)]">
          <div className={`border-b border-black/8 bg-gradient-to-r ${headerAccent(templateFamily)} pb-4`}>
            <h2 className="text-2xl font-semibold tracking-tight text-[#111111]">
              {basics.name || title || 'Untitled Resume'}
            </h2>
            {basics.label ? <p className="mt-1 text-sm text-[#434343]">{basics.label}</p> : null}
            <p className="mt-2 text-xs text-[#5a5a5a]">
              {[basics.email, basics.phone, basics.location, basics.website, basics.linkedin, basics.github]
                .filter(Boolean)
                .join('  •  ') || 'Contact details will appear here'}
            </p>
          </div>

          <div className="mt-5 space-y-5">
            {preview?.sections.length ? (
              preview.sections.map(section => (
                <section key={section.key}>
                  <h3 className="border-b border-black/10 pb-1 text-xs font-semibold uppercase tracking-[0.18em] text-[#5b5b5b]">
                    {section.title}
                  </h3>
                  <div className="mt-3 space-y-3 text-sm leading-6 text-[#1f1f1f]">
                    {section.items.map((item, idx) => {
                      if (typeof item === 'string') {
                        return <p key={`${section.key}-${idx}`}>{item}</p>
                      }
                      const row = item as { title?: string; meta?: string; bullets?: string[] }
                      return (
                        <div key={`${section.key}-${idx}`} className="space-y-1.5">
                          {row.title ? <p className="font-semibold text-[#111111]">{row.title}</p> : null}
                          {row.meta ? <p className="text-xs uppercase tracking-[0.12em] text-[#686868]">{row.meta}</p> : null}
                          {row.bullets?.length ? (
                            <ul className="list-disc space-y-1 pl-5 text-[#262626]">
                              {row.bullets.map((bullet, bulletIdx) => (
                                <li key={`${section.key}-${idx}-${bulletIdx}`}>{bullet}</li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                </section>
              ))
            ) : (
              <div className="rounded-[var(--radius-lg)] border border-dashed border-black/10 bg-white/50 px-4 py-6 text-center text-sm text-[#696969]">
                Start filling the builder to generate a live preview.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
