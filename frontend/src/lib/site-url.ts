/** Canonical marketing origin; never advertise localhost to crawlers. */
export function siteUrl(): string {
    const configured = process.env.NEXT_PUBLIC_APP_URL
    if (configured) {
        try {
            const url = new URL(configured)
            if (
                url.protocol === 'https:' &&
                url.hostname !== 'localhost' &&
                url.hostname !== '127.0.0.1'
            )
                return url.origin
        } catch {
            /* Relative app URLs are valid for the client, not canonical URLs. */
        }
    }
    return 'https://latexy.xyz'
}
