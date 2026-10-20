'use client'

import { useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import {
    IconCheck,
    IconArrowRight,
    IconFileText,
    IconCode,
    IconCircleCheck,
} from '@tabler/icons-react'
import Link from 'next/link'
import CapabilityGate from '@/components/CapabilityGate'

const feedback = {
    Structure: {
        title: 'Make the essentials easy to find.',
        checks: [
            'Use familiar headings such as Experience and Education.',
            'Keep role titles, companies, and dates together.',
            'Check that your PDF has readable, selectable text.',
        ],
        sample: 'Experience',
        detail: 'A clear heading helps both a reader and a parser find your work history.',
    },
    Keywords: {
        title: 'Use the language of the role.',
        checks: [
            'Compare the job description with your actual experience.',
            'Name the tools and skills you have used.',
            'Add context instead of repeating a keyword.',
        ],
        sample: 'Research → a design decision → what changed',
        detail: 'Explain how you used a skill. Only include experience you can discuss in an interview.',
    },
    Readability: {
        title: 'Give each sentence a job.',
        checks: [
            'Lead with a clear action.',
            'Replace vague claims with a specific contribution.',
            'Keep tense, punctuation, and dates consistent.',
        ],
        sample: 'Designed the checkout flow with research and engineering.',
        detail: 'A concrete contribution tells a reader more than “results-driven team player”.',
    },
} as const

const initialApplications = [
    {
        role: 'Product Designer',
        company: 'Northstar Studio',
        version: 'Product résumé',
        stage: 'Saved',
    },
    {
        role: 'Design Systems Designer',
        company: 'Fieldwork',
        version: 'Systems résumé',
        stage: 'Applied',
    },
]

export default function ReviewJourney() {
    const [review, setReview] = useState<keyof typeof feedback>('Structure')
    const [applications, setApplications] = useState(initialApplications)
    const [documentView, setDocumentView] = useState('PDF')
    const selected = feedback[review]
    return (
        <div className="rd-journey lp-container" id="product">
            <section
                className="rd-section lp-feature-row"
                id="resume-feedback"
                aria-labelledby="rd-feedback-title"
            >
                <div className="rd-section-copy">
                    <p className="rd-eyebrow">ATS feedback, with context</p>
                    <h2 id="rd-feedback-title">
                        Know what to improve
                        <br />
                        before you send.
                    </h2>
                    <p>
                        See how your résumé is structured, which skills match the role, and where
                        the wording needs work. Review each suggestion before changing your
                        document.
                    </p>
                    <p className="rd-context-note">
                        ATS feedback is guidance. It cannot guarantee an interview or compatibility
                        with every hiring system.
                    </p>
                </div>
                <Tabs.Root
                    value={review}
                    onValueChange={value => setReview(value as keyof typeof feedback)}
                    className="rd-report"
                >
                    <div className="rd-demo-top">
                        <span>Sample résumé review</span>
                        <IconCircleCheck size={18} stroke={1.5} aria-hidden="true" />
                    </div>
                    <Tabs.List className="rd-tab-list" aria-label="Explore sample ATS feedback">
                        {Object.keys(feedback).map(value => (
                            <Tabs.Trigger key={value} value={value}>
                                {value}
                            </Tabs.Trigger>
                        ))}
                    </Tabs.List>
                    <Tabs.Content className="rd-report-content" value={review}>
                        <h3>{selected.title}</h3>
                        <ul>
                            {selected.checks.map(check => (
                                <li key={check}>
                                    <IconCheck size={17} aria-hidden="true" />
                                    <span>{check}</span>
                                </li>
                            ))}
                        </ul>
                        <div className="rd-report-example">
                            <small>A closer look</small>
                            <p>{selected.sample}</p>
                            <span>{selected.detail}</span>
                        </div>
                    </Tabs.Content>
                </Tabs.Root>
            </section>
            <section
                className="rd-section rd-section-wide lp-full-section"
                id="applications"
                aria-labelledby="rd-applications-title"
            >
                <div className="rd-section-copy">
                    <p className="rd-eyebrow">The work around the application</p>
                    <h2 id="rd-applications-title">
                        A different role.
                        <br />
                        The right version.
                    </h2>
                    <p>
                        Tailor a résumé for each opportunity. Keep the version you sent, your cover
                        letter, and the next step in one workspace.
                    </p>
                </div>
                <div className="rd-application-list">
                    <div className="rd-demo-top">
                        <span>Your applications</span>
                        <span>Interactive sample</span>
                    </div>
                    {applications.map((application, index) => (
                        <article key={application.company} className="rd-application">
                            <IconFileText size={22} stroke={1.5} aria-hidden="true" />
                            <div>
                                <h3>{application.role}</h3>
                                <p>
                                    {application.company} <span aria-hidden="true">·</span>{' '}
                                    {application.version}
                                </p>
                            </div>
                            <label>
                                <span className="sr-only">
                                    Stage for {application.role} at {application.company}
                                </span>
                                <select
                                    value={application.stage}
                                    onChange={event =>
                                        setApplications(current =>
                                            current.map((item, itemIndex) =>
                                                itemIndex === index
                                                    ? { ...item, stage: event.target.value }
                                                    : item
                                            )
                                        )
                                    }
                                >
                                    {['Saved', 'Applied', 'Interview', 'Offer'].map(value => (
                                        <option key={value}>{value}</option>
                                    ))}
                                </select>
                            </label>
                        </article>
                    ))}
                    <p className="rd-demo-footnote">
                        Change a stage to try it. These are example applications.
                    </p>
                </div>
            </section>
            <section
                className="rd-section lp-feature-row"
                id="latex-studio"
                aria-labelledby="rd-latex-title"
            >
                <div className="rd-section-copy">
                    <p className="rd-eyebrow">A proper LaTeX studio</p>
                    <h2 id="rd-latex-title">
                        For the documents
                        <br />
                        beyond your résumé.
                    </h2>
                    <p>
                        Write a paper, prepare a report, or bring an existing LaTeX project. Edit
                        visually or in source, choose your compiler, and create a PDF.
                    </p>
                    <div className="rd-compiler-list">
                        <span>pdfLaTeX</span>
                        <span>XeLaTeX</span>
                        <span>LuaLaTeX</span>
                    </div>
                    <CapabilityGate feature="a09">
                        <CapabilityGate feature="b01">
                            <CapabilityGate feature="c01">
                                <Link className="rd-text-link" href="/try?mode=source">
                                    Explore the studio{' '}
                                    <IconArrowRight size={16} aria-hidden="true" />
                                </Link>
                            </CapabilityGate>
                        </CapabilityGate>
                    </CapabilityGate>
                </div>
                <Tabs.Root
                    value={documentView}
                    onValueChange={setDocumentView}
                    className="rd-document-demo"
                >
                    <div className="rd-demo-top">
                        <span>
                            <IconCode size={17} aria-hidden="true" /> research.tex
                        </span>
                        <Tabs.List className="rd-tab-list" aria-label="Explore the LaTeX document">
                            <Tabs.Trigger value="Source">Source</Tabs.Trigger>
                            <Tabs.Trigger value="PDF">PDF</Tabs.Trigger>
                        </Tabs.List>
                    </div>
                    <Tabs.Content value="Source" className="rd-document-source">
                        <pre>
                            <code>{String.raw`\documentclass{article}
\usepackage{amsmath}
\begin{document}
\section*{A note on energy}
The relation between mass and energy:
\[
  E = mc^2
\]
Here, $m$ denotes mass and $c$ the speed
of light in a vacuum.
\end{document}`}</code>
                        </pre>
                    </Tabs.Content>
                    <Tabs.Content value="PDF" className="rd-document-paper">
                        <small>RESEARCH NOTE</small>
                        <h3>A note on energy</h3>
                        <p>The relation between mass and energy:</p>
                        <p className="rd-equation" aria-label="E equals m c squared">
                            E = mc<sup>2</sup>
                        </p>
                        <p>
                            Here, <i>m</i> denotes mass and <i>c</i> the speed of light in a vacuum.
                        </p>
                    </Tabs.Content>
                    <p className="rd-demo-footnote">
                        Illustrative source and PDF. Compile your own document in the studio.
                    </p>
                </Tabs.Root>
            </section>
        </div>
    )
}
