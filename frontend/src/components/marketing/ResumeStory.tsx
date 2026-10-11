'use client'

import { useState } from 'react'
import { Check, ArrowUpRight, Sparkles } from 'lucide-react'

const examples = [
    {
        label: 'Make it clearer',
        before: 'Responsible for helping customers and answering their questions.',
        after: 'Guided customers through onboarding, answered product questions, and resolved everyday support issues.',
        reason: 'Replace a vague responsibility with the work you actually did.',
    },
    {
        label: 'Show your impact',
        before: 'Worked on improving the onboarding process.',
        after: 'Updated the onboarding guide and introduced a weekly check-in to help new customers get started.',
        reason: 'Name your contribution. Add measured results only when you have them.',
    },
    {
        label: 'Keep it relevant',
        before: 'Helped several teams with different tasks.',
        after: 'Coordinated customer feedback with product and support teams to prioritise recurring issues.',
        reason: 'Highlight relevant collaboration without adding unverified claims.',
    },
]

export default function ResumeStory() {
    const [selected, setSelected] = useState(0)
    const [accepted, setAccepted] = useState(false)
    const example = examples[selected]
    return (
        <div className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-line-2 bg-surface shadow-[var(--shadow-2)]">
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
                <span className="flex items-center gap-2 text-sm font-semibold">
                    <span className="h-2 w-2 rounded-full bg-accent" />
                    Your résumé, taking shape
                </span>
                <span className="text-xs text-fg-3">Interactive example</span>
            </div>
            <div className="p-5 sm:p-7">
                <div className="rounded-[var(--radius-md)] border border-line bg-bg p-6">
                    <p className="font-display text-2xl font-semibold tracking-tight">
                        Alex Morgan
                    </p>
                    <p className="mt-1 text-sm text-fg-3">Customer success · London</p>
                    <div className="my-4 h-px bg-line-2" />
                    <p className="text-xs font-semibold uppercase tracking-widest text-accent-strong">
                        Experience
                    </p>
                    <div className="mt-3 flex flex-wrap justify-between gap-2">
                        <p className="text-sm font-semibold">Customer Success Associate</p>
                        <p className="text-xs text-fg-3">2023 — Present</p>
                    </div>
                    <p className="mt-3 text-sm leading-relaxed text-fg-2" aria-live="polite">
                        {accepted ? example.after : example.before}
                    </p>
                </div>
                <div
                    className="mt-5 flex flex-wrap gap-2"
                    role="group"
                    aria-label="Choose a writing example"
                >
                    {examples.map((item, i) => (
                        <button
                            key={item.label}
                            type="button"
                            aria-pressed={i === selected}
                            onClick={() => {
                                setSelected(i)
                                setAccepted(false)
                            }}
                            className={`min-h-10 rounded-full border px-3 text-sm transition motion-reduce:transition-none ${selected === i ? 'border-accent bg-accent-soft text-accent-strong' : 'border-line text-fg-2 hover:border-accent'}`}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>
                <div className="mt-5 rounded-[var(--radius-md)] border border-line bg-surface-2 p-5">
                    <p className="flex items-center gap-2 text-sm font-semibold text-accent-strong">
                        <Sparkles className="h-4 w-4" aria-hidden="true" />A suggestion, not a
                        decision
                    </p>
                    <p className="mt-3 text-sm leading-relaxed text-fg" aria-live="polite">
                        {example.after}
                    </p>
                    <p className="mt-3 text-sm leading-relaxed text-fg-3">{example.reason}</p>
                    <button
                        type="button"
                        onClick={() => setAccepted(!accepted)}
                        className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-4 text-sm font-semibold text-accent-fg transition hover:brightness-110"
                    >
                        {accepted ? (
                            <Check className="h-4 w-4" aria-hidden="true" />
                        ) : (
                            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                        )}
                        {accepted ? 'Accepted · Undo' : 'Try accepting this edit'}
                    </button>
                </div>
                <p className="mt-4 text-xs leading-relaxed text-fg-3">
                    Example content only. Your AI suggestions depend on your résumé and the job.
                </p>
            </div>
        </div>
    )
}
