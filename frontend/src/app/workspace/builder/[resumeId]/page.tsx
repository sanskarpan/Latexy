'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Eye,
  EyeOff,
  FileText,
  LayoutList,
  Plus,
  RefreshCcw,
  Sparkles,
  Target,
  Wand2,
} from 'lucide-react'
import { toast } from 'sonner'

import BuilderPreview from '@/components/builder/BuilderPreview'
import {
  apiClient,
  type BuilderTemplateResponse,
  type StructuredResume,
} from '@/lib/api-client'
import {
  cloneStructuredResume,
  createBuilderId,
  DEFAULT_STRUCTURED_RESUME,
  deriveBuilderMetrics,
  deriveBuilderPreview,
} from '@/lib/resume-builder'

type SectionKey = StructuredResume['section_order'][number]

type SectionConfig = {
  key: SectionKey
  title: string
  description: string
  emptyHint: string
}

const SECTION_CONFIG: SectionConfig[] = [
  {
    key: 'summary',
    title: 'Profile & Summary',
    description: 'Lock the headline, contact details, and the first five seconds of the resume.',
    emptyHint: 'Add name, headline, and a short summary to make the preview immediately usable.',
  },
  {
    key: 'experience',
    title: 'Experience',
    description: 'Lead with impact, measurable outcomes, and role progression.',
    emptyHint: 'Add at least one recent role with results-oriented bullets.',
  },
  {
    key: 'education',
    title: 'Education',
    description: 'Capture degree signal, timeline, and any highlights worth keeping.',
    emptyHint: 'Add one education entry, even for experienced resumes.',
  },
  {
    key: 'skills',
    title: 'Skills',
    description: 'Group keywords by capability so ATS and recruiters can skim quickly.',
    emptyHint: 'Create at least one skill group with relevant keywords.',
  },
  {
    key: 'projects',
    title: 'Projects',
    description: 'Use this when shipped work deserves explicit spotlight beyond job bullets.',
    emptyHint: 'Add a project if it meaningfully strengthens the narrative.',
  },
  {
    key: 'certifications',
    title: 'Certifications',
    description: 'Useful for cloud, security, finance, and other trust-heavy roles.',
    emptyHint: 'Skip unless it materially supports the target job.',
  },
  {
    key: 'awards',
    title: 'Awards',
    description: 'Keep only proof points that add signal rather than vanity.',
    emptyHint: 'Optional section for standout recognition.',
  },
  {
    key: 'languages',
    title: 'Languages',
    description: 'List only real working proficiency or market-relevant fluency.',
    emptyHint: 'Useful for global, customer-facing, and multilingual roles.',
  },
  {
    key: 'interests',
    title: 'Interests',
    description: 'Add sparingly when it makes the candidate more memorable or aligned.',
    emptyHint: 'Usually optional. Use only if it helps the story.',
  },
]

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-white/8 bg-black/20 p-4 ${className}`}>{children}</div>
}

function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block text-xs uppercase tracking-[0.14em] text-zinc-500">
      {children}
    </label>
  )
}

function TextInput(
  props: React.InputHTMLAttributes<HTMLInputElement> & {
    id?: string
  },
) {
  return (
    <input
      {...props}
      className={`w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-white outline-none transition focus:border-orange-300/50 ${props.className ?? ''}`}
    />
  )
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-white outline-none transition focus:border-orange-300/50 ${props.className ?? ''}`}
    />
  )
}

