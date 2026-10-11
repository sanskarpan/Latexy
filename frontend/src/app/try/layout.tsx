import type { Metadata } from 'next'

export const metadata: Metadata = {
    title: 'Try the résumé builder | Latexy',
    description:
        'Edit a sample résumé visually, tailor your writing to a job, and preview a polished PDF. No LaTeX knowledge needed for visual editing.',
    alternates: { canonical: '/try' },
}

export default function TryLayout({ children }: { children: React.ReactNode }) {
    return children
}
