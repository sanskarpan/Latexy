'use client'

import Link from 'next/link'
import { useId, useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
    IconArrowRight,
    IconBriefcase,
    IconCheck,
    IconChevronDown,
    IconCode,
    IconDotsVertical,
    IconFileText,
    IconLayout,
    IconListCheck,
    IconPlus,
    IconSchool,
    IconUserCircle,
} from '@tabler/icons-react'

const ORIGINAL_BULLET =
    'Built and maintained user-facing products in Python with a focus on performance.'
const SUGGESTED_BULLET =
    'Built and maintained user-facing Python features, prioritizing performance.'
const SAMPLE_SOURCE = `\\documentclass{article}
\\usepackage{amsmath}
\\begin{document}
\\section*{A Simple Equation}
\\[
  \\int_0^1 x^2 \\,dx = \\frac{1}{3}
\\]
\\end{document}`

function SourceCode({ source }: { source: string }) {
    return (
        <pre className="lp-code-sample">
            {source.split(/(\\[a-zA-Z]+\*?|\\\[|\\\])/g).map((part, index) =>
                part.startsWith('\\') ? (
                    <span className="lp-code-command" key={index}>
                        {part}
                    </span>
                ) : (
                    part
                )
            )}
        </pre>
    )
}

function SampleResume({
    name,
    role,
    bullet,
    extraJob,
}: {
    name: string
    role: string
    bullet: string
    extraJob: string | null
}) {
    return (
        <article className="lp-demo-paper" aria-label="Live sample résumé preview">
            <header>
                <h3>{name || 'Your name'}</h3>
                <p>{role || 'Your role'}</p>
                <small>alex@example.com · London · linkedin.com/in/alex</small>
            </header>
            <section>
                <h4>Summary</h4>
                <p>
                    Software engineer with a focus on building thoughtful, high-quality products.
                    Experienced in full-stack development, team collaboration, and turning complex
                    problems into simple, usable solutions.
                </p>
            </section>
            <section>
                <h4>Experience</h4>
                <div className="lp-paper-role">
                    <strong>{role || 'Your role'}</strong>
                    <span>2021 — Present</span>
                </div>
                <p>BrightCode</p>
                <ul>
                    <li>{bullet}</li>
                    <li>
                        Collaborated with cross-functional teams to improve the developer
                        experience.
                    </li>
                </ul>
                <div className="lp-paper-role">
                    <strong>Software Engineer</strong>
                    <span>2018 — 2021</span>
                </div>
                <p>Northwind</p>
                <p>Delivered product features and helped the team improve engineering practices.</p>
                {extraJob !== null && (
                    <>
                        <div className="lp-paper-role">
                            <strong>Additional experience</strong>
                        </div>
                        <p>{extraJob}</p>
                    </>
                )}
            </section>
            <section>
                <h4>Education</h4>
                <div className="lp-paper-role">
                    <strong>BSc Computer Science</strong>
                    <span>2014 — 2018</span>
                </div>
                <p>University of Bristol</p>
            </section>
        </article>
    )
}

