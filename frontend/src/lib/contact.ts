/**
 * Published contact addresses for Latexy.
 *
 * This module is the single source of truth for public-facing email addresses.
 * The contact domain is `latexy.xyz`; the older `.com` domain is a parked
 * lander without mail routing, so addresses on it are undeliverable. Import
 * these constants instead of hardcoding an address at a call site.
 */
export const CONTACT_DOMAIN = 'latexy.xyz'

export const SUPPORT_EMAIL = `support@${CONTACT_DOMAIN}`
export const PRIVACY_EMAIL = `privacy@${CONTACT_DOMAIN}`
export const LEGAL_EMAIL = `legal@${CONTACT_DOMAIN}`
export const BILLING_EMAIL = `billing@${CONTACT_DOMAIN}`

/** Build a `mailto:` URL, optionally with a pre-filled subject line. */
export function mailtoHref(email: string, subject?: string): string {
    return subject ? `mailto:${email}?subject=${encodeURIComponent(subject)}` : `mailto:${email}`
}
