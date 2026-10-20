'use client'

import { useEffect, useRef, useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import {
    IconCheck,
    IconArrowRight,
    IconArrowBackUp,
    IconPencil,
    IconDownload,
    IconArrowCurveLeft,
} from '@tabler/icons-react'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { MarketingCTA } from './MarketingCTA'
import { ReviewStageList, type ReviewStage } from './ReviewStages'
import '@fontsource/tinos/latin-400.css'
import '@fontsource/tinos/latin-700.css'

const original = 'Worked with engineering to ship the checkout flow.'
const suggested = 'Designed the checkout flow with research and engineering.'
const layouts = ['Classic', 'Modern', 'Minimal'] as const

export default function ReviewDesk() {
    const { can, loading, error } = useEntitlements()
    const [stage, setStage] = useState<ReviewStage>('Review')
    const [bullet, setBullet] = useState(original)
    const [draft, setDraft] = useState(original)
    const [draftDirty, setDraftDirty] = useState(false)
    const [beforeSuggestion, setBeforeSuggestion] = useState(original)
    const [layout, setLayout] = useState<(typeof layouts)[number]>('Classic')
    const [role, setRole] = useState('Product Designer')
    const [roleDraft, setRoleDraft] = useState('Product Designer')
    const [writeError, setWriteError] = useState('')
    const canUseExample = bullet === original
    const [accepted, setAccepted] = useState(false)
    const [message, setMessage] = useState('')
    const [target, setTarget] = useState('Product design')
    const deskRef = useRef<HTMLDivElement>(null)
    const paperRef = useRef<HTMLElement>(null)
    const highlightRef = useRef<HTMLLIElement>(null)
    const annotationRef = useRef<HTMLDivElement>(null)

    // Keep the annotation tied to the selected sentence as text and fonts
    // reflow. Only geometry changes; the document itself is never transformed.
    useEffect(() => {
        const desk = deskRef.current
        const paper = paperRef.current
        const highlight = highlightRef.current
        const annotation = annotationRef.current
        if (!desk || !paper || !highlight || !annotation) return
        const align = () => {
            const sentence = highlight.getBoundingClientRect()
            const sheet = paper.getBoundingClientRect()
            if (window.matchMedia('(max-width: 599px)').matches) {
                const length = annotation.getBoundingClientRect().top + 24 - sentence.top - 16
                desk.style.setProperty('--rd-connector-length', `${Math.max(24, length)}px`)
                desk.style.removeProperty('--rd-scene-height')
            } else {
                const anchor = Math.max(70, sentence.top - sheet.top - 60)
                desk.style.setProperty('--rd-note-anchor', `${anchor}px`)
                desk.style.setProperty(
                    '--rd-connector-width',
                    `${Math.max(6, annotation.getBoundingClientRect().left - sentence.right - 1)}px`
                )
                desk.style.setProperty(
                    '--rd-scene-height',
                    `${Math.max(sheet.height, anchor + annotation.offsetHeight)}px`
                )
            }
        }
        align()
        const observer = new ResizeObserver(align)
        observer.observe(paper)
        observer.observe(annotation)
        let disposed = false
        void document.fonts.ready.then(() => {
            if (!disposed) align()
        })
        return () => {
            disposed = true
            observer.disconnect()
        }
    }, [stage, bullet, role, layout, accepted])

    return (
        <Tabs.Root
            ref={deskRef}
            className="rd-desk"
            value={stage}
            onValueChange={value => {
                setStage(value as ReviewStage)
                setMessage('')
            }}
            data-stage={stage.toLowerCase()}
            data-testid="review-desk"
        >
            <ReviewStageList selected={stage} />
            <div className="rd-desk-scene">
                <aside className="ts-paper-caption" aria-label="Sample résumé preview">
                    <strong>Résumé preview</strong>
                    <span>Professional design,<br />typeset in LaTeX.</span>
                    <IconArrowCurveLeft size={62} stroke={0.8} aria-hidden="true" />
                </aside>
                <article
                    ref={paperRef}
                    className="rd-paper"
                    data-layout={layout.toLowerCase()}
                    aria-label={`${layout} sample résumé`}
                >
                    <header>
                        <h2>Alex Morgan</h2>
                        <p>{role.trim() || 'Your role'}</p>
                        <small>
                            London, UK <span aria-hidden="true">·</span> alex@example.com
                        </small>
                    </header>
                    <section>
                        <h3>Experience</h3>
                        <div className="rd-paper-job">
                            <strong>{role.trim() || 'Your role'}</strong>
                            <span>2022 — Present</span>
                        </div>
                        <p className="rd-paper-company">Nova Systems</p>
                        <ul>
                            <li>
                                Led the redesign of the onboarding experience, from research to
                                delivery.
                            </li>
                            <li
                                ref={highlightRef}
                                className="rd-highlight"
                                data-accepted={accepted}
                            >
                                {bullet.trim() || 'Your experience goes here.'}
                            </li>
                            <li className="rd-paper-secondary">
                                Conducted user research and turned insights into product
                                improvements.
                            </li>
                            <li className="rd-paper-secondary">
                                Owned the design system and component library.
                            </li>
                        </ul>
                    </section>
                    <section className="rd-paper-history">
                        <div className="rd-paper-job">
                            <strong>Junior Product Designer</strong>
                            <span>2020 — 2022</span>
                        </div>
                        <p className="rd-paper-company">BrightCode</p>
                        <ul>
                            <li>Designed features across web and mobile.</li>
                            <li>Collaborated with engineering to ship accessible features.</li>
                        </ul>
                    </section>
                </article>
                <div ref={annotationRef} className="rd-annotation">
                    <Tabs.Content value="Write" className="rd-note">
                        <p className="rd-note-kicker">
                            <IconPencil size={14} aria-hidden="true" /> Write in your own words
                        </p>
                        <h3>Start with what you did.</h3>
                        <label htmlFor="hero-sample-role">Your role</label>
                        <input
                            id="hero-sample-role"
                            value={roleDraft}
                            onChange={event => {
                                setRoleDraft(event.target.value)
                                setWriteError('')
                            }}
                            aria-invalid={Boolean(writeError) && !roleDraft.trim()}
                            aria-describedby={writeError ? 'hero-write-error' : undefined}
                            maxLength={60}
                        />
                        <label htmlFor="hero-sample-bullet">One contribution</label>
                        <textarea
                            id="hero-sample-bullet"
                            value={draft}
                            onChange={event => {
                                setDraft(event.target.value)
                                setDraftDirty(true)
                                setWriteError('')
                            }}
                            aria-invalid={Boolean(writeError) && !draft.trim()}
                            aria-describedby={writeError ? 'hero-write-error' : undefined}
                            maxLength={240}
                            rows={3}
                        />
                        <button
                            type="button"
                            className="rd-small-primary"
                            onClick={() => {
                                const next = draft.trim()
                                if (!next || !roleDraft.trim()) {
                                    setWriteError(
                                        'Enter a role and a contribution before updating the sample.'
                                    )
                                    return
                                }
                                setWriteError('')
                                setRole(roleDraft.trim())
                                setBullet(next)
                                setDraft(next)
                                setDraftDirty(false)
                                setAccepted(false)
                                setMessage('Your wording is now in the sample résumé.')
                            }}
                        >
                            Update sample <IconArrowRight size={13} aria-hidden="true" />
                        </button>
                        {writeError && (
                            <p id="hero-write-error" className="rd-field-error" role="alert">
                                {writeError}
                            </p>
                        )}
                    </Tabs.Content>
                    <Tabs.Content value="Review" className="rd-note">
                        <h3>
                            {accepted
                                ? 'Your contribution, clearer.'
                                : 'Make the contribution clear'}
                        </h3>
                        <p>
                            Be specific about what you did, who you worked with, and the outcome
                            when possible.
                        </p>
                        <blockquote>{suggested}</blockquote>
                        <p className="rd-example-note">
                            {canUseExample || accepted
                                ? 'Illustrative suggestion for the starter sentence.'
                                : 'This suggestion only fits the starter sentence. Your contribution stays unchanged.'}
                        </p>
                        <div className="rd-note-actions">
                            <button
                                type="button"
                                className="rd-small-primary"
                                disabled={!accepted && !canUseExample}
                                onClick={() => {
                                    if (accepted) {
                                        setBullet(beforeSuggestion)
                                        if (!draftDirty) setDraft(beforeSuggestion)
                                        setAccepted(false)
                                        setMessage('Your previous wording has been restored.')
                                    } else {
                                        setBeforeSuggestion(bullet)
                                        if (!draftDirty) setDraft(suggested)
                                        setBullet(suggested)
                                        setAccepted(true)
                                        setMessage(
                                            'Suggestion applied to the sample. You can undo it.'
                                        )
                                    }
                                }}
                            >
                                {accepted ? (
                                    <>
                                        <IconArrowBackUp size={13} aria-hidden="true" /> Undo
                                    </>
                                ) : (
                                    'Use suggestion'
                                )}
                            </button>
                            <button
                                type="button"
                                className="rd-small-secondary"
                                onClick={() => {
                                    if (accepted) {
                                        setBullet(beforeSuggestion)
                                        if (!draftDirty) setDraft(beforeSuggestion)
                                    }
                                    setAccepted(false)
                                    setMessage(
                                        'Original wording kept. You decide what goes on the page.'
                                    )
                                }}
                            >
                                Keep original
                            </button>
                        </div>
                    </Tabs.Content>
                    <Tabs.Content value="Tailor" className="rd-note">
                        <p className="rd-note-kicker">A version for the role</p>
                        <h3>Start with the job, not a keyword list.</h3>
                        <label htmlFor="hero-target-role">Sample role</label>
                        <select
                            id="hero-target-role"
                            value={target}
                            onChange={event => setTarget(event.target.value)}
                        >
                            <option>Product design</option>
                            <option>Design systems</option>
                        </select>
                        <blockquote>
                            {target === 'Product design'
                                ? 'Looking for experience with research, prototyping, and working with engineers.'
                                : 'Looking for experience building accessible components and maintaining a design system.'}
                        </blockquote>
                        <p>
                            {target === 'Product design'
                                ? 'Your checkout work is relevant. Explain how research shaped the design.'
                                : 'Your component-library work is relevant. Explain how other teams used it.'}
                        </p>
                    </Tabs.Content>
                    <Tabs.Content value="Export" className="rd-note">
                        <p className="rd-note-kicker">
                            <IconDownload size={14} aria-hidden="true" /> The finishing details
                        </p>
                        <h3>A layout that lets your work read.</h3>
                        <fieldset className="rd-layout-options">
                            <legend>Choose a sample layout</legend>
                            {layouts.map(value => (
                                <label key={value}>
                                    <input
                                        type="radio"
                                        name="hero-layout"
                                        value={value}
                                        checked={layout === value}
                                        onChange={() => setLayout(value)}
                                    />
                                    <span>{value}</span>
                                </label>
                            ))}
                        </fieldset>
                        <p>
                            Preview a layout here.{' '}
                            {error
                                ? 'PDF export availability could not be verified.'
                                : loading
                                    ? 'Checking PDF export availability.'
                                    : can('c05')
                                        ? 'PDF export is available when studio access is enabled.'
                                        : 'PDF export is currently unavailable.'}
                        </p>
                        <MarketingCTA label="Open the studio" />
                    </Tabs.Content>
                </div>
            </div>
            <div className="rd-desk-caption">
                <span>Illustrative, interactive sample</span>
                <span>Try a step. Your edits stay here.</span>
            </div>
            <p className="rd-sample-status" role="status">
                {message && (
                    <>
                        <IconCheck size={14} aria-hidden="true" /> {message}
                    </>
                )}
            </p>
            <noscript>
                <p className="rd-noscript">
                    This is an illustrative résumé review. Open the studio to work on your own
                    document.
                </p>
            </noscript>
        </Tabs.Root>
    )
}
