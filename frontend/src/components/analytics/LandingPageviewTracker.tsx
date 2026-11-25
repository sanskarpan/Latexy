'use client'

import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import { getDeviceFingerprint } from '@/lib/api-client'
import { isTrackablePath, landingPageKey, trackFirstPartyPageview } from '@/lib/analytics/landing'

const DEVICE_LINK_KEY = 'latexy_landing_device_link'

function deviceFingerprint(): string | null {
    try {
        return getDeviceFingerprint()
    } catch {
        // Hardened browser contexts can block localStorage; tracking is optional.
        return null
    }
}

/**
 * Emits the first-party landing/pageview events used by the admin growth view.
 *
 * Landing routes always emit one event per pathname visit. Non-landing routes
 * emit at most one authenticated link event per browser session, which lets the
 * server connect the anonymous landing view to the account on the same device.
 * The event never carries a path, query string, or document identifier.
 */
export default function LandingPageviewTracker() {
    const pathname = usePathname()
    const { data: session } = useSession()
    const lastLandingPath = useRef<string | null>(null)

    useEffect(() => {
        if (!pathname || !isTrackablePath(pathname)) return

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

        // Only an authenticated app view can link a device to an account. Do not
        // send anonymous application pageviews; the report only needs the link.
        if (!session?.user?.id) return
        try {
            if (window.sessionStorage.getItem(DEVICE_LINK_KEY) === '1') return
            window.sessionStorage.setItem(DEVICE_LINK_KEY, '1')
        } catch {
            // Storage can be unavailable; the request is harmless if repeated.
        }
        trackFirstPartyPageview({
            page: 'app',
            pathname,
            fingerprint: deviceFingerprint(),
        })
    }, [pathname, session?.user?.id])

    return null
}
