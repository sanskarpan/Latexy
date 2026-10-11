'use client'

import { useMemo, useRef, useState } from 'react'
import { FileText, Plus } from 'lucide-react'
import { addVisualSectionContent, appendVisualSection, projectVisualResume, updateVisualField, type VisualField } from '@/lib/wysiwyg/visual-projection'
import { FIRST_USE_RESUME_TEMPLATE } from '@/lib/first-use-resume'

export interface VisualResumeEditorProps {
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
}

function SectionName({ field, onCommit }: { field: VisualField; onCommit: (text: string) => void }) {
  const [draft, setDraft] = useState(field.value)
  return <input aria-label={`${field.section}: section name`} value={draft} onChange={(event) => setDraft(event.target.value)}
    onBlur={() => { if (draft !== field.value) onCommit(draft) }}
    onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') setDraft(field.value) }}
    placeholder="Section name" className="w-full rounded border border-transparent bg-transparent px-1 py-1 font-display text-xl font-semibold text-fg outline-none hover:border-line focus:border-accent" />
}

/** Editable content on a document surface. The PDF remains the layout authority. */
export default function VisualResumeEditor({ value, onChange, readOnly = false }: VisualResumeEditorProps) {
  const projection = useMemo(() => projectVisualResume(value), [value])
  const sections = useMemo(() => {
    const labels = new Map<string, string>()
    for (const field of projection.fields) if (!labels.has(field.sectionId)) labels.set(field.sectionId, field.section)
    return Array.from(labels, ([id, label]) => ({ id, label }))
  }, [projection])
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  function change(field: VisualField, text: string) {
    if (!readOnly) onChange(updateVisualField(value, field, text))
  }

  function addSection() {
    if (!readOnly) onChange(appendVisualSection(value))
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg" data-testid="visual-resume-editor">
      <div className="shrink-0 border-b border-line px-5 py-4">
        <p className="text-sm font-semibold text-fg">{readOnly ? 'Résumé content' : 'Make this résumé yours'}</p>
        <p className="mt-1 text-xs leading-relaxed text-fg-2">{readOnly ? 'Review the supported text below. Your PDF contains the final layout.' : 'Click any text to edit. Update the preview when you’re ready to see the final layout.'}</p>
        {!readOnly && <nav aria-label="Resume sections" className="mt-3 flex flex-wrap gap-1.5">
          {sections.map((section) => (
            <button key={section.id} type="button" onClick={() => sectionRefs.current[section.id]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })}
              className="rounded-full border border-line px-3 py-1.5 text-xs text-fg-2 transition hover:border-accent hover:bg-surface-2">
              {section.label}
            </button>
          ))}
        </nav>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {projection.unsupportedBlocks > 0 && (
          <p role="status" className="mx-auto mb-4 max-w-2xl rounded-xl border border-line bg-surface px-4 py-3 text-xs leading-relaxed text-fg-2">
            Some custom layout elements are preserved and appear in your PDF preview. You can edit the supported content below; advanced layout changes are available in Source mode.
          </p>
        )}
        {projection.fields.length ? (
          <article aria-label="Editable resume content" className="mx-auto max-w-2xl rounded-sm border border-line bg-surface p-5 shadow-sm sm:p-8">
            {sections.map((section) => {
              const heading = projection.fields.find((field) => field.sectionId === section.id && field.kind === 'heading')
              const addition = heading ? addVisualSectionContent(value, heading) : null
              return (
              <section key={section.id} ref={(element) => { sectionRefs.current[section.id] = element }} className="mb-8 space-y-4 last:mb-0" aria-label={section.label}>
                <div className="border-b border-line pb-3">
                  {heading && !readOnly ? <SectionName key={heading.value} field={heading} onCommit={(text) => change(heading, text)} /> : <h2 className="font-display text-xl font-semibold text-fg">{section.label}</h2>}
                </div>
                {projection.fields.filter((field) => field.sectionId === section.id && field.kind !== 'heading').map((field) => (
                  <label key={field.id} className="block">
                    <span className="mb-1 block text-xs font-medium text-fg-3">{field.label}</span>
                    <div className="flex gap-2">
                      {field.kind === 'bullet' && <span aria-hidden="true" className="pt-2 text-fg-3">•</span>}
                      <textarea aria-label={`${section.label}: ${field.label}`} value={field.value} readOnly={readOnly}
                        rows={field.value.length > 110 || field.value.includes('\n') ? 3 : 1}
                        onChange={(event) => change(field, event.target.value)}
                        className={`w-full resize-y rounded-md border border-transparent bg-transparent px-2 py-2 text-sm leading-relaxed text-fg outline-none transition hover:border-line focus:border-accent focus:bg-bg focus:ring-2 focus:ring-accent/15 ${field.kind === 'heading' ? 'font-semibold' : ''}`} />
                    </div>
                  </label>
                ))}
                {!readOnly && addition && addition.source !== value && <button type="button" onClick={() => onChange(addition.source)} className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-fg-2 transition hover:bg-surface-2 hover:text-fg"><Plus size={12} />Add {addition.kind}</button>}
              </section>
            )})}
          </article>
        ) : (
          <div className="mx-auto max-w-md py-12 text-center">
            <FileText size={28} className="mx-auto text-fg-3" />
            <h2 className="mt-4 text-lg font-semibold text-fg">This layout needs the advanced editor</h2>
            <p className="mt-2 text-sm leading-relaxed text-fg-2">{value.trim() ? 'Your document is safely preserved. Use Source mode to edit this custom layout, or start with a résumé template for visual editing.' : 'Start with an example, then replace the details with your own.'}</p>
            {!readOnly && !value.trim() && <button type="button" onClick={() => onChange(FIRST_USE_RESUME_TEMPLATE)} className="mt-5 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-accent-fg">Start with an example</button>}
          </div>
        )}
        {!readOnly && projection.fields.length > 0 && (
          <button type="button" onClick={addSection} className="mx-auto mt-5 flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-xs font-medium text-fg-2 transition hover:border-accent hover:text-fg">
            <Plus size={14} /> Add a section
          </button>
        )}
      </div>
    </div>
  )
}
