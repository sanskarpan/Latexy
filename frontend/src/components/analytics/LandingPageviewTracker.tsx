'use client'

import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import { getDeviceFingerprint } from '@/lib/api-client'
import {
    isPathAnalysisPath,
    landingPageKey,
    trackFirstPartyPageview,
} from '@/lib/analytics/landing'

function deviceFingerprint(): string | null {
    try {
        return getDeviceFingerprint()
    } catch {
        // Hardened browser contexts can block localStorage; tracking is optional.
        return null
    }
}

/**
 * Emits the first-party pageview events used by the admin growth and path views.
 *
 * Landing routes always emit one event per pathname visit. Authenticated app
 * routes emit one event per navigation so the admin path report can reconstruct
 * the last few sanitized pages before an upgrade or churn. The event carries
 * only a canonical route label: public share pages are excluded at the source,
 * and query strings, tokens, workspace ids and document identifiers are removed
 * before transmission and again on the server.
 */
export default function LandingPageviewTracker() {
    const pathname = usePathname()
    const { data: session } = useSession()
    const lastLandingPath = useRef<string | null>(null)

    useEffect(() => {
        if (!pathname) return

        const pageKey = landingPageKey(pathname)
        if (pageKey) {
            if (lastLandingPath.current === pathname) return
            lastLandingPath.current = pathname
            trackFirstPartyPageview({
                page: 'landing',
                pageKey,
                pathname,
                fingerprint: deviceFingerprint(),
            })
            return
        }

        // Anonymous application views are not needed for path analysis; the
        // outcome is only meaningful after the account exists.
        if (!session?.user?.id) return
        if (!isPathAnalysisPath(pathname)) return
        trackFirstPartyPageview({
            page: 'app',
            pathname,
            fingerprint: deviceFingerprint(),
        })
    }, [pathname, session?.user?.id])

    return null
}
