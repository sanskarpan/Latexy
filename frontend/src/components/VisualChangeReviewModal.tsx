'use client'

import { useEffect, useRef, useState } from 'react'
import VisualResumeEditor from '@/components/VisualResumeEditor'

export default function VisualChangeReviewModal({
    original,
    proposed,
    onApply,
    onClose,
}: {
    original: string
    proposed: string
    onApply?: (reviewedLatex: string) => void
    onClose: () => void
}) {
    const dialogRef = useRef<HTMLDialogElement>(null)
    const [reviewed, setReviewed] = useState(proposed)
    useEffect(() => { setReviewed(proposed) }, [proposed])
    useEffect(() => {
        const dialog = dialogRef.current
        dialog?.showModal()
        return () => dialog?.close()
    }, [])
    return (
        <dialog
            ref={dialogRef}
            onCancel={onClose}
            aria-labelledby="visual-review-title"
            className="m-auto w-[min(96vw,1100px)] max-h-[90dvh] rounded-xl border border-line bg-bg p-0 text-fg shadow-2xl backdrop:bg-black/60"
        >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
                <div>
                    <h2 id="visual-review-title" className="font-display text-xl font-semibold">
                        Review your résumé changes
                    </h2>
                    <p className="mt-1 text-sm text-fg-2">
                        Compare the content before deciding. Your current draft stays unchanged
                        until you apply. {onApply ? 'You can edit the proposed wording before accepting it.' : ''}
                    </p>
                </div>
                <button
                    onClick={onClose}
                    className="rounded-md border border-line px-3 py-2 text-sm"
                >
                    Close review
                </button>
            </div>
            <div className="grid gap-4 p-4 md:grid-cols-2">
                <section className="min-w-0">
                    <h3 className="mb-2 font-semibold">Original</h3>
                    <VisualResumeEditor value={original} onChange={() => {}} readOnly />
                </section>
                <section className="min-w-0">
                    <h3 className="mb-2 font-semibold">Proposed</h3>
                    <VisualResumeEditor value={reviewed} onChange={setReviewed} readOnly={!onApply} />
                </section>
            </div>
            {onApply && (
                <div className="sticky bottom-0 flex justify-end border-t border-line bg-surface p-4">
                    <button
                        onClick={() => onApply(reviewed)}
                        className="rounded-md bg-accent px-4 py-2 font-semibold text-accent-fg"
                    >
                        Apply changes
                    </button>
                </div>
            )}
        </dialog>
    )
}