function SectionHeader({
  title,
  sectionKey,
  description,
  order,
  hidden,
  onMove,
  onToggleHidden,
}: {
  title: string
  sectionKey: SectionKey
  description: string
  order: string[]
  hidden: boolean
  onMove: (sectionKey: SectionKey, direction: -1 | 1) => void
  onToggleHidden: (sectionKey: SectionKey) => void
}) {
  const idx = order.indexOf(sectionKey)
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-lg font-semibold text-white">{title}</p>
        <p className="mt-1 max-w-2xl text-sm text-zinc-400">{description}</p>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => onMove(sectionKey, -1)} disabled={idx <= 0} className="btn-ghost px-2 py-2 text-xs disabled:opacity-30">
          <ArrowUp className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={() => onMove(sectionKey, 1)} disabled={idx === -1 || idx >= order.length - 1} className="btn-ghost px-2 py-2 text-xs disabled:opacity-30">
          <ArrowDown className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={() => onToggleHidden(sectionKey)} className="btn-ghost px-2 py-2 text-xs">
          {hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>
    </div>
  )
}

function StarterChip({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-zinc-300 transition hover:bg-white/[0.08]"
    >
      {label}
    </button>
  )
}

function joinComma(value: string[]) {
  return value.join(', ')
}

function splitComma(value: string) {
  return value.split(',').map(item => item.trim()).filter(Boolean)
}

function splitLines(value: string) {
  return value.split('\n').map(item => item.trim()).filter(Boolean)
}

function sectionCount(structured: StructuredResume, section: SectionKey) {
  switch (section) {
    case 'summary':
      return Number(Boolean(structured.basics.summary.trim() || structured.basics.name.trim() || structured.basics.label.trim()))
    case 'experience':
      return structured.experience.length
    case 'education':
      return structured.education.length
    case 'skills':
      return structured.skills.length
    case 'projects':
      return structured.projects.length
    case 'certifications':
      return structured.certifications.length
    case 'awards':
      return structured.awards.length
    case 'languages':
      return structured.languages.length
    case 'interests':
      return structured.interests.length
  }
}

function sectionReady(structured: StructuredResume, section: SectionKey) {
  switch (section) {
    case 'summary':
      return Boolean(structured.basics.name.trim() && structured.basics.summary.trim())
    case 'experience':
      return structured.experience.some(item => item.title.trim() && item.company.trim() && item.bullets.some(bullet => bullet.trim()))
    case 'education':
      return structured.education.some(item => item.institution.trim() && item.degree.trim())
    case 'skills':
      return structured.skills.some(item => item.name.trim() && item.keywords.length)
    case 'projects':
      return structured.projects.some(item => item.name.trim() && (item.description.trim() || item.bullets.some(bullet => bullet.trim())))
    case 'certifications':
      return structured.certifications.some(item => item.name.trim())
    case 'awards':
      return structured.awards.some(item => item.name.trim())
    case 'languages':
      return structured.languages.some(item => item.name.trim())
    case 'interests':
      return structured.interests.some(item => item.name.trim())
  }
}