function BuilderDemo() {
    const id = useId()
    const [mode, setMode] = useState<'guided' | 'source' | 'studio'>('guided')
    const [name, setName] = useState('Alex Morgan')
    const [role, setRole] = useState('Senior Software Engineer')
    const [bullet, setBullet] = useState(ORIGINAL_BULLET)
    const [extraJob, setExtraJob] = useState<string | null>(null)
    const modeNames = { guided: 'Guided builder', source: 'LaTeX source', studio: 'Visual studio' }
    const sectionLinks = [
        { key: 'personal', label: 'Personal details', icon: IconUserCircle },
        { key: 'experience', label: 'Experience', icon: IconBriefcase },
        { key: 'skills', label: 'Skills', icon: IconListCheck },
        { key: 'education', label: 'Education', icon: IconSchool },
    ]
    return (
        <div className="lp-demo lp-builder-demo">
            <div className="lp-demo-toolbar">
                <span>
                    <IconLayout size={15} aria-hidden="true" />
                    {modeNames[mode]}
                </span>
                <div className="lp-demo-tabs" role="tablist" aria-label="Explore authoring modes">
                    {(['guided', 'source', 'studio'] as const).map(value => (
                        <button
                            key={value}
                            id={`${id}-${value}`}
                            role="tab"
                            aria-selected={mode === value}
                            aria-label={modeNames[value]}
                            aria-controls={`${id}-panel`}
                            onClick={() => setMode(value)}
                            tabIndex={mode === value ? 0 : -1}
                            onKeyDown={event => {
                                if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key))
                                    return
                                event.preventDefault()
                                const modes = ['guided', 'source', 'studio'] as const
                                const next =
                                    event.key === 'Home'
                                        ? modes[0]
                                        : event.key === 'End'
                                          ? modes[2]
                                          : modes[
                                                (modes.indexOf(value) +
                                                    (event.key === 'ArrowRight' ? 1 : 2)) %
                                                    3
                                            ]
                                setMode(next)
                                document.getElementById(`${id}-${next}`)?.focus()
                            }}
                        >
                            {value === 'guided'
                                ? 'Visual'
                                : value === 'source'
                                  ? 'Source'
                                  : 'Studio'}
                        </button>
                    ))}
                </div>
                <Link
                    href={
                        mode === 'guided'
                            ? '/workspace/builder/new'
                            : `/try?mode=${mode === 'source' ? 'source' : 'visual'}`
                    }
                    className="lp-demo-open"
                >
                    Open <IconArrowRight size={13} aria-hidden="true" />
                </Link>
            </div>
            <div
                className="lp-builder-workspace"
                data-mode={mode}
                id={`${id}-panel`}
                role="tabpanel"
                aria-labelledby={`${id}-${mode}`}
                tabIndex={0}
            >
                {mode !== 'source' && (
                    <aside className="lp-builder-rail" aria-label="Sample résumé sections">
                        {sectionLinks.map(({ key, label, icon: Icon }) => (
                            <button
                                type="button"
                                key={key}
                                title={label}
                                aria-label={`Open ${label}`}
                                aria-controls={`${id}-${key}-section`}
                                onClick={() => {
                                    const details = document.getElementById(
                                        `${id}-${key}-section`
                                    ) as HTMLDetailsElement | null
                                    if (!details) return
                                    details.open = true
                                    details.querySelector('summary')?.focus()
                                }}
                            >
                                <Icon size={15} aria-hidden="true" />
                            </button>
                        ))}
                    </aside>
                )}
                <div className="lp-builder-fields">
                    {mode === 'source' ? (
                        <>
                            <span className="lp-demo-label">Sample LaTeX source</span>
                            <SourceCode
                                source={`\\section{Experience}\n\\textbf{${role}}\n\\begin{itemize}\n  \\item ${bullet}\n\\end{itemize}`}
                            />
                        </>
                    ) : (
                        <>
                            <details id={`${id}-personal-section`}>
                                <summary>
                                    Personal details{' '}
                                    <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <label htmlFor={`${id}-name`}>Name</label>
                                <input
                                    id={`${id}-name`}
                                    value={name}
                                    onChange={event => setName(event.target.value)}
                                    maxLength={50}
                                />
                                <label htmlFor={`${id}-role`}>Role</label>
                                <input
                                    id={`${id}-role`}
                                    value={role}
                                    onChange={event => setRole(event.target.value)}
                                    maxLength={70}
                                />
                            </details>
                            <details id={`${id}-experience-section`} open>
                                <summary>
                                    Experience <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <label htmlFor={`${id}-bullet`}>What did you do?</label>
                                <textarea
                                    id={`${id}-bullet`}
                                    value={bullet}
                                    onChange={event => setBullet(event.target.value)}
                                    rows={3}
                                    maxLength={300}
                                />
                            </details>
                            {mode === 'studio' ? (
                                <span className="lp-demo-hint lp-engine-note">
                                    Edit the sample text to try the studio.
                                </span>
                            ) : (
                                <button
                                    type="button"
                                    className="lp-demo-add"
                                    aria-pressed={extraJob !== null}
                                    onClick={() =>
                                        setExtraJob(current =>
                                            current === null
                                                ? 'Describe another role or project.'
                                                : null
                                        )
                                    }
                                >
                                    <IconPlus size={13} aria-hidden="true" />{' '}
                                    {extraJob === null ? 'Add job' : 'Remove job'}
                                </button>
                            )}
                            {extraJob !== null && (
                                <>
                                    <label htmlFor={`${id}-extra-job`}>Additional experience</label>
                                    <textarea
                                        id={`${id}-extra-job`}
                                        value={extraJob}
                                        onChange={event => setExtraJob(event.target.value)}
                                        rows={2}
                                        maxLength={300}
                                    />
                                </>
                            )}
                            <details id={`${id}-skills-section`}>
                                <summary>
                                    Skills <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <p>Python · TypeScript · Product development</p>
                            </details>
                            <details id={`${id}-education-section`}>
                                <summary>
                                    Education <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <p>BSc Computer Science, University of Bristol</p>
                            </details>
                        </>
                    )}
                </div>
                <div className="lp-builder-preview">
                    <SampleResume name={name} role={role} bullet={bullet} extraJob={extraJob} />
                </div>
            </div>
            <p className="lp-demo-caption">Interactive sample — edits stay in this preview.</p>
        </div>
    )
}

