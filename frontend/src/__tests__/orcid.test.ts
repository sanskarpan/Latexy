import { describe, expect, test } from 'vitest'
import { isOrcidId, normalizeOrcidId } from '../lib/orcid'

describe('ORCID input', () => {
  test('normalizes canonical profile URLs without accepting lookalike hosts', () => {
    expect(normalizeOrcidId(' https://orcid.org/0000-0001-2345-678X/ ')).toBe('0000-0001-2345-678X')
    expect(normalizeOrcidId('http://www.orcid.org/0000-0001-2345-6789')).toBe('0000-0001-2345-6789')
    expect(normalizeOrcidId('https://orcid.org.evil.test/0000-0001-2345-6789')).toBe(
      'https://orcid.org.evil.test/0000-0001-2345-6789',
    )
  })

  test('validates bare ids including the X checksum character', () => {
    expect(isOrcidId('0000-0001-2345-6789')).toBe(true)
    expect(isOrcidId('0000-0001-2345-678X')).toBe(true)
    expect(isOrcidId('0000-0001-2345')).toBe(false)
  })
})
