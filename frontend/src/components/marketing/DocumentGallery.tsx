'use client'

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { IconChevronDown } from '@tabler/icons-react'
import type { DocumentStageState } from './DocumentStage'
import './document-scene.css'

const layouts = ['Classic', 'Modern', 'Minimal'] as const
type Layout = (typeof layouts)[number]

function ResumePaper({ layout }: { layout: Layout }) {
    return (
        <article className="lp-hero-paper" aria-label={`${layout} sample résumé`}>
            <header>
                <h2>Alex Morgan</h2>
                <p>Senior Software Engineer</p>
                <small>London · alex@example.com</small>
            </header>
            <section className="lp-hero-paper-profile">
                <h3>Profile</h3>
                <p>Building thoughtful products, accessible interfaces, and dependable systems.</p>
            </section>
            <section>
                <h3>Experience</h3>
                <div className="lp-hero-paper-role">
                    <strong>Senior Software Engineer</strong>
                    <span>2021 — Present</span>
                </div>
                <p className="lp-hero-paper-company">BrightCode</p>
                <ul>
                    <li>Built user-facing products in Python.</li>
                    <li>Partnered with design and engineering.</li>
                    <li className="lp-hero-paper-extra">Improved accessibility and tooling.</li>
                </ul>
                <div className="lp-hero-paper-role lp-hero-paper-extra">
                    <strong>Software Engineer</strong>
                    <span>2018 — 2021</span>
                </div>
                <p className="lp-hero-paper-company lp-hero-paper-extra">Northwind</p>
                <p className="lp-hero-paper-extra">
                    Delivered product features and improved engineering practices.
                </p>
            </section>
            <section>
                <h3>Education</h3>
                <strong>BSc Computer Science</strong>
                <p>University of Bristol · 2014 — 2018</p>
            </section>
            <section className="lp-hero-paper-skills">
                <h3>Skills</h3>
                <p>Python · TypeScript · React · System design</p>
            </section>
        </article>
    )
}