const DIMENSIONS = [
    { label: 'Grammar', score: 86 },
    { label: 'Keywords', score: 61 },
    { label: 'Density', score: 74 },
    { label: 'Sections', score: 91 },
    { label: 'Bullets', score: 78 },
]

function AnalysisDemo() {
    const [category, setCategory] = useState<'present' | 'partial' | 'missing'>('missing')
    const keywords = {
        present: ['Python', 'TypeScript', 'Product development'],
        partial: ['Scalable systems', 'Collaboration'],
        missing: ['System design', 'CI/CD', 'Stakeholder communication'],
    }
    const point = (index: number, radius: number) =>
        `${(130 + Math.sin((index * Math.PI * 2) / 5) * radius).toFixed(2)},${(114 - Math.cos((index * Math.PI * 2) / 5) * radius).toFixed(2)}`
    return (
        <div className="lp-demo lp-analysis-demo">
            <div className="lp-radar-panel">
                <h3>ATS analysis</h3>
                <svg
                    className="lp-radar-chart"
                    viewBox="0 0 260 235"
                    role="img"
                    aria-label="Illustrative scores: Grammar 86, Keywords 61, Density 74, Sections 91, Bullets 78 out of 100"
                >
                    {[0.25, 0.5, 0.75, 1].map(scale => (
                        <polygon
                            key={scale}
                            points={DIMENSIONS.map((_, i) => point(i, 75 * scale)).join(' ')}
                            fill="none"
                            stroke="var(--lp-border)"
                        />
                    ))}
                    {DIMENSIONS.map((_, i) => (
                        <line
                            key={i}
                            x1="130"
                            y1="114"
                            x2={point(i, 75).split(',')[0]}
                            y2={point(i, 75).split(',')[1]}
                            stroke="var(--lp-border)"
                        />
                    ))}
                    <polygon
                        points={DIMENSIONS.map((dimension, i) =>
                            point(i, dimension.score * 0.75)
                        ).join(' ')}
                        fill="var(--lp-accent)"
                        fillOpacity=".2"
                        stroke="var(--lp-accent)"
                        strokeWidth="1.5"
                    />
                    {DIMENSIONS.map((dimension, i) => {
                        const [x, y] = point(i, 97).split(',')
                        return (
                            <text
                                key={dimension.label}
                                x={x}
                                y={y}
                                textAnchor="middle"
                                dominantBaseline="middle"
                                fill="var(--lp-muted)"
                                fontSize="10"
                            >
                                {dimension.label}
                            </text>
                        )
                    })}
                </svg>
            </div>
            <div className="lp-keyword-panel">
                <h3>Keyword analysis</h3>
                <div className="lp-keyword-content">
                    <div className="lp-keyword-filters" aria-label="Keyword categories">
                        {(['present', 'partial', 'missing'] as const).map(value => (
                            <button
                                key={value}
                                aria-pressed={category === value}
                                onClick={() => setCategory(value)}
                            >
                                <span
                                    className={`lp-status-dot lp-status-${value} ${value}`}
                                    aria-hidden="true"
                                />
                                {value[0].toUpperCase() + value.slice(1)}
                                <strong>
                                    {value === 'present' ? 8 : value === 'partial' ? 4 : 6}
                                </strong>
                            </button>
                        ))}
                    </div>
                    <div className="lp-keyword-result" aria-live="polite">
                        <strong>
                            {category === 'missing'
                                ? 'Consider adding'
                                : category === 'partial'
                                  ? 'Make the connection clearer'
                                  : 'Already in your résumé'}
                        </strong>
                        <p>{keywords[category].join(', ')}</p>
                        <small>Only include skills and experience you actually have.</small>
                    </div>
                </div>
                <p className="lp-demo-caption">
                    Illustrative analysis. Scores are feedback, not a hiring prediction.
                </p>
            </div>
        </div>
    )
}

