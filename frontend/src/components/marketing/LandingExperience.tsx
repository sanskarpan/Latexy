'use client'

import Link from 'next/link'
import CapabilityGate from '@/components/CapabilityGate'
import { useId, useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Circle, Line, Polygon } from '@visx/shape'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import '@fontsource/tinos/latin-400.css'
import '@fontsource/tinos/latin-700.css'
import '@fontsource/tinos/latin-700-italic.css'
import {
    IconArrowRight,
    IconAlignLeft,
    IconArrowsDiagonal,
    IconCircleDot,
    IconCircleCheckFilled,
    IconCircleXFilled,
    IconAlertCircleFilled,
    IconLine,
    IconSquareFilled,
    IconDownload,
    IconBulb,
    IconBriefcase,
    IconCheck,
    IconChevronDown,
    IconDotsVertical,
    IconFileText,
    IconLayout,
    IconListCheck,
    IconPlus,
    IconSchool,
    IconUserCircle,
} from '@tabler/icons-react'

const SAMPLE_SUMMARY =
    'Software engineer with a focus on building thoughtful, high-quality products. Experienced in full-stack development, team collaboration, and turning complex problems into simple, usable solutions.'

const ORIGINAL_BULLET =
    'Built and maintained user-facing products in Python with a focus on performance.'
const EXPERIENCE_DETAILS = [
    'Collaborated with cross-functional teams.',
    'Improved the developer experience.',
] as const
const SUGGESTED_BULLET =
    'Built and maintained user-facing features using Python, with a focus on performance.'
const SAMPLE_SOURCE = `\\documentclass{article}
\\usepackage{amsmath}
\\begin{document}
\\section*{A Simple Equation}
\\[
  \\int_{-\\infty}^{\\infty} e^{-x^2}\\,dx = \\sqrt{\\pi}
\\]
\\end{document}`

function SourceCode({ source, lineNumbers = false }: { source: string; lineNumbers?: boolean }) {
    const renderLine = (line: string) =>
        line.split(/(\\[a-zA-Z]+\*?|\\\[|\\\])/g).map((part, index) =>
            part.startsWith('\\') ? (
                <span className="lp-code-command" key={index}>
                    {part}
                </span>
            ) : (
                part
            )
        )
    return (
        <pre className={`lp-code-sample${lineNumbers ? ' lp-code-numbered' : ''}`}>
            {lineNumbers
                ? source.split('\n').map((line, index) => (
                      <span className="lp-code-line" key={index}>
                          <span className="lp-code-line-number" aria-hidden="true">
                              {index + 1}
                          </span>
                          <code>{renderLine(line)}</code>
                      </span>
                  ))
                : renderLine(source)}
        </pre>
    )
}

function EquationSample() {
    return (
        <article className="lp-demo-paper lp-equation-paper">
            <h3>A Simple Equation</h3>
            <div
                className="lp-equation"
                role="math"
                aria-label="Integral from negative infinity to infinity of e to the negative x squared dx equals the square root of pi"
                dangerouslySetInnerHTML={{
                    __html: katex.renderToString(
                        String.raw`\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}\qquad(1)`,
                        {
                            displayMode: true,
                            throwOnError: false,
                        }
                    ),
                }}
            />
        </article>
    )
}

