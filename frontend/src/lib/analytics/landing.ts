/**
 * Landing page keys, device class, and experiment/variant context.
 *
 * This module is deliberately independent of PostHog and of the API client so
 * the consent-gated browser analytics boundary and the first-party landing
 * tracker can share one bounded vocabulary. It never reads or sends a URL
 * query string, a share token, or a document identifier.
 */

export type LandingDeviceClass = 'mobile' | 'tablet' | 'desktop'
export type LandingPageKey =
    | 'home'
    | 'try'
    | 'pricing'
    | 'templates'
    | 'resources'
    | 'platform'
    | 'faq'
    | 'updates'
    | 'developer'

export interface LandingContext {
    pageKey: LandingPageKey | null
    experiment: string | null
    variant: string | null
    deviceClass: LandingDeviceClass
}

const ROUTE_PAGE_KEYS: ReadonlyArray<[RegExp, LandingPageKey]> = [
    [/^\/$/, 'home'],
    [/^\/try\/?$/, 'try'],
    [/^\/pricing\/?$/, 'pricing'],
    [/^\/templates(?:\/.*)?$/, 'templates'],
    [/^\/resources\/?$/, 'resources'],
    [/^\/platform\/?$/, 'platform'],
    [/^\/faq\/?$/, 'faq'],
    [/^\/updates\/?$/, 'updates'],
    [/^\/developer\/?$/, 'developer'],
]

// Public document/share surfaces are excluded before any tracking decision.
// Even though only a page key can leave the browser, these routes can carry an
// opaque token in the pathname.
const EXCLUDED_PREFIXES = [
    '/r/',
    '/u/',
    '/share/',
    '/portfolio/',
    '/workspace/',
    '/workspaces/',
    '/tenant-invite/',
    '/api/',
]

const LABEL_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/i

// Keep direct static member expressions so Next inlines these values at build
// time, while remaining safe in browser-only bundles where `process` is absent.
const LANDING_EXPERIMENT =
    (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_LANDING_EXPERIMENT)
        ?.trim()
        .toLowerCase() || null
const LANDING_VARIANT =
    (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_LANDING_VARIANT)
        ?.trim()
        .toLowerCase() || null

function validLabel(value: string | null): string | null {
    return value && LABEL_PATTERN.test(value) ? value : null
}

export function isTrackablePath(pathname: string | null | undefined): boolean {
    if (!pathname || !pathname.startsWith('/')) return false
    return !EXCLUDED_PREFIXES.some(
        prefix => pathname === prefix.slice(0, -1) || pathname.startsWith(prefix)
    )
}

export function landingPageKey(pathname: string | null | undefined): LandingPageKey | null {
    if (!pathname || !isTrackablePath(pathname)) return null
    // Compare only the pathname; callers must not pass location.search/hash.
    const path = pathname.split('?')[0].split('#')[0]
    for (const [pattern, key] of ROUTE_PAGE_KEYS) {
        if (pattern.test(path)) return key
    }
    return null
}

export function resolveDeviceClass(width?: number): LandingDeviceClass {
    if (Number.isFinite(width)) {
        if (Number(width) < 768) return 'mobile'
        if (Number(width) < 1024) return 'tablet'
        return 'desktop'
    }
    if (typeof window === 'undefined') return 'desktop'
    const px = typeof window.innerWidth === 'number' ? window.innerWidth : 1024
    if (px < 768) return 'mobile'
    if (px < 1024) return 'tablet'
    return 'desktop'
}

export function landingExperimentContext(): { experiment: string | null; variant: string | null } {
    return {
        experiment: validLabel(LANDING_EXPERIMENT),
        // A variant may be recorded without an experiment label; it is not inferred
        // from the experiment and an absent value remains absent.
        variant: validLabel(LANDING_VARIANT),
    }
}

export function resolveLandingContext(
    pathname: string | null | undefined,
    width?: number
): LandingContext {
    const experiment = landingExperimentContext()
    return {
        pageKey: landingPageKey(pathname),
        experiment: experiment.experiment,
        variant: experiment.variant,
        deviceClass: resolveDeviceClass(width),
    }
}

/**
 * Send the first-party page_view used by the admin landing-conversion report.
 *
 * Only the page kind, allowlisted page key, bounded experiment/variant labels,
 * coarse device class, and the anonymous device-local trial fingerprint are
 * sent. The request URL contains no page path or query string.
 */
export function trackFirstPartyPageview(options: {
    page: 'landing' | 'app'
    pageKey?: LandingPageKey | null
    fingerprint?: string | null
    pathname?: string | null
}): void {
    if (typeof window === 'undefined') return
    const context = resolveLandingContext(options.pathname ?? null)
    const pageKey = options.page === 'landing' ? (options.pageKey ?? context.pageKey) : null

    const params = new URLSearchParams({
        page: options.page,
        device_class: context.deviceClass,
    })
    if (pageKey) params.set('page_key', pageKey)
    if (context.experiment) params.set('experiment', context.experiment)
    if (context.variant) params.set('variant', context.variant)
    if (options.fingerprint) params.set('device_fingerprint', options.fingerprint)

    const base =
        typeof process === 'undefined'
            ? ''
            : (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030')
    const url = `${base}/analytics/track/page-view?${params.toString()}`

    try {
        // keepalive lets the request survive navigation. fetch (rather than beacon)
        // carries the Better Auth cookie so an authenticated app view can link the
        // device to the account.
        void fetch(url, { method: 'POST', credentials: 'include', keepalive: true }).catch(
            () => undefined
        )
        return
    } catch {
        // Fall through to a beacon when fetch is unavailable.
    }

    try {
        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
            navigator.sendBeacon(url)
        }
    } catch {
        // Analytics must never break navigation.
    }
}