export default function BuilderResumePage() {
  const params = useParams<{ resumeId: string }>()
  const router = useRouter()
  const resumeId = params.resumeId

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [templates, setTemplates] = useState<BuilderTemplateResponse[]>([])
  const [title, setTitle] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [structured, setStructured] = useState<StructuredResume>(cloneStructuredResume(DEFAULT_STRUCTURED_RESUME))
  const [templateFamily, setTemplateFamily] = useState('minimal')
  const [builderStatus, setBuilderStatus] = useState<'active' | 'detached'>('active')
  const [activeSection, setActiveSection] = useState<SectionKey>('summary')
  const initialLoad = useRef(true)
  const sectionRefs = useRef<Partial<Record<SectionKey, HTMLElement | null>>>({})

  const liveMetrics = useMemo(() => deriveBuilderMetrics(structured), [structured])
  const livePreview = useMemo(
    () => deriveBuilderPreview(structured, templateFamily),
    [structured, templateFamily],
  )

  const completenessScore = liveMetrics.completeness_score
  const pageEstimate = liveMetrics.page_estimate
  const warnings = liveMetrics.warnings
  const missingSections = liveMetrics.missing_sections

  const selectedTemplate = useMemo(
    () => templates.find(template => template.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  )

  useEffect(() => {
    let cancelled = false
    Promise.all([apiClient.getBuilderResume(resumeId), apiClient.getBuilderTemplates()])
      .then(([builder, availableTemplates]) => {
        if (cancelled) return
        setTemplates(availableTemplates)
        setTitle(builder.resume.title)
        setSelectedTemplateId(builder.resume.selected_template_id ?? availableTemplates[0]?.id ?? '')
        setStructured(cloneStructuredResume(builder.resume.structured_content ?? DEFAULT_STRUCTURED_RESUME))
        setTemplateFamily(builder.template_family)
        setBuilderStatus((builder.resume.builder_status ?? 'active') as 'active' | 'detached')
      })
      .catch(error => {
        toast.error(error instanceof Error ? error.message : 'Failed to load builder resume')
        router.push('/workspace')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [resumeId, router])

  useEffect(() => {
    if (initialLoad.current) {
      initialLoad.current = false
      return
    }
    if (!dirty || builderStatus === 'detached') return
    const timeout = window.setTimeout(async () => {
      setSaving(true)
      try {
        const updated = await apiClient.updateBuilderResume(resumeId, {
          title,
          template_id: selectedTemplateId,
          structured_content: structured,
        })
        setTemplateFamily(updated.template_family)
        setBuilderStatus((updated.resume.builder_status ?? 'active') as 'active' | 'detached')
        setDirty(false)
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Autosave failed')
      } finally {
        setSaving(false)
      }
    }, 600)
    return () => window.clearTimeout(timeout)
  }, [dirty, structured, title, selectedTemplateId, resumeId, builderStatus])

  const mutateStructured = (mutator: (draft: StructuredResume) => void) => {
    setStructured(prev => {
      const next = cloneStructuredResume(prev)
      mutator(next)
      return next
    })
    setDirty(true)
  }

  const moveSection = (sectionKey: SectionKey, direction: -1 | 1) => {
    mutateStructured(draft => {
      const currentIndex = draft.section_order.indexOf(sectionKey)
      const targetIndex = currentIndex + direction
      if (currentIndex < 0 || targetIndex < 0 || targetIndex >= draft.section_order.length) return
      const [item] = draft.section_order.splice(currentIndex, 1)
      draft.section_order.splice(targetIndex, 0, item)
    })
  }

  const toggleHidden = (sectionKey: SectionKey) => {
    mutateStructured(draft => {
      if (draft.hidden_sections.includes(sectionKey)) {
        draft.hidden_sections = draft.hidden_sections.filter(section => section !== sectionKey)
      } else {
        draft.hidden_sections = [...draft.hidden_sections, sectionKey]
      }
    })
  }

  const forceReattach = async () => {
    setSaving(true)
    try {
      const updated = await apiClient.updateBuilderResume(resumeId, {
        title,
        template_id: selectedTemplateId,
        structured_content: structured,
        force_reattach: true,
      })
      setTemplateFamily(updated.template_family)
      setBuilderStatus('active')
      setDirty(false)
      toast.success('Builder reattached and LaTeX overwritten from structured data')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to reattach builder')
    } finally {
      setSaving(false)
    }
  }

  const jumpToSection = (section: SectionKey) => {
    setActiveSection(section)
    sectionRefs.current[section]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const visibleSections = useMemo(
    () => structured.section_order.filter(section => !structured.hidden_sections.includes(section)),
    [structured.section_order, structured.hidden_sections],
  )

  const healthTone = completenessScore >= 85
    ? 'border-emerald-300/20 bg-emerald-300/[0.08] text-emerald-100'
    : completenessScore >= 65
      ? 'border-amber-300/20 bg-amber-300/[0.08] text-amber-100'
      : 'border-rose-300/20 bg-rose-300/[0.08] text-rose-100'

  if (loading) {
    return <div className="content-shell py-16 text-sm text-zinc-400">Loading builder…</div>
  }

  const hidden = new Set(structured.hidden_sections)
  const missingSet = new Set(missingSections)

  return (
    <div className="content-shell space-y-8 pb-16">
      <header className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div>
          <p className="overline">Guided Builder</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">{title || 'Untitled Resume'}</h1>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            This builder is now the structured path: guide the narrative, tune density, and keep LaTeX synchronized
            without treating the resume like a raw text file.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link href={`/workspace/${resumeId}/edit`} className="btn-ghost px-4 py-2 text-xs">
            Open Advanced Editor
          </Link>
          <div className="rounded-full border border-white/10 px-3 py-2 text-xs text-zinc-400">
            {saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'All changes saved'}
          </div>
        </div>
      </header>

      {builderStatus === 'detached' ? (
        <section className="surface-panel edge-highlight border border-amber-300/20 bg-amber-300/[0.05] p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-amber-100">Builder detached</p>
              <p className="mt-1 text-sm text-amber-50/80">
                This resume was edited directly in the advanced editor. Structured changes are paused until you explicitly
                overwrite the current LaTeX from builder data.
              </p>
            </div>
            <button type="button" onClick={() => void forceReattach()} className="btn-accent px-4 py-2 text-xs">
              <RefreshCcw className="mr-2 inline h-3.5 w-3.5" />
              Reattach Builder
            </button>
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-4">
        <Card className={healthTone}>
          <p className="text-xs uppercase tracking-[0.14em] opacity-70">Resume Health</p>
          <p className="mt-2 text-3xl font-semibold">{completenessScore}%</p>
          <p className="mt-2 text-sm opacity-85">
            {missingSections.length
              ? `${missingSections.length} key area${missingSections.length === 1 ? '' : 's'} still weak or missing.`
              : 'Core sections are covered and preview-ready.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Page Strategy</p>
          <p className="mt-2 text-3xl font-semibold text-white">{pageEstimate}</p>
          <p className="mt-2 text-sm text-zinc-400">
            {pageEstimate > 1 ? 'Trim bullets and optional sections to stay tighter.' : 'Compact enough for the most common one-page target.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Visible Sections</p>
          <p className="mt-2 text-3xl font-semibold text-white">{visibleSections.length}</p>
          <p className="mt-2 text-sm text-zinc-400">
            {structured.hidden_sections.length
              ? `${structured.hidden_sections.length} section${structured.hidden_sections.length === 1 ? '' : 's'} hidden from the rendered resume.`
              : 'All configured sections are currently visible.'}
          </p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Current Template</p>
          <p className="mt-2 text-lg font-semibold text-white">{selectedTemplate?.name || 'Template'}</p>
          <p className="mt-2 text-sm text-zinc-400">
            Family: {selectedTemplate?.template_family || templateFamily} · {selectedTemplate?.category_label || 'Builder'}
          </p>
        </Card>
      </section>

      <section className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)_420px]">
        <aside className="space-y-4">
          <Card className="sticky top-24">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <LayoutList className="h-4 w-4 text-orange-300" />
              Builder Flow
            </div>
            <div className="mt-4 space-y-2">
              {SECTION_CONFIG.map(section => {
                const count = sectionCount(structured, section.key)
                const ready = sectionReady(structured, section.key)
                const isActive = activeSection === section.key
                return (
                  <button
                    key={section.key}
                    type="button"
                    onClick={() => jumpToSection(section.key)}
                    className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                      isActive
                        ? 'border-orange-300/30 bg-orange-300/[0.08]'
                        : 'border-white/8 bg-black/20 hover:bg-white/[0.04]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-white">{section.title}</p>
                      {ready ? <CheckCircle2 className="h-4 w-4 text-emerald-300" /> : null}
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">
                      {hidden.has(section.key)
                        ? 'Hidden from output'
                        : count
                          ? `${count} item${count === 1 ? '' : 's'} configured`
                          : section.emptyHint}
                    </p>
                  </button>
                )
              })}
            </div>

            {missingSections.length ? (
              <div className="mt-5 rounded-2xl border border-amber-300/15 bg-amber-300/[0.06] px-3 py-3">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-100/85">
                  <Target className="h-3.5 w-3.5" />
                  Next fixes
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {missingSections.map(item => {
                    const key = item === 'name' || item === 'email' ? 'summary' : item
                    if (!SECTION_CONFIG.some(section => section.key === key)) return null
                    return (
                      <StarterChip key={item} label={item.replace('_', ' ')} onClick={() => jumpToSection(key as SectionKey)} />
                    )
                  })}
                </div>
              </div>
            ) : null}
          </Card>
        </aside>

        <div className="space-y-6">
          <section className="surface-panel edge-highlight p-6">
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <FieldLabel htmlFor="builder-resume-title">Resume Title</FieldLabel>
                  <TextInput
                    id="builder-resume-title"
                    type="text"
                    value={title}
                    onChange={event => {
                      setTitle(event.target.value)
                      setDirty(true)
                    }}
                  />
                </div>
                <div>
                  <FieldLabel htmlFor="builder-template-select">Template</FieldLabel>
                  <select
                    id="builder-template-select"
                    value={selectedTemplateId}
                    onChange={event => {
                      setSelectedTemplateId(event.target.value)
                      setDirty(true)
                    }}
                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-white outline-none transition focus:border-orange-300/50"
                  >
                    {templates.map(template => (
                      <option key={template.id} value={template.id}>
                        {template.name} · {template.category_label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <Card className="flex h-full flex-col justify-between">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Wand2 className="h-4 w-4 text-orange-300" />
                  Builder Guidance
                </div>
                <div className="mt-3 space-y-2 text-sm text-zinc-300">
                  <p>Lead with measurable impact, not responsibility lists.</p>
                  <p>Keep the preview one page unless the role clearly benefits from a second page.</p>
                  <p>Hide sections that don’t reinforce the target job instead of filling them with weak content.</p>
                </div>
              </Card>
            </div>

            {warnings.length ? (
              <div className="mt-4 space-y-2">
                {warnings.map(warning => (
                  <div key={warning} className="rounded-xl border border-amber-300/20 bg-amber-300/[0.05] px-3 py-2 text-xs text-amber-50/90">
                    {warning}
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <section
            ref={node => {
              sectionRefs.current.summary = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Profile & Summary"
              sectionKey="summary"
              description="Control the resume header, role headline, and the core narrative recruiters see first."
              order={structured.section_order}
              hidden={hidden.has('summary')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="grid gap-4 md:grid-cols-2">
              {[
                ['Full Name', 'name'],
                ['Headline', 'label'],
                ['Email', 'email'],
                ['Phone', 'phone'],
                ['Location', 'location'],
                ['Website', 'website'],
                ['LinkedIn', 'linkedin'],
                ['GitHub', 'github'],
              ].map(([label, key]) => (
                <div key={key}>
                  <FieldLabel htmlFor={`builder-basics-${key}`}>{label}</FieldLabel>
                  <TextInput
                    id={`builder-basics-${key}`}
                    type="text"
                    value={structured.basics[key as keyof StructuredResume['basics']]}
                    onChange={event => mutateStructured(draft => {
                      draft.basics[key as keyof StructuredResume['basics']] = event.target.value
                    })}
                  />
                </div>
              ))}
            </div>
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <FieldLabel htmlFor="builder-basics-summary">Summary</FieldLabel>
                <div className="flex flex-wrap gap-2">
                  <StarterChip
                    label="Insert startup profile"
                    onClick={() => mutateStructured(draft => {
                      draft.basics.summary = 'Engineer who ships product-facing systems quickly, improves reliability under load, and partners tightly with product to turn ambiguity into measurable execution.'
                    })}
                  />
                  <StarterChip
                    label="Insert leadership profile"
                    onClick={() => mutateStructured(draft => {
                      draft.basics.summary = 'Technical leader with a track record of scaling teams, clarifying platform strategy, and driving high-leverage systems work across product and infrastructure.'
                    })}
                  />
                </div>
              </div>
              <TextArea
                id="builder-basics-summary"
                value={structured.basics.summary}
                onFocus={() => setActiveSection('summary')}
                onChange={event => mutateStructured(draft => {
                  draft.basics.summary = event.target.value
                })}
                rows={5}
              />
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.experience = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Experience"
              sectionKey="experience"
              description="Each role should read like evidence: scope, outcomes, and technical leverage."
              order={structured.section_order}
              hidden={hidden.has('experience')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.experience.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Role', 'title'],
                      ['Company', 'company'],
                      ['Location', 'location'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel>{label}</FieldLabel>
                        <TextInput
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('experience')}
                          onChange={event => mutateStructured(draft => {
                            draft.experience[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <label className="mt-4 flex items-center gap-2 text-sm text-zinc-300">
                    <input
                      type="checkbox"
                      checked={entry.current}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].current = event.target.checked
                        if (event.target.checked) draft.experience[idx].end_date = ''
                      })}
                    />
                    Current role
                  </label>
                  <div className="mt-4">
                    <FieldLabel>Role Summary</FieldLabel>
                    <TextArea
                      rows={3}
                      value={entry.summary}
                      onFocus={() => setActiveSection('experience')}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].summary = event.target.value
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Impact Bullets</FieldLabel>
                    <TextArea
                      rows={5}
                      value={entry.bullets.join('\n')}
                      onFocus={() => setActiveSection('experience')}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].bullets = splitLines(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Technologies</FieldLabel>
                    <TextInput
                      type="text"
                      value={joinComma(entry.technologies)}
                      placeholder="Python, PostgreSQL, Kafka, AWS"
                      onFocus={() => setActiveSection('experience')}
                      onChange={event => mutateStructured(draft => {
                        draft.experience[idx].technologies = splitComma(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.experience.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove entry
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.experience.push({
                  id: createBuilderId('exp'),
                  title: '',
                  company: '',
                  location: '',
                  start_date: '',
                  end_date: '',
                  current: false,
                  summary: '',
                  bullets: [],
                  technologies: [],
                })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add experience
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.education = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Education"
              sectionKey="education"
              description="Keep it compact unless education is still a primary qualification signal."
              order={structured.section_order}
              hidden={hidden.has('education')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.education.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Institution', 'institution'],
                      ['Degree', 'degree'],
                      ['Field', 'field'],
                      ['Location', 'location'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                      ['GPA', 'gpa'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel>{label}</FieldLabel>
                        <TextInput
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('education')}
                          onChange={event => mutateStructured(draft => {
                            draft.education[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Highlights</FieldLabel>
                    <TextArea
                      rows={4}
                      value={entry.highlights.join('\n')}
                      placeholder="Honors, thesis, relevant coursework, leadership"
                      onFocus={() => setActiveSection('education')}
                      onChange={event => mutateStructured(draft => {
                        draft.education[idx].highlights = splitLines(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.education.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove education
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.education.push({
                  id: createBuilderId('edu'),
                  institution: '',
                  degree: '',
                  field: '',
                  location: '',
                  start_date: '',
                  end_date: '',
                  gpa: '',
                  highlights: [],
                })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add education
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.skills = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Skills"
              sectionKey="skills"
              description="Structure keywords into groups so both ATS and humans can parse them fast."
              order={structured.section_order}
              hidden={hidden.has('skills')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.skills.map((group, idx) => (
                <Card key={group.id}>
                  <FieldLabel>Group Name</FieldLabel>
                  <TextInput
                    type="text"
                    value={group.name}
                    onFocus={() => setActiveSection('skills')}
                    onChange={event => mutateStructured(draft => {
                      draft.skills[idx].name = event.target.value
                    })}
                  />
                  <div className="mt-4">
                    <FieldLabel>Keywords</FieldLabel>
                    <TextArea
                      rows={3}
                      value={joinComma(group.keywords)}
                      onFocus={() => setActiveSection('skills')}
                      onChange={event => mutateStructured(draft => {
                        draft.skills[idx].keywords = splitComma(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.skills.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove skill group
                    </button>
                  </div>
                </Card>
              ))}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => mutateStructured(draft => {
                  draft.skills.push({ id: createBuilderId('skill'), name: 'Core Skills', keywords: [] })
                })} className="btn-accent px-4 py-2 text-xs">
                  <Plus className="mr-2 inline h-3.5 w-3.5" />
                  Add skill group
                </button>
                <StarterChip
                  label="Add engineering groups"
                  onClick={() => mutateStructured(draft => {
                    if (!draft.skills.length) {
                      draft.skills.push(
                        { id: createBuilderId('skill'), name: 'Languages', keywords: ['Python', 'TypeScript', 'SQL'] },
                        { id: createBuilderId('skill'), name: 'Platform', keywords: ['AWS', 'Docker', 'Kubernetes'] },
                      )
                    }
                  })}
                />
              </div>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.projects = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Projects"
              sectionKey="projects"
              description="Use projects to surface work that sharpens the candidate’s story, not to pad the page."
              order={structured.section_order}
              hidden={hidden.has('projects')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.projects.map((project, idx) => (
                <Card key={project.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Project Name', 'name'],
                      ['Role', 'role'],
                      ['URL', 'url'],
                      ['Start Date', 'start_date'],
                      ['End Date', 'end_date'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel>{label}</FieldLabel>
                        <TextInput
                          type="text"
                          value={project[key as keyof typeof project] as string}
                          onFocus={() => setActiveSection('projects')}
                          onChange={event => mutateStructured(draft => {
                            draft.projects[idx][key as keyof typeof project] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Description</FieldLabel>
                    <TextArea
                      rows={3}
                      value={project.description}
                      onFocus={() => setActiveSection('projects')}
                      onChange={event => mutateStructured(draft => {
                        draft.projects[idx].description = event.target.value
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Impact Bullets</FieldLabel>
                    <TextArea
                      rows={4}
                      value={project.bullets.join('\n')}
                      onFocus={() => setActiveSection('projects')}
                      onChange={event => mutateStructured(draft => {
                        draft.projects[idx].bullets = splitLines(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4">
                    <FieldLabel>Technologies</FieldLabel>
                    <TextInput
                      type="text"
                      value={joinComma(project.technologies)}
                      onFocus={() => setActiveSection('projects')}
                      onChange={event => mutateStructured(draft => {
                        draft.projects[idx].technologies = splitComma(event.target.value)
                      })}
                    />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.projects.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove project
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.projects.push({
                  id: createBuilderId('proj'),
                  name: '',
                  role: '',
                  url: '',
                  start_date: '',
                  end_date: '',
                  description: '',
                  bullets: [],
                  technologies: [],
                })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add project
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.certifications = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Certifications"
              sectionKey="certifications"
              description="Only keep credentials that materially support the target role or domain trust."
              order={structured.section_order}
              hidden={hidden.has('certifications')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.certifications.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['Name', 'name'],
                      ['Issuer', 'issuer'],
                      ['Date', 'date'],
                      ['URL', 'url'],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <FieldLabel>{label}</FieldLabel>
                        <TextInput
                          type="text"
                          value={entry[key as keyof typeof entry] as string}
                          onFocus={() => setActiveSection('certifications')}
                          onChange={event => mutateStructured(draft => {
                            draft.certifications[idx][key as keyof typeof entry] = event.target.value as never
                          })}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.certifications.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove certification
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.certifications.push({ id: createBuilderId('cert'), name: '', issuer: '', date: '', url: '' })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add certification
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.awards = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Awards"
              sectionKey="awards"
              description="Recognition should add proof, not noise."
              order={structured.section_order}
              hidden={hidden.has('awards')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.awards.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel>Name</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('awards')}
                        onChange={event => mutateStructured(draft => {
                          draft.awards[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel>Detail</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.detail}
                        onFocus={() => setActiveSection('awards')}
                        onChange={event => mutateStructured(draft => {
                          draft.awards[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.awards.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove award
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.awards.push({ id: createBuilderId('award'), name: '', detail: '' })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add award
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.languages = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Languages"
              sectionKey="languages"
              description="State the language and actual proficiency rather than broad claims."
              order={structured.section_order}
              hidden={hidden.has('languages')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.languages.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel>Language</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('languages')}
                        onChange={event => mutateStructured(draft => {
                          draft.languages[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel>Proficiency</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.detail}
                        placeholder="Native, fluent, professional, conversational"
                        onFocus={() => setActiveSection('languages')}
                        onChange={event => mutateStructured(draft => {
                          draft.languages[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.languages.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove language
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.languages.push({ id: createBuilderId('lang'), name: '', detail: '' })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add language
              </button>
            </div>
          </section>

          <section
            ref={node => {
              sectionRefs.current.interests = node
            }}
            className="surface-panel edge-highlight scroll-mt-28 p-6"
          >
            <SectionHeader
              title="Interests"
              sectionKey="interests"
              description="Keep this optional and only use it when it sharpens memorability or fit."
              order={structured.section_order}
              hidden={hidden.has('interests')}
              onMove={moveSection}
              onToggleHidden={toggleHidden}
            />
            <div className="space-y-4">
              {structured.interests.map((entry, idx) => (
                <Card key={entry.id}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel>Interest</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.name}
                        onFocus={() => setActiveSection('interests')}
                        onChange={event => mutateStructured(draft => {
                          draft.interests[idx].name = event.target.value
                        })}
                      />
                    </div>
                    <div>
                      <FieldLabel>Detail</FieldLabel>
                      <TextInput
                        type="text"
                        value={entry.detail}
                        placeholder="Context, depth, leadership, or relevance"
                        onFocus={() => setActiveSection('interests')}
                        onChange={event => mutateStructured(draft => {
                          draft.interests[idx].detail = event.target.value
                        })}
                        />
                      </div>
                    </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => mutateStructured(draft => {
                      draft.interests.splice(idx, 1)
                    })} className="btn-ghost px-4 py-2 text-xs">
                      Remove interest
                    </button>
                  </div>
                </Card>
              ))}
              <button type="button" onClick={() => mutateStructured(draft => {
                draft.interests.push({ id: createBuilderId('interest'), name: '', detail: '' })
              })} className="btn-accent px-4 py-2 text-xs">
                <Plus className="mr-2 inline h-3.5 w-3.5" />
                Add interest
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <BuilderPreview
            title={title}
            structured={structured}
            preview={livePreview}
            templateFamily={templateFamily}
            completenessScore={completenessScore}
            pageEstimate={pageEstimate}
            warnings={warnings}
          />

          <section className="surface-panel edge-highlight p-6">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Sparkles className="h-4 w-4 text-orange-300" />
              Builder Notes
            </div>
            <div className="mt-4 space-y-3 text-sm text-zinc-300">
              <p>Section order and visibility update both the preview and the generated LaTeX.</p>
              <p>Template switching stays within builder-native families so the structure remains stable.</p>
              <p>The advanced editor is still available when you need raw control, but that detaches the builder until you reattach it.</p>
            </div>
            <div className="mt-5 rounded-2xl border border-white/8 bg-black/20 p-4 text-xs text-zinc-500">
              <FileText className="mr-2 inline h-3.5 w-3.5" />
              Current mode: {builderStatus} · {selectedTemplate?.category_label || templateFamily}
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}