function SampleResume({
    name,
    role,
    bullet,
    extraJob,
    summary,
}: {
    name: string
    role: string
    bullet: string
    extraJob: string | null
    summary: string
}) {
    return (
        <article className="lp-demo-paper" aria-label="Live sample résumé preview">
            <header>
                <h3>{name.trim() || 'Your name'}</h3>
                <p>{role.trim() || 'Your role'}</p>
                <small>alex@example.com · London · linkedin.com/in/alex</small>
            </header>
            <section>
                <h4>Summary</h4>
                <p>{summary}</p>
            </section>
            <section>
                <h4>Experience</h4>
                <div className="lp-paper-role">
                    <strong>{role.trim() || 'Your role'}</strong>
                    <span>2021 — Present</span>
                </div>
                <p>BrightCode</p>
                <ul>
                    <li>{bullet}</li>
                    {EXPERIENCE_DETAILS.map(detail => (
                        <li key={detail}>{detail}</li>
                    ))}
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
    const [summary, setSummary] = useState(SAMPLE_SUMMARY)
    const [role, setRole] = useState('Senior Software Engineer')
    const [bullet, setBullet] = useState(ORIGINAL_BULLET)
    const [extraJob, setExtraJob] = useState<string | null>(null)
    const modeNames = { guided: 'Guided builder', source: 'LaTeX source', studio: 'Visual studio' }
    const sectionLinks = [
        { key: 'personal', label: 'Personal details', icon: IconUserCircle },
        { key: 'summary', label: 'Summary', icon: IconAlignLeft },
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
                <CapabilityGate feature={mode === 'guided' ? 'b08' : 'a09'}>
                    <CapabilityGate feature={mode === 'guided' ? 'b08' : 'b01'}>
                        <CapabilityGate feature={mode === 'guided' ? 'b08' : 'c01'}>
                            <Link
                                href={
                                    mode === 'guided'
                                        ? '/workspace/builder/new'
                                        : `/try?mode=${mode === 'source' ? 'source' : 'visual'}`
                                }
                                className="lp-demo-open"
                                aria-label={`Open ${modeNames[mode]} to export PDF`}
                                title={`Open ${modeNames[mode]} to export PDF`}
                            >
                                <IconDownload size={13} aria-hidden="true" /> Export PDF
                            </Link>
                        </CapabilityGate>
                    </CapabilityGate>
                </CapabilityGate>
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
                        <button
                            type="button"
                            title="Show all sections"
                            aria-label="Show all sample résumé sections"
                            onClick={() => {
                                sectionLinks.forEach(({ key }) => {
                                    const details = document.getElementById(
                                        `${id}-${key}-section`
                                    ) as HTMLDetailsElement | null
                                    if (details) details.open = true
                                })
                                document
                                    .getElementById(`${id}-personal-section`)
                                    ?.querySelector('summary')
                                    ?.focus()
                            }}
                        >
                            <IconLayout size={15} aria-hidden="true" />
                        </button>
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
                                source={`\\section{Experience}\n\\textbf{${role}}\n\\textit{BrightCode} \\hfill 2021--Present\n\\begin{itemize}\n  \\item ${bullet}\n${EXPERIENCE_DETAILS.map(detail => `  \\item ${detail}`).join('\n')}\n\\end{itemize}`}
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
                            <details id={`${id}-summary-section`}>
                                <summary>
                                    Summary <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <label htmlFor={`${id}-summary`}>Professional summary</label>
                                <textarea
                                    id={`${id}-summary`}
                                    value={summary}
                                    onChange={event => setSummary(event.target.value)}
                                    rows={4}
                                    maxLength={500}
                                />
                            </details>
                            <details id={`${id}-experience-section`} open>
                                <summary>
                                    Experience <IconChevronDown size={13} aria-hidden="true" />
                                </summary>
                                <div className="lp-experience-entry">
                                    <div className="lp-experience-role">
                                        <strong>{role.trim() || 'Your role'}</strong>
                                        <div className="lp-experience-meta">
                                            <small>BrightCode</small>
                                            <small>2021 — Present</small>
                                        </div>
                                    </div>
                                    <label className="sr-only" htmlFor={`${id}-bullet`}>
                                        What did you do?
                                    </label>
                                    <ul className="lp-experience-bullets">
                                        <li>
                                            <textarea
                                                id={`${id}-bullet`}
                                                value={bullet}
                                                onChange={event => setBullet(event.target.value)}
                                                rows={3}
                                                maxLength={300}
                                            />
                                        </li>
                                        {EXPERIENCE_DETAILS.map(detail => (
                                            <li key={detail}>{detail}</li>
                                        ))}
                                    </ul>
                                </div>
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
                    <SampleResume
                        name={name}
                        role={role}
                        bullet={bullet}
                        extraJob={extraJob}
                        summary={summary}
                    />
                </div>
            </div>
            <p className="sr-only">Interactive sample — edits stay in this preview.</p>
        </div>
    )
}

const DIMENSIONS = [
    {
        label: 'Grammar',
        score: 70,
        detail: 'Look for clear sentences, consistent tense and punctuation.',
    },
    {
        label: 'Keywords',
        score: 61,
        detail: 'Compare relevant terms with the job description. Include only skills you have.',
    },
    { label: 'Density', score: 80, detail: 'Give the important information room to breathe.' },
    {
        label: 'Sections',
        score: 72,
        detail: 'Use familiar headings so your experience is easy to find.',
    },
    {
        label: 'Bullets',
        score: 86,
        detail: 'Describe what you did with specific, truthful examples.',
    },
]

function AnalysisDemo() {
    const [category, setCategory] = useState<'present' | 'partial' | 'missing'>('missing')
    const [categoryTouched, setCategoryTouched] = useState(false)
    const [metric, setMetric] = useState<number | null>(null)
    const keywords = {
        present: ['Python', 'TypeScript', 'Product development'],
        partial: ['Scalable systems', 'Collaboration'],
        missing: ['System design', 'CI/CD', 'Stakeholder communication'],
    }
    const point = (index: number, radius: number): [number, number] => [
        140 + Math.sin((index * Math.PI * 2) / 5) * radius,
        118 - Math.cos((index * Math.PI * 2) / 5) * radius,
    ]
    return (
        <div className="lp-analysis-demo">
            <div className="lp-demo lp-radar-panel">
                <h3>ATS analysis</h3>
                <svg
                    className="lp-radar-chart"
                    viewBox="0 0 280 236"
                    role="img"
                    aria-label="Illustrative scores: Grammar 70, Keywords 61, Density 80, Sections 72, Bullets 86 out of 100"
                >
                    {[0.25, 0.5, 0.75, 1].map(scale => (
                        <Polygon
                            key={scale}
                            points={DIMENSIONS.map((_, index) => point(index, 96 * scale))}
                            fill="none"
                            stroke="var(--lp-chart-grid)"
                            strokeWidth={1}
                        />
                    ))}
                    {DIMENSIONS.map((_, index) => {
                        const [x, y] = point(index, 96)
                        return (
                            <Line
                                key={index}
                                from={{ x: 140, y: 118 }}
                                to={{ x, y }}
                                stroke="var(--lp-chart-grid)"
                            />
                        )
                    })}
                    <Polygon
                        points={DIMENSIONS.map((dimension, index) =>
                            point(index, dimension.score * 0.96)
                        )}
                        fill="var(--lp-chart-fill)"
                        fillOpacity={0.55}
                        stroke="var(--lp-chart-stroke)"
                        strokeWidth={1.8}
                    />
                    {DIMENSIONS.map((dimension, index) => {
                        const [x, y] = point(index, dimension.score * 0.96)
                        const [labelX, labelY] = point(index, 109)
                        return (
                            <g key={dimension.label}>
                                <Circle
                                    cx={x}
                                    cy={y}
                                    r={metric === index ? 6 : 2.6}
                                    fill="var(--lp-chart-stroke)"
                                    className="lp-radar-point"
                                />
                                <text
                                    x={labelX}
                                    y={labelY}
                                    textAnchor="middle"
                                    dominantBaseline="middle"
                                    fill="var(--lp-muted)"
                                    fontSize={17}
                                >
                                    {dimension.label}
                                </text>
                            </g>
                        )
                    })}
                </svg>
                <div className="lp-radar-metrics" role="group" aria-label="Explore sample analysis">
                    {DIMENSIONS.map((dimension, index) => (
                        <button
                            key={dimension.label}
                            type="button"
                            aria-pressed={metric === index}
                            onClick={() => setMetric(index)}
                        >
                            {dimension.label}
                        </button>
                    ))}
                </div>
                <p className="lp-radar-insight" aria-live="polite">
                    {metric === null ? (
                        'Select a metric to explore the sample.'
                    ) : (
                        <>
                            <strong>
                                {DIMENSIONS[metric].label} · {DIMENSIONS[metric].score}/100
                            </strong>{' '}
                            {DIMENSIONS[metric].detail}
                        </>
                    )}
                </p>
            </div>
            <div className="lp-demo lp-keyword-panel">
                <h3>Keyword analysis</h3>
                <div className="lp-keyword-content">
                    <div className="lp-keyword-filters" aria-label="Keyword categories">
                        {(['present', 'partial', 'missing'] as const).map(value => (
                            <button
                                key={value}
                                aria-pressed={category === value}
                                data-highlighted={categoryTouched && category === value}
                                onClick={() => {
                                    setCategory(value)
                                    setCategoryTouched(true)
                                }}
                            >
                                {value === 'present' ? (
                                    <IconCircleCheckFilled
                                        className="lp-status-dot"
                                        size={12}
                                        aria-hidden="true"
                                    />
                                ) : value === 'partial' ? (
                                    <IconAlertCircleFilled
                                        className="lp-status-dot partial"
                                        size={12}
                                        aria-hidden="true"
                                    />
                                ) : (
                                    <IconCircleXFilled
                                        className="lp-status-dot missing"
                                        size={12}
                                        aria-hidden="true"
                                    />
                                )}
                                {value[0].toUpperCase() + value.slice(1)}
                                <strong>
                                    {value === 'present' ? 8 : value === 'partial' ? 4 : 6}
                                </strong>
                            </button>
                        ))}
                    </div>
                    <div className="lp-keyword-result" aria-live="polite">
                        <strong>
                            <IconBulb size={14} aria-hidden="true" />
                            {category === 'missing'
                                ? 'Consider adding'
                                : category === 'partial'
                                  ? 'Make the connection clearer'
                                  : 'Already in your résumé'}
                        </strong>
                        <p>{keywords[category].join(', ')}</p>
                        <small className="sr-only">
                            Only include skills and experience you actually have.
                        </small>
                    </div>
                </div>
                <p className="lp-demo-caption">
                    Sample analysis — illustrative data.
                    <span className="sr-only"> Scores are feedback, not a hiring prediction.</span>
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
                    <h3>
                        <IconCircleDot size={12} aria-hidden="true" /> Job requirement
                    </h3>
                    <p>Design and build scalable, user-facing features using Python.</p>
                </div>
                <IconLine className="lp-flow-arrow" size={28} aria-hidden="true" />
                <div className="lp-tailor-cell">
                    <h3>Your matching experience</h3>
                    <ul className="lp-matching-experience">
                        <li>{decision === 'accepted' ? bullet : ORIGINAL_BULLET}</li>
                    </ul>
                </div>
                <IconLine className="lp-flow-arrow" size={28} aria-hidden="true" />
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
                        {decision === 'accepted' && <IconCheck size={13} aria-hidden="true" />}
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
            <p
                className={decision === 'pending' ? 'sr-only' : 'lp-demo-caption'}
                aria-live="polite"
            >
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
                                {status === 'Interview' ? (
                                    <IconSquareFilled size={12} aria-hidden="true" />
                                ) : (
                                    <IconCircleDot size={14} aria-hidden="true" />
                                )}
                                {status}
                                <span className="lp-board-count">
                                    {
                                        applications.filter(
                                            application => application.status === status
                                        ).length
                                    }
                                </span>
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
                                            {application.company} · {application.status}{' '}
                                            {
                                                ['Oct 10', 'Oct 8', 'Oct 5', 'Oct 1', 'Oct 12'][
                                                    application.id - 1
                                                ]
                                            }
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
            <p className="sr-only">Sample board — use a card menu to change its status.</p>
        </div>
    )
}

function LatexDemo() {
    const id = useId()
    const [engine, setEngine] = useState('pdflatex')
    const [sampleView, setSampleView] = useState<'source' | 'pdf'>('source')
    const engineNotes: Record<string, string> = {
        pdflatex: 'The classic compiler for everyday LaTeX documents.',
        xelatex: 'A compiler suited to Unicode text and system fonts.',
        lualatex: 'A modern compiler with Unicode and Lua support.',
    }
    return (
        <div className="lp-demo lp-latex-demo" data-view={sampleView}>
            <div className="lp-latex-source">
                <div className="lp-latex-tabs" role="tablist" aria-label="Explore the LaTeX sample">
                    {(['source', 'pdf'] as const).map(value => (
                        <button
                            key={value}
                            type="button"
                            role="tab"
                            id={`${id}-latex-${value}`}
                            aria-controls={`${id}-latex-panel`}
                            aria-selected={sampleView === value}
                            tabIndex={sampleView === value ? 0 : -1}
                            onClick={() => setSampleView(value)}
                            onKeyDown={event => {
                                if (
                                    ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)
                                ) {
                                    event.preventDefault()
                                    const next =
                                        event.key === 'Home'
                                            ? 'source'
                                            : event.key === 'End'
                                              ? 'pdf'
                                              : value === 'source'
                                                ? 'pdf'
                                                : 'source'
                                    setSampleView(next)
                                    document.getElementById(`${id}-latex-${next}`)?.focus()
                                }
                            }}
                        >
                            {value === 'source' ? 'Source' : 'PDF'}
                        </button>
                    ))}
                </div>
                <div
                    role="tabpanel"
                    id={`${id}-latex-panel`}
                    aria-labelledby={`${id}-latex-${sampleView}`}
                    tabIndex={0}
                >
                    {sampleView === 'source' ? (
                        <SourceCode source={SAMPLE_SOURCE} lineNumbers />
                    ) : (
                        <EquationSample />
                    )}
                </div>
            </div>
            <div className="lp-latex-preview">
                <div className="lp-preview-toolbar">
                    <span className="lp-demo-label">
                        <IconFileText size={12} aria-hidden="true" /> PDF
                    </span>
                    <CapabilityGate feature="a09">
                        <CapabilityGate feature="b01">
                            <CapabilityGate feature="c01">
                                <Link
                                    href="/try?mode=source"
                                    aria-label="Open full LaTeX preview in the studio"
                                    title="Open full LaTeX preview in the studio"
                                >
                                    <IconArrowsDiagonal size={13} aria-hidden="true" />
                                </Link>
                            </CapabilityGate>
                        </CapabilityGate>
                    </CapabilityGate>
                </div>
                <EquationSample />
            </div>
            <div className="lp-compiler-controls">
                <label htmlFor={`${id}-engine`}>Compiler</label>
                <select
                    id={`${id}-engine`}
                    value={engine}
                    onChange={event => setEngine(event.target.value)}
                >
                    <option value="pdflatex">pdfLaTeX</option>
                    <option value="xelatex">XeLaTeX</option>
                    <option value="lualatex">LuaLaTeX</option>
                </select>
                <p className="sr-only" aria-live="polite">
                    {engineNotes[engine]}
                </p>
                <CapabilityGate feature="a09">
                    <CapabilityGate feature="b01">
                        <CapabilityGate feature="c01">
                            <Link
                                className="lp-button-small lp-button-accent lp-compile-action"
                                href="/try?mode=source"
                                aria-label="Open the LaTeX studio to compile"
                                title="Open the LaTeX studio to compile"
                            >
                                Compile
                            </Link>
                        </CapabilityGate>
                    </CapabilityGate>
                </CapabilityGate>
                <p className="lp-demo-caption">A minimal example. Compile in the studio.</p>
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