function TailoringDemo() {
    const id = useId()
    const [bullet, setBullet] = useState(SUGGESTED_BULLET)
    const [editing, setEditing] = useState(false)
    const [decision, setDecision] = useState<'pending' | 'accepted' | 'original'>('pending')
    return (
        <div className="lp-demo lp-tailor-demo">
            <div className="lp-tailor-flow">
                <div className="lp-tailor-cell">
                    <h3>Job requirement</h3>
                    <p>Design and build scalable, user-facing features using Python.</p>
                </div>
                <IconArrowRight className="lp-flow-arrow" size={20} aria-hidden="true" />
                <div className="lp-tailor-cell">
                    <h3>Your matching experience</h3>
                    <p>{decision === 'accepted' ? bullet : ORIGINAL_BULLET}</p>
                </div>
                <IconArrowRight className="lp-flow-arrow" size={20} aria-hidden="true" />
                <div className="lp-tailor-cell lp-tailor-suggestion">
                    <h3>Suggested rewrite</h3>
                    {editing ? (
                        <>
                            <label className="sr-only" htmlFor={`${id}-rewrite`}>
                                Edit suggested rewrite
                            </label>
                            <textarea
                                id={`${id}-rewrite`}
                                value={bullet}
                                onChange={event => setBullet(event.target.value)}
                                rows={3}
                                maxLength={400}
                                autoFocus
                            />
                        </>
                    ) : (
                        <p>{bullet}</p>
                    )}
                </div>
                <div className="lp-tailor-actions">
                    <button
                        className="lp-button-small lp-button-accent"
                        onClick={() => {
                            setDecision('accepted')
                            setEditing(false)
                        }}
                        disabled={!bullet.trim()}
                    >
                        <IconCheck size={13} aria-hidden="true" />
                        {decision === 'accepted' ? 'Accepted' : 'Accept'}
                    </button>
                    <button
                        className="lp-button-small"
                        onClick={() => {
                            setEditing(!editing)
                            setDecision('pending')
                        }}
                    >
                        {editing ? 'Done' : 'Edit'}
                    </button>
                    <button
                        className="lp-button-small"
                        onClick={() => {
                            setDecision('original')
                            setEditing(false)
                        }}
                    >
                        Keep original
                    </button>
                </div>
            </div>
            <p className="lp-demo-caption" aria-live="polite">
                {decision === 'accepted'
                    ? 'Sample updated with your approved wording.'
                    : decision === 'original'
                      ? 'Original wording kept. You decide what changes.'
                      : 'Illustrative suggestion. Review every claim before using it.'}
            </p>
        </div>
    )
}

