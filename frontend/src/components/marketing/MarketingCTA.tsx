'use client'

import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { useSession } from '@/lib/auth-client'

export function MarketingCTA({
    label = 'Build my résumé',
    href = '/try?mode=visual',
}: {
    label?: string
    href?: string
}) {
    const { can, loading, error, refresh } = useEntitlements()
    const { data: session } = useSession()
    const studioAllowed = Boolean(session?.user?.id) || can('a09')
    const editingAllowed = studioAllowed && can('c01')
    const visualAllowed = editingAllowed && can('b10')
    const destination = visualAllowed ? href : '/try?mode=source'

    if (loading) {
        return <span data-marketing-status className="inline-flex min-h-11 items-center text-sm text-fg-2" role="status">Checking studio availability…</span>
    }
    if (error) {
        return (
            <span data-marketing-status className="inline-flex min-h-11 flex-wrap items-center gap-x-3 text-sm text-fg-2" role="alert">
                Studio availability could not be verified.
                <button type="button" className="min-h-11 font-semibold text-accent-strong underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" onClick={refresh}>Retry</button>
            </span>
        )
    }
    if (!editingAllowed) {
        return <span data-marketing-status className="inline-flex min-h-11 items-center text-sm text-fg-2" role="status">Studio editing is currently unavailable.</span>
    }

    return (
        <Link
            href={destination}
            data-marketing-action="primary"
            className="inline-flex min-h-12 items-center justify-center gap-3 rounded-[var(--radius-md)] bg-accent px-6 py-3 font-semibold text-accent-fg shadow-[var(--shadow-1)] transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
            {visualAllowed ? label : 'Open the source editor'}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
    )
}
