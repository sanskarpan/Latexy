'use client'

import { X, Upload, Sparkles, FileDown } from 'lucide-react'

export default function FirstUseGuide({
    onImport,
    onTailor,
    onPreview,
    onDismiss,
}: {
    onImport: () => void
    onTailor: () => void
    onPreview: () => void
    onDismiss: () => void
}) {
    return (
        <section
            aria-label="Getting started"
            className="relative shrink-0 border-b border-line bg-accent-soft px-4 py-4 sm:px-6"
        >
            <button
                aria-label="Dismiss getting started"
                onClick={onDismiss}
                className="absolute right-2 top-2 rounded-md p-2 text-fg-2 hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
                <X size={16} />
            </button>
            <p className="pr-8 font-display text-lg font-semibold text-fg">
                Your next chapter starts here.
            </p>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-fg-2">
                Try editing the sample below. Your draft saves in this browser. No code needed.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
                <button
                    onClick={onImport}
                    className="inline-flex items-center gap-2 rounded-md border border-line-2 bg-surface px-3 py-2 text-sm font-medium text-fg hover:border-accent"
                >
                    <Upload size={15} /> Bring your résumé
                </button>
                <button
                    onClick={onTailor}
                    className="inline-flex items-center gap-2 rounded-md border border-line-2 bg-surface px-3 py-2 text-sm font-medium text-fg hover:border-accent"
                >
                    <Sparkles size={15} /> Tailor to a job
                </button>
                <button
                    onClick={onPreview}
                    className="inline-flex items-center gap-2 rounded-md border border-line-2 bg-surface px-3 py-2 text-sm font-medium text-fg hover:border-accent"
                >
                    <FileDown size={15} /> Preview your PDF
                </button>
            </div>
        </section>
    )
}