type ApplicationStatus = 'Saved' | 'Applied' | 'Interview'
const INITIAL_APPLICATIONS: {
    id: number
    role: string
    company: string
    status: ApplicationStatus
    version: string
    cover: boolean
}[] = [
    {
        id: 1,
        role: 'Senior Software Engineer',
        company: 'Acme',
        status: 'Saved',
        version: 'Product résumé',
        cover: true,
    },
    {
        id: 2,
        role: 'Frontend Engineer',
        company: 'Northwind',
        status: 'Saved',
        version: 'Frontend résumé',
        cover: false,
    },
    {
        id: 3,
        role: 'Software Engineer',
        company: 'Stripe',
        status: 'Applied',
        version: 'Platform résumé',
        cover: true,
    },
    {
        id: 4,
        role: 'Full Stack Developer',
        company: 'Linear',
        status: 'Applied',
        version: 'Product résumé',
        cover: true,
    },
    {
        id: 5,
        role: 'Senior Software Engineer',
        company: 'Notion',
        status: 'Interview',
        version: 'Product résumé',
        cover: true,
    },
]

function ApplicationDemo() {
    const [applications, setApplications] = useState(INITIAL_APPLICATIONS)
    return (
        <div className="lp-application-demo">
            <div className="lp-application-board">
                {(['Saved', 'Applied', 'Interview'] as const).map(status => (
                    <section className="lp-demo lp-board-column" key={status}>
                        <h3>
                            <span className="lp-board-heading">
                                <IconFileText size={14} aria-hidden="true" />
                                {status}
                            </span>
                            <span>
                                {
                                    applications.filter(
                                        application => application.status === status
                                    ).length
                                }
                            </span>
                        </h3>
                        {applications
                            .filter(application => application.status === status)
                            .map(application => (
                                <article className="lp-application-card" key={application.id}>
                                    <IconFileText size={17} aria-hidden="true" />
                                    <div>
                                        <h4>{application.role}</h4>
                                        <p
                                            title={`${application.version} · ${application.cover ? 'Cover letter attached' : 'Résumé ready'}`}
                                        >
                                            {application.company} · Résumé
                                            {application.cover ? ' + cover letter' : ''}
                                        </p>
                                    </div>
                                    <DropdownMenu.Root>
                                        <DropdownMenu.Trigger asChild>
                                            <button
                                                className="lp-application-overflow"
                                                id={`lp-application-${application.id}`}
                                                aria-label={`Manage ${application.role} at ${application.company}`}
                                            >
                                                <IconDotsVertical size={16} aria-hidden="true" />
                                            </button>
                                        </DropdownMenu.Trigger>
                                        <DropdownMenu.Portal>
                                            <DropdownMenu.Content
                                                className="lp-application-menu lp-page"
                                                sideOffset={5}
                                                align="end"
                                                onCloseAutoFocus={event => {
                                                    event.preventDefault()
                                                    requestAnimationFrame(() =>
                                                        document
                                                            .getElementById(
                                                                `lp-application-${application.id}`
                                                            )
                                                            ?.focus()
                                                    )
                                                }}
                                            >
                                                <DropdownMenu.Label className="lp-menu-label">
                                                    {application.version}
                                                </DropdownMenu.Label>
                                                <DropdownMenu.RadioGroup
                                                    value={application.status}
                                                    onValueChange={value => {
                                                        setApplications(current =>
                                                            current.map(item =>
                                                                item.id === application.id
                                                                    ? {
                                                                          ...item,
                                                                          status: value as ApplicationStatus,
                                                                      }
                                                                    : item
                                                            )
                                                        )
                                                    }}
                                                >
                                                    {(
                                                        ['Saved', 'Applied', 'Interview'] as const
                                                    ).map(value => (
                                                        <DropdownMenu.RadioItem
                                                            className="lp-menu-item"
                                                            key={value}
                                                            value={value}
                                                        >
                                                            <DropdownMenu.ItemIndicator>
                                                                <IconCheck
                                                                    size={13}
                                                                    aria-hidden="true"
                                                                />
                                                            </DropdownMenu.ItemIndicator>
                                                            {value}
                                                        </DropdownMenu.RadioItem>
                                                    ))}
                                                </DropdownMenu.RadioGroup>
                                            </DropdownMenu.Content>
                                        </DropdownMenu.Portal>
                                    </DropdownMenu.Root>
                                </article>
                            ))}
                    </section>
                ))}
            </div>
            <p className="lp-demo-caption">Sample board — use a card menu to change its status.</p>
        </div>
    )
}

