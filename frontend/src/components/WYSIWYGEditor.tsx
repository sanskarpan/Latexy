'use client'

/**
 * WYSIWYG Resume Editor (Feature 78).
 *
 * Renders a ResumeDoc as an editable form UI.
 * Each section is shown with an "Add entry" button.
 * Each entry is an inline form card with the relevant fields.
 */

import { useState } from 'react'
import { AlertTriangle, Plus, Trash2, GripVertical } from 'lucide-react'
import type { Entry, EntryType, ResumeDoc, Section } from '@/lib/wysiwyg/document-model'

// ── Field input ───────────────────────────────────────────────────────────────

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  multiline?: boolean
}) {
  const cls =
    'w-full rounded border border-white/[0.08] bg-black/30 px-2 py-1 text-[11px] text-zinc-200 outline-none placeholder:text-zinc-700 focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20'
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[9px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
        {label}
      </label>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={2}
          className={cls}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cls}
        />
      )}
    </div>
  )
}

// ── Entry card ────────────────────────────────────────────────────────────────

function EntryCard({
  entry,
  onChange,
  onRemove,
}: {
  entry: Entry
  onChange: (e: Entry) => void
  onRemove: () => void
}) {
  const upd = (patch: Partial<Entry>) => onChange({ ...entry, ...patch })
  const updBullet = (i: number, v: string) => {
    const bullets = [...entry.bullets]
    bullets[i] = v
    upd({ bullets })
  }
  const addBullet = () => upd({ bullets: [...entry.bullets, ''] })
  const removeBullet = (i: number) => upd({ bullets: entry.bullets.filter((_, j) => j !== i) })

  return (
    <div className="group relative rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
      <button
        onClick={onRemove}
        className="absolute right-2 top-2 hidden rounded p-0.5 text-zinc-700 transition hover:bg-red-500/20 hover:text-red-400 group-hover:flex"
      >
        <Trash2 size={11} />
      </button>

      {/* Type badge */}
      <div className="mb-2 flex items-center gap-1.5">
        <GripVertical size={11} className="text-zinc-800" />
        <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
          {entry.type}
        </span>
      </div>

      {entry.type === 'raw' ? (
        <Field
          label="Raw LaTeX"
          value={entry.raw ?? ''}
          onChange={(v) => upd({ raw: v })}
          placeholder="Raw LaTeX block"
          multiline
        />
      ) : (
        <div className="space-y-2">
          {/* Common fields */}
          {(entry.type === 'subheading' || entry.type === 'cventry' || entry.type === 'cvevent') && (
            <div className="grid grid-cols-2 gap-2">
              <Field label="Heading / Title" value={entry.heading ?? ''} onChange={(v) => upd({ heading: v })} />
              <Field label="Subheading / Company" value={entry.subheading ?? ''} onChange={(v) => upd({ subheading: v })} />
            </div>
          )}
          {entry.type === 'project' && (
            <Field label="Project Title" value={entry.heading ?? ''} onChange={(v) => upd({ heading: v })} />
          )}
          {entry.type !== 'bullets' && (
            <div className="grid grid-cols-3 gap-2">
              <Field label="Start Date" value={entry.startDate ?? ''} onChange={(v) => upd({ startDate: v })} placeholder="Jan 2022" />
              <Field label="End Date" value={entry.endDate ?? ''} onChange={(v) => upd({ endDate: v })} placeholder="Present" />
              {entry.type !== 'project' && (
                <Field label="Location" value={entry.location ?? ''} onChange={(v) => upd({ location: v })} placeholder="Remote" />
              )}
            </div>
          )}

          {/* Bullets */}
          <div>
            <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.12em] text-zinc-700">
              Bullets
            </div>
            <div className="space-y-1">
              {entry.bullets.map((b, i) => (
                <div key={i} className="flex items-start gap-1">
                  <span className="mt-1.5 text-zinc-800">•</span>
                  <input
                    value={b}
                    onChange={(e) => updBullet(i, e.target.value)}
                    className="flex-1 rounded border border-white/[0.06] bg-black/20 px-2 py-1 text-[11px] text-zinc-300 outline-none focus:border-violet-500/30"
                    placeholder="Bullet point…"
                  />
                  <button
                    onClick={() => removeBullet(i)}
                    className="mt-0.5 rounded p-0.5 text-zinc-800 transition hover:text-red-400"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={addBullet}
              className="mt-1.5 flex items-center gap-1 text-[10px] text-zinc-700 transition hover:text-zinc-400"
            >
              <Plus size={10} />
              Add bullet
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Section card ──────────────────────────────────────────────────────────────

function SectionCard({
  section,
  onChange,
}: {
  section: Section
  onChange: (s: Section) => void
}) {
  const updateEntry = (i: number, entry: Entry) => {
    const entries = [...section.entries]
    entries[i] = entry
    onChange({ ...section, entries })
  }

  const removeEntry = (i: number) => {
    onChange({ ...section, entries: section.entries.filter((_, j) => j !== i) })
  }

  const addEntry = (type: EntryType) => {
    const entry: Entry = {
      type,
      heading: '',
      subheading: '',
      startDate: '',
      endDate: '',
      location: '',
      bullets: [],
    }
    onChange({ ...section, entries: [...section.entries, entry] })
  }

  return (
    <div className="rounded-xl border border-white/[0.05] bg-white/[0.01] p-4">
      <div className="mb-3 flex items-center justify-between">
        <input
          value={section.title}
          onChange={(e) => onChange({ ...section, title: e.target.value })}
          className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-[13px] font-bold text-zinc-200 outline-none hover:border-white/[0.08] focus:border-violet-500/40"
          placeholder="Section Title"
        />
      </div>

      <div className="space-y-2">
        {section.entries.map((entry, i) => (
          <EntryCard
            key={i}
            entry={entry}
            onChange={(e) => updateEntry(i, e)}
            onRemove={() => removeEntry(i)}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(['subheading', 'project', 'bullets'] as EntryType[]).map((type) => (
          <button
            key={type}
            onClick={() => addEntry(type)}
            className="flex items-center gap-1 rounded-md border border-white/[0.06] bg-white/[0.02] px-2 py-1 text-[10px] text-zinc-600 transition hover:border-violet-500/30 hover:text-zinc-400"
          >
            <Plus size={10} />
            {type === 'subheading' ? 'Job / Education' : type === 'project' ? 'Project' : 'Bullet list'}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface WYSIWYGEditorProps {
  doc: ResumeDoc
  onChange: (doc: ResumeDoc) => void
  hasRawEntries?: boolean
}

export default function WYSIWYGEditor({ doc, onChange, hasRawEntries }: WYSIWYGEditorProps) {
  const updateSection = (i: number, section: Section) => {
    const sections = [...doc.sections]
    sections[i] = section
    onChange({ ...doc, sections })
  }

  const addSection = () => {
    onChange({
      ...doc,
      sections: [...doc.sections, { title: 'New Section', entries: [] }],
    })
  }

  return (
    <div className="flex flex-col gap-4">
      {hasRawEntries && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
          <AlertTriangle size={12} />
          Some blocks could not be parsed and are shown as raw LaTeX. They will be preserved as-is.
        </div>
      )}

      {doc.sections.map((section, i) => (
        <SectionCard
          key={i}
          section={section}
          onChange={(s) => updateSection(i, s)}
        />
      ))}

      <button
        onClick={addSection}
        className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-white/[0.08] py-3 text-[11px] text-zinc-700 transition hover:border-violet-500/30 hover:text-zinc-500"
      >
        <Plus size={12} />
        Add Section
      </button>
    </div>
  )
}
