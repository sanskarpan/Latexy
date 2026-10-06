/** Accept a bare ORCID iD or a canonical profile URL and return the bare id. */
export function normalizeOrcidId(raw: string): string {
  const value = raw.trim()
  const match = value.match(/^https?:\/\/(?:www\.)?orcid\.org\/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\/?$/i)
  return match?.[1] ?? value
}

export function isOrcidId(value: string): boolean {
  return /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(value)
}