export default function DocumentGallery() {
    const [layout, setLayout] = useState<Layout>('Classic')
    const [expanded, setExpanded] = useState(false)
    const [reducedMotion, setReducedMotion] = useState(true)
    const [dark, setDark] = useState(false)
    const scene = useRef<HTMLDivElement>(null)
    const stage = useRef<HTMLDivElement>(null)
    const stageState = useRef<DocumentStageState>({ dark: false, selected: 0, reducedMotion: true })
    const controls = useRef<Partial<Record<Layout, HTMLButtonElement>>>({})
    const pointer = useRef({ x: 0, y: 0 })
    const invalidate = useRef<(() => void) | null>(null)
    const pointerFrame = useRef<number | null>(null)
    useEffect(() => {
        stageState.current = { dark, selected: layouts.indexOf(layout), reducedMotion }
        invalidate.current?.()
    }, [dark, layout, reducedMotion])
    useEffect(() => {
        let cancelled = false
        let cleanup = () => {}
        import('./DocumentStage')
            .then(({ mountDocumentStage }) => {
                if (!cancelled && stage.current)
                    cleanup = mountDocumentStage(stage.current, stageState, pointer, invalidate)
            })
            .catch(() => {
                if (!cancelled && stage.current) stage.current.dataset.renderer = 'unavailable'
            })
        return () => {
            cancelled = true
            cleanup()
        }
    }, [])
    useEffect(() => {
        const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
        const update = () => {
            setReducedMotion(preference.matches)
            pointer.current = { x: 0, y: 0 }
            scene.current?.style.setProperty('--scene-x', '0deg')
            scene.current?.style.setProperty('--scene-y', '0deg')
            invalidate.current?.()
        }
        update()
        const syncTheme = () => setDark(document.documentElement.dataset.mode === 'dark')
        syncTheme()
        const theme = new MutationObserver(syncTheme)
        theme.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-mode'],
        })
        preference.addEventListener('change', update)
        return () => {
            theme.disconnect()
            preference.removeEventListener('change', update)
            if (pointerFrame.current !== null) cancelAnimationFrame(pointerFrame.current)
        }
    }, [])
    const resetPointer = () => {
        pointer.current = { x: 0, y: 0 }
        scene.current?.style.setProperty('--scene-x', '0deg')
        scene.current?.style.setProperty('--scene-y', '0deg')
        invalidate.current?.()
    }
    return (
        <div className="lp-gallery" data-mobile-expanded={expanded}>
            <div
                className="lp-gallery-art lp-document-scene"
                id="landing-document-samples"
                ref={scene}
                data-layout={layout}
                data-reduced-motion={reducedMotion}
                onPointerLeave={resetPointer}
                onPointerMove={event => {
                    if (reducedMotion || event.pointerType !== 'mouse') return
                    const box = event.currentTarget.getBoundingClientRect()
                    pointer.current = {
                        x: ((event.clientX - box.left) / box.width - 0.5) * 2,
                        y: ((event.clientY - box.top) / box.height - 0.5) * 2,
                    }
                    if (pointerFrame.current !== null) return
                    pointerFrame.current = requestAnimationFrame(() => {
                        pointerFrame.current = null
                        scene.current?.style.setProperty('--scene-x', `${pointer.current.x * 2}deg`)
                        scene.current?.style.setProperty('--scene-y', `${-pointer.current.y}deg`)
                        invalidate.current?.()
                    })
                }}
            >
                <div className="lp-document-stage" ref={stage} aria-hidden="true" />
                {layouts.map((name, index) => {
                    const offset = (index - layouts.indexOf(layout) + 3) % 3
                    const slot = offset === 0 ? 'center' : offset === 1 ? 'right' : 'left'
                    return (
                        <figure
                            className="lp-document-card"
                            data-slot={slot}
                            data-template={name}
                            aria-hidden={name !== layout}
                            key={name}
                            style={{ '--card-index': index } as CSSProperties}
                        >
                            <figcaption>
                                <span>0{index + 1}</span> {name}
                                <span className="lp-document-caption-note">
                                    {name === layout ? 'Selected layout' : 'Sample layout'}
                                </span>
                            </figcaption>
                            <div className="lp-document-mat">
                                <ResumePaper layout={name} />
                            </div>
                        </figure>
                    )
                })}
            </div>
            <div className="lp-gallery-controls">
                <span>Choose a layout</span>
                <div role="group" aria-label="Sample résumé layouts">
                    {layouts.map((name, index) => (
                        <button
                            type="button"
                            key={name}
                            aria-pressed={layout === name}
                            ref={button => {
                                if (button) controls.current[name] = button
                            }}
                            onClick={() => setLayout(name)}
                            onKeyDown={event => {
                                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
                                    return
                                event.preventDefault()
                                const next =
                                    event.key === 'Home'
                                        ? layouts[0]
                                        : event.key === 'End'
                                          ? layouts[2]
                                          : layouts[
                                                (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3
                                            ]
                                setLayout(next)
                                controls.current[next]?.focus()
                            }}
                        >
                            <span>0{index + 1}</span>
                            {name}
                        </button>
                    ))}
                </div>
            </div>
            <button
                type="button"
                className="lp-mobile-sample-toggle"
                aria-expanded={expanded}
                aria-controls="landing-document-samples"
                onClick={() => setExpanded(value => !value)}
            >
                {expanded ? 'Show compact preview' : 'Read the full sample'}
                <IconChevronDown
                    size={16}
                    aria-hidden="true"
                    style={{ transform: expanded ? 'rotate(180deg)' : undefined }}
                />
            </button>
            <p className="sr-only" aria-live="polite">
                {layout} selected. The résumé moves to the centre. Sample content, not your
                document.
            </p>
        </div>
    )
}