function LatexDemo() {
    const id = useId()
    const [engine, setEngine] = useState('pdflatex')
    const engineNotes: Record<string, string> = {
        pdflatex: 'The classic compiler for everyday LaTeX documents.',
        xelatex: 'A compiler suited to Unicode text and system fonts.',
        lualatex: 'A modern compiler with Unicode and Lua support.',
    }
    return (
        <div className="lp-demo lp-latex-demo">
            <div className="lp-latex-source">
                <h3>
                    <IconCode size={14} aria-hidden="true" />
                    Source
                </h3>
                <SourceCode source={SAMPLE_SOURCE} />
            </div>
            <div className="lp-latex-preview">
                <span className="lp-demo-label">PDF preview</span>
                <article className="lp-demo-paper lp-equation-paper">
                    <h3>A Simple Equation</h3>
                    <p
                        className="lp-equation"
                        aria-label="Integral from zero to one of x squared dx equals one third"
                    >
                        ∫<sub>0</sub>
                        <sup>1</sup> x<sup>2</sup> dx = ⅓ <span>(1)</span>
                    </p>
                </article>
            </div>
            <div className="lp-compiler-controls">
                <label htmlFor={`${id}-engine`}>Explore compiler engines</label>
                <select
                    id={`${id}-engine`}
                    value={engine}
                    onChange={event => setEngine(event.target.value)}
                >
                    <option value="pdflatex">pdfLaTeX</option>
                    <option value="xelatex">XeLaTeX</option>
                    <option value="lualatex">LuaLaTeX</option>
                </select>
                <p className="lp-engine-note" aria-live="polite">
                    {engineNotes[engine]}
                </p>
                <Link className="lp-button-small lp-button-accent" href="/try?mode=source">
                    Open compiler <IconArrowRight size={13} aria-hidden="true" />
                </Link>
                <p className="lp-demo-caption">Fixed sample — compile in the studio.</p>
            </div>
        </div>
    )
}

export default function LandingExperience() {
    return (
        <div className="lp-experience" id="product">
            <section
                className="lp-feature-row lp-builder-section"
                aria-labelledby="lp-builder-title"
            >
                <div className="lp-section-copy">
                    <h2 id="lp-builder-title">
                        A builder for people.
                        <br />A studio for precision.
                    </h2>
                    <p>
                        Write, refine, and export with a tool designed for clarity, not complexity.
                    </p>
                </div>
                <BuilderDemo />
            </section>
            <section
                className="lp-feature-row lp-analysis-section"
                aria-labelledby="lp-analysis-title"
            >
                <div className="lp-section-copy">
                    <h2 id="lp-analysis-title">
                        Understand what
                        <br />
                        your résumé is saying.
                    </h2>
                    <p>
                        Get clear, actionable feedback on your content, from structure to keywords.
                    </p>
                </div>
                <AnalysisDemo />
            </section>
            <section
                className="lp-full-section lp-tailoring-section"
                aria-labelledby="lp-tailoring-title"
            >
                <div className="lp-section-copy">
                    <h2 id="lp-tailoring-title">Tailor to the role. Keep your voice.</h2>
                    <p>
                        See how your experience matches a job description, and get suggestions to
                        make it stronger.
                    </p>
                </div>
                <TailoringDemo />
            </section>
            <section
                className="lp-full-section lp-applications-section"
                aria-labelledby="lp-applications-title"
            >
                <div className="lp-section-copy">
                    <h2 id="lp-applications-title">The application does not end at the PDF.</h2>
                    <p>
                        Keep everything in one place — saved variants, cover letters, interview
                        prep, and a simple tracker.
                    </p>
                </div>
                <ApplicationDemo />
            </section>
            <section className="lp-feature-row lp-latex-section" aria-labelledby="lp-latex-title">
                <div className="lp-section-copy">
                    <h2 id="lp-latex-title">More than résumés. Real LaTeX.</h2>
                    <p>
                        Use the same LaTeX toolchain for academic papers, technical reports, and
                        more.
                    </p>
                </div>
                <LatexDemo />
            </section>
        </div>
    )
}
