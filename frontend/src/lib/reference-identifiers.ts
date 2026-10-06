/** Classify a bare DOI/arXiv identifier or an exact provider URL. */
export function detectReferenceIdentifierType(line: string): 'doi' | 'arxiv' | null {
  const trimmed = line.trim()
  if (!trimmed) return null
  if (/^10\.\d{4,}\//.test(trimmed)) return 'doi'
  if (/^\d{4}\.\d{4,}(v\d+)?$/.test(trimmed)) return 'arxiv'

  try {
    const url = new URL(trimmed)
    const host = url.hostname.toLowerCase()
    if ((host === 'doi.org' || host === 'dx.doi.org') && /^\/10\.\d{4,}\//.test(url.pathname)) {
      return 'doi'
    }
    if (host === 'arxiv.org' && /^\/(?:abs|pdf)\//.test(url.pathname)) return 'arxiv'
  } catch {
    // A non-URL may still be one of the supported bare identifiers above.
  }
  return null
}
