export function extractJobPosting(doc = document, currentUrl = location.href) {
  const MAX_DESCRIPTION = 20_000
  const MAX_SHORT = 200

  const text = (value, max = MAX_SHORT, preserveLines = false) => {
    if (typeof value !== 'string') return ''
    const normalized = value
      .replace(/<script\b[^>]*>[\s\S]*?<\/script(?=[\s/>])[^>]*>/gi, ' ')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style(?=[\s/>])[^>]*>/gi, ' ')
      .replace(/<br\s*\/?>|<\/(?:p|li|div|h[1-6])>/gi, '\n')
      .replace(/<[^>]+>/g, ' ')
      // Decode once: an encoded ampersand must not expose another entity
      // to a later replacement pass. This output is plain text, not HTML.
      .replace(/&(?:nbsp|#160|amp|quot|#34|#39|apos);/gi, (entity) => ({
        '&nbsp;': ' ', '&#160;': ' ', '&amp;': '&', '&quot;': '"',
        '&#34;': '"', '&#39;': "'", '&apos;': "'",
      })[entity.toLowerCase()])
    return (preserveLines
      ? normalized
          .split(/\r?\n/)
          .map((line) => line.replace(/[\t ]+/g, ' ').trim())
          .filter(Boolean)
          .join('\n')
      : normalized.replace(/\s+/g, ' ').trim()
    ).slice(0, max)
  }

  const firstText = (selectors, max = MAX_SHORT, preserveLines = false) => {
    for (const selector of selectors) {
      const element = doc.querySelector(selector)
      const value = element?.getAttribute?.('content') || element?.textContent || ''
      const normalized = text(value, max, preserveLines)
      if (normalized) return normalized
    }
    return ''
  }

  const findPosting = (value) => {
    if (Array.isArray(value)) {
      for (const item of value) {
        const found = findPosting(item)
        if (found) return found
      }
      return null
    }
    if (!value || typeof value !== 'object') return null
    const types = Array.isArray(value['@type']) ? value['@type'] : [value['@type']]
    if (types.some((type) => String(type).toLowerCase() === 'jobposting')) return value
    return findPosting(value['@graph'])
  }

  let structured = null
  for (const node of doc.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      structured = findPosting(JSON.parse(node.textContent || 'null'))
    } catch {
      // Invalid third-party JSON-LD must not break the explicit user action.
    }
    if (structured) break
  }

  const structuredCompany =
    typeof structured?.hiringOrganization === 'object'
      ? structured.hiringOrganization?.name
      : structured?.hiringOrganization
  const structuredLocation = Array.isArray(structured?.jobLocation)
    ? structured.jobLocation[0]
    : structured?.jobLocation
  const address = structuredLocation?.address || structuredLocation
  const locationText =
    typeof address === 'string'
      ? address
      : [address?.addressLocality, address?.addressRegion, address?.addressCountry]
          .filter(Boolean)
          .join(', ')

  const title =
    text(structured?.title) ||
    firstText(['h1', '[data-testid="job-title"]', '[itemprop="title"]', 'meta[property="og:title"]'])
  const company =
    text(structuredCompany) ||
    firstText([
      '[data-company-name]',
      '[itemprop="hiringOrganization"] [itemprop="name"]',
      '.jobs-unified-top-card__company-name',
      '.company-name',
      'meta[property="og:site_name"]',
    ])
  const description =
    text(structured?.description, MAX_DESCRIPTION, true) ||
    firstText([
      '[data-testid="job-description"]',
      '[itemprop="description"]',
      '#job-details',
      '.jobs-description-content__text',
      '.job-description',
      '.jobDescriptionText',
      'main',
    ], MAX_DESCRIPTION, true)
  const locationValue =
    text(locationText) ||
    firstText(['[data-testid="job-location"]', '[itemprop="jobLocation"]', '.job-location'])

  let url = ''
  try {
    const parsed = new URL(currentUrl)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      parsed.hash = ''
      const disposableParams = /^(?:utm_.+|ref|refid|trk|trkinfo|trackingid|fbclid|gclid|msclkid|token|auth|session|signature)$/i
      for (const key of [...parsed.searchParams.keys()]) {
        if (disposableParams.test(key)) parsed.searchParams.delete(key)
      }
      url = parsed.toString().slice(0, 500)
    }
  } catch {
    // A browser tab should always have a URL; fail closed for non-web schemes.
  }

  return {
    title,
    company,
    description,
    location: locationValue,
    url,
    source: structured ? 'json_ld' : 'visible_page',
  }
}
