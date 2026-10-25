'use client'

import { useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import {
    IconFileText,
    IconMessage,
    IconAdjustmentsHorizontal,
    IconArrowRight,
    IconArrowNarrowRight,
    IconCheck,
    IconArrowBackUp,
    IconCode,
} from '@tabler/icons-react'

const steps = [
    {
        title: 'Write',
        copy: 'Start with your experience and goals in a clean workspace.',
        icon: IconFileText,
        href: '#landing-title',
    },
    {
        title: 'Review',
        copy: 'Consider suggestions on structure, content, and readability.',
        icon: IconMessage,
        href: '#resume-feedback',
    },
    {
        title: 'Tailor',
        copy: 'Bring relevant experience forward for each opportunity.',
        icon: IconAdjustmentsHorizontal,
        href: '#tailor-application',
    },
    {
        title: 'Export',
        copy: 'Refine your layout and compile a PDF when available.',
        icon: IconFileText,
        href: '#source-to-pdf',
    },
]

export function TypesetWorkflow() {
    return (
        <section className="ts-workflow lp-container" aria-labelledby="workflow-heading">
            <div className="ts-workflow-heading">
                <div>
                    <p className="rd-eyebrow">01 — 04</p>
                    <h2 id="workflow-heading">
                        From first draft
                        <br />
                        to final PDF.
                    </h2>
                </div>
                <p className="ts-section-description">
                    A considered workflow to help you write, get feedback, tailor, and export. All
                    in one place.
                </p>
            </div>
            <ol>
                {steps.map(({ title, copy, icon: Icon, href }, i) => (
                    <li key={title}>
                        <a href={href}>
                            <span className="ts-step-icon">
                                <Icon size={30} stroke={1.5} aria-hidden="true" />
                            </span>
                            <h3>
                                {i + 1}. {title}
                            </h3>
                            <p>{copy}</p>
                        </a>
                        {i < 3 && (
                            <span className="ts-step-arrow" aria-hidden="true">
                                <IconArrowNarrowRight size={28} stroke={0.8} />
                            </span>
                        )}
                    </li>
                ))}
            </ol>
        </section>
    )
}

const reviews = {
    Structure: {
        original: 'Worked with engineering to ship the checkout flow.',
        suggestion: 'Designed the checkout flow with research and engineering.',
        explanation: 'Make your contribution easier to find. Start with the work you owned.',
        label: 'Line review',
    },
    Keywords: {
        original: 'Owned the design system and component library.',
        suggestion: 'Maintained the design system and reusable interface components.',
        explanation:
            'Use relevant terms naturally, and only when they describe work you actually did.',
        label: 'Keyword context',
    },
    Readability: {
        original: 'Conducted user research and turned insights into product improvements.',
        suggestion: 'Used research insights to improve the product.',
        explanation:
            'A shorter sentence can make the main point easier to scan. Keep the detail you need.',
        label: 'Readability check',
    },
}
type Review = keyof typeof reviews

export function TypesetReview() {
    const [topic, setTopic] = useState<Review>('Structure')
    const [accepted, setAccepted] = useState<Record<Review, boolean>>({
        Structure: false,
        Keywords: false,
        Readability: false,
    })
    const [status, setStatus] = useState('')
    const current = reviews[topic]
    return (
        <section id="resume-feedback" className="ts-review-band" aria-labelledby="review-heading">
            <div className="lp-container ts-feature">
                <div className="ts-section-copy">
                    <p className="rd-eyebrow">A closer look</p>
                    <h2 id="review-heading">
                        Thoughtful <br />
                        feedback, <br />
                        right where <br />
                        you write.
                    </h2>
                    <p className="ts-section-description">
                        Examine structure, keywords, and readability. Consider each suggestion, then
                        choose what belongs on your page.
                    </p>
                    <p className="ts-small-note">
                        ATS feedback is guidance, not a hiring prediction.
                    </p>
                </div>
                <Tabs.Root
                    className="ts-review-demo"
                    value={topic}
                    onValueChange={value => {
                        setTopic(value as Review)
                        setStatus('')
                    }}
                >
                    <Tabs.List aria-label="Explore sample feedback" className="ts-review-tabs">
                        {Object.keys(reviews).map(key => (
                            <Tabs.Trigger key={key} value={key}>
                                {key}
                            </Tabs.Trigger>
                        ))}
                    </Tabs.List>
                    {(Object.keys(reviews) as Review[]).map(key => (
                        <Tabs.Content value={key} key={key} className="ts-review-content">
                            <div className="ts-review-excerpt">
                                <p className="ts-document-label">Experience</p>
                                <div className="ts-job">
                                    <strong>Product Designer</strong>
                                    <span>2022 — Present</span>
                                </div>
                                <p>Nova Systems</p>
                                <ul>
                                    {(Object.keys(reviews) as Review[]).map(item => (
                                        <li
                                            key={item}
                                            className={item === key ? 'ts-line-selected' : ''}
                                        >
                                            {accepted[item]
                                                ? reviews[item].suggestion
                                                : reviews[item].original}
                                        </li>
                                    ))}
                                    <li>
                                        Built a shared reporting dashboard with research and
                                        engineering.
                                    </li>
                                </ul>
                                <p className="ts-small-note">
                                    Illustrative sample. No AI is running here.
                                </p>
                            </div>
                            <aside className="ts-review-note">
                                <h3>{current.label}</h3>
                                <p>{current.explanation}</p>
                                <h4>Suggested revision</h4>
                                <p className="ts-suggestion">{current.suggestion}</p>
                                <div className="ts-demo-actions">
                                    <button
                                        type="button"
                                        className="rd-small-primary"
                                        onClick={() => {
                                            setAccepted(a => ({ ...a, [topic]: !a[topic] }))
                                            setStatus(
                                                accepted[topic]
                                                    ? 'Previous wording restored.'
                                                    : 'Suggestion applied to this sample.'
                                            )
                                        }}
                                    >
                                        {accepted[topic] ? (
                                            <>
                                                <IconArrowBackUp size={14} aria-hidden="true" />{' '}
                                                Undo
                                            </>
                                        ) : (
                                            'Use suggestion'
                                        )}
                                    </button>
                                    <button
                                        type="button"
                                        className="rd-small-secondary"
                                        onClick={() => {
                                            setAccepted(a => ({ ...a, [topic]: false }))
                                            setStatus('Original wording kept.')
                                        }}
                                    >
                                        Keep original
                                    </button>
                                </div>
                            </aside>
                        </Tabs.Content>
                    ))}
                    <p className="ts-status" role="status">
                        {status && (
                            <>
                                <IconCheck size={14} aria-hidden="true" />
                                {status}
                            </>
                        )}
                    </p>
                </Tabs.Root>
            </div>
        </section>
    )
}

export function SampleDocument({
    tailored = false,
    compact = false,
    serif = true,
    relaxed = false,
}: {
    tailored?: boolean
    compact?: boolean
    serif?: boolean
    relaxed?: boolean
}) {
    return (
        <article
            className={`ts-document ${compact ? 'ts-document-compact' : ''} ${serif ? '' : 'ts-document-sans'} ${relaxed ? 'ts-document-relaxed' : ''}`}
            aria-label={tailored ? 'Illustrative tailored résumé' : 'Illustrative general résumé'}
        >
            <header>
                <h3>Alex Morgan</h3>
                <p>Product Designer</p>
                <small>London, UK · alex@example.com</small>
            </header>
            <p className="ts-document-label">Experience</p>
            <div className="ts-job">
                <strong>Product Designer</strong>
                <span>2022 — Present</span>
            </div>
            <p>Nova Systems</p>
            <ul>
                <li>
                    {tailored
                        ? 'Conducted interviews to understand user needs and shape product direction.'
                        : 'Led the redesign of the onboarding experience, from research to delivery.'}
                </li>
                <li>
                    {tailored
                        ? 'Turned research findings into prototypes for team feedback.'
                        : 'Built a reporting dashboard with research and engineering.'}
                </li>
                {!compact && (
                    <li>
                        {tailored
                            ? 'Collaborated with engineers to deliver accessible product improvements.'
                            : 'Maintained the design system and component library.'}
                    </li>
                )}
                {!compact && (
                    <li>
                        {tailored
                            ? 'Used usability feedback to refine accessible web and mobile features.'
                            : 'Conducted user research and turned insights into product improvements.'}
                    </li>
                )}
            </ul>
        </article>
    )
}

export function TypesetVersions() {
    const [role, setRole] = useState('research')
    return (
        <section
            className="lp-container ts-feature ts-versions"
            id="tailor-application"
            aria-labelledby="tailor-heading"
        >
            <div className="ts-section-copy">
                <p className="rd-eyebrow">Tailor each application</p>
                <h2 id="tailor-heading">
                    Different roles. <br />
                    Sharper résumés.
                </h2>
                <p className="ts-section-description">
                    Keep one version for your general profile, then tailor versions for specific
                    opportunities with guidance on what to emphasize.
                </p>
                <label htmlFor="ts-target-role" className="ts-control-label">
                    Explore a sample focus
                </label>
                <select
                    id="ts-target-role"
                    value={role}
                    onChange={event => setRole(event.target.value)}
                >
                    <option value="research">Research-focused role</option>
                    <option value="general">General product design</option>
                </select>
                <p className="ts-small-note">Illustrative versions, using the same experience.</p>
            </div>
            <div className="ts-document-pair">
                <figure>
                    <SampleDocument />
                    <figcaption>
                        <strong>General version</strong>
                        <span>A balanced résumé for a wide range of opportunities.</span>
                    </figcaption>
                </figure>
                <figure>
                    <SampleDocument tailored={role === 'research'} />
                    <figcaption>
                        <strong>
                            {role === 'research'
                                ? 'Tailored for a research-focused role'
                                : 'General product design focus'}
                        </strong>
                        <span>
                            {role === 'research'
                                ? 'Relevant research experience moves to the foreground.'
                                : 'A broad view of product delivery and collaboration.'}
                        </span>
                    </figcaption>
                </figure>
            </div>
        </section>
    )
}

export function TypesetSource() {
    const [typeface, setTypeface] = useState('serif')
    const [spacing, setSpacing] = useState('normal')
    return (
        <section
            className="lp-container ts-feature ts-source"
            id="source-to-pdf"
            aria-labelledby="source-heading"
        >
            <div className="ts-section-copy">
                <p className="rd-eyebrow">From source to PDF</p>
                <h2 id="source-heading">
                    Real documents. <br />
                    Beautifully typeset.
                </h2>
                <p className="ts-section-description">
                    Write in a focused editor, then compile a professional PDF with LaTeX. Adjust
                    the details to suit the document.
                </p>
                <p className="ts-small-note">
                    This is a live HTML layout sample. PDF generation happens in the studio when
                    compilation is enabled.
                </p>
            </div>
            <div className="ts-source-demo">
                <div className="ts-code-panel">
                    <p className="ts-panel-label">
                        <IconCode size={15} aria-hidden="true" /> main.tex
                    </p>
                    <pre aria-label="Illustrative LaTeX source">
                        <code>
                            {String.raw`\section{Experience}
\textbf{Product Designer}
\textit{Nova Systems}
\begin{itemize}
  \item Led the redesign of
    the onboarding experience,
    from research to delivery.
  \item Built a reporting
    dashboard with research
    and engineering.
\end{itemize}`
                                .split('\n')
                                .map((line, index) => (
                                    <span className="ts-code-line" key={index}>
                                        <span className="ts-line-number" aria-hidden="true">
                                            {index + 1}
                                        </span>
                                        <span>
                                            {line.split(/(\\[a-zA-Z]+)/g).map((token, part) => (
                                                <span
                                                    key={part}
                                                    className={
                                                        token.startsWith('\\')
                                                            ? 'ts-code-command'
                                                            : undefined
                                                    }
                                                >
                                                    {token}
                                                </span>
                                            ))}
                                        </span>
                                    </span>
                                ))}
                        </code>
                    </pre>
                </div>
                <div className="ts-preview-panel">
                    <p className="ts-panel-label">
                        Layout preview <span>Illustrative</span>
                    </p>
                    <div className="ts-preview-controls">
                        <label>
                            Typeface
                            <select
                                value={typeface}
                                onChange={event => setTypeface(event.target.value)}
                            >
                                <option value="serif">Tinos (serif)</option>
                                <option value="sans">Sans serif</option>
                            </select>
                        </label>
                        <label>
                            Spacing
                            <select
                                value={spacing}
                                onChange={event => setSpacing(event.target.value)}
                            >
                                <option value="normal">Normal</option>
                                <option value="relaxed">Relaxed</option>
                            </select>
                        </label>
                    </div>
                    <p id="ts-preview-help" className="ts-preview-help">
                        Scroll within the preview to read the full sample.
                    </p>
                    <div
                        className="ts-preview-scroll"
                        role="region"
                        aria-label="Scrollable layout preview"
                        aria-describedby="ts-preview-help"
                        tabIndex={0}
                    >
                        <SampleDocument
                            compact
                            serif={typeface === 'serif'}
                            relaxed={spacing === 'relaxed'}
                        />
                    </div>
                </div>
            </div>
        </section>
    )
}
