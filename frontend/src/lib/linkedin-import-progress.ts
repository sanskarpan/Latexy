export const LINKEDIN_DATA_EXPORT_URL = 'https://www.linkedin.com/mypreferences/d/download-my-data'

const LINKEDIN_ARCHIVE_REQUESTED_KEY = 'latexy-linkedin-archive-requested-at'

function isValidTimestamp(value: string | null): value is string {
  return value !== null && Number.isFinite(Date.parse(value))
}

export function readLinkedInArchiveRequest(): string | null {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(LINKEDIN_ARCHIVE_REQUESTED_KEY)
    return isValidTimestamp(value) ? value : null
  } catch {
    return null
  }
}

export function rememberLinkedInArchiveRequest(now = new Date()): string {
  const requestedAt = now.toISOString()
  try {
    window.localStorage.setItem(LINKEDIN_ARCHIVE_REQUESTED_KEY, requestedAt)
  } catch {
    // Opening LinkedIn remains useful when browser storage is unavailable.
  }
  return requestedAt
}

export function clearLinkedInArchiveRequest(): void {
  try {
    window.localStorage.removeItem(LINKEDIN_ARCHIVE_REQUESTED_KEY)
  } catch {
    // A successful import must not be converted into a storage failure.
  }
}

export function formatLinkedInArchiveRequestDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}
