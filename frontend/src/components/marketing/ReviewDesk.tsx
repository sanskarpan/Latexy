'use client'

import { useEffect, useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import {
    IconCheck,
    IconArrowRight,
    IconArrowBackUp,
    IconPencil,
    IconDownload,
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
    // Server-rendered samples stay readable while their controls wait for this
    // component's handlers. This is independent of remote feature availability.
    const [interactive, setInteractive] = useState(false)
    useEffect(() => setInteractive(true), [])
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

    return (
        <Tabs.Root
            className="rd-desk"
            value={stage}
            onValueChange={value => {
                setStage(value as ReviewStage)
                setMessage('')
            }}
            data-stage={stage.toLowerCase()}
            data-testid="review-desk"
        >
            <ReviewStageList selected={stage} disabled={!interactive} />
            <div className="rd-desk-scene">
                <aside className="ts-paper-caption" aria-label="Sample résumé preview">
                    <strong>Résumé preview</strong>
                    <span>Professional design, typeset in LaTeX.</span>
                </aside>
                <article
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
                            <li className="rd-highlight" data-accepted={accepted}>
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
                <div className="rd-annotation">
                    <Tabs.Content value="Write" className="rd-note">
                        <p className="rd-note-kicker">
                            <IconPencil size={14} aria-hidden="true" /> Write in your own words
                        </p>
                        <h3>Start with what you did.</h3>
                        <label htmlFor="hero-sample-role">Your role</label>
                        <input
                            id="hero-sample-role"
                            disabled={!interactive}
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
                            disabled={!interactive}
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
                            disabled={!interactive}
                            onClick={() => {
                                const next = draft.trim()
                                if (!next || !roleDraft.trim()) {
                                    setMessage('')
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
                                disabled={!interactive || (!accepted && !canUseExample)}
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
                                disabled={!interactive}
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
                            disabled={!interactive}
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
                                        disabled={!interactive}
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
