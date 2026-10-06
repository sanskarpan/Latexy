import { describe, expect, it } from 'vitest'

import { parseExtensionCapture, validExtensionCaptureId } from '@/lib/extension-capture'

describe('browser-extension capture boundary', () => {
  it('accepts UUID capture identifiers only', () => {
    expect(validExtensionCaptureId('11111111-1111-4111-8111-111111111111')).toBe(true)
    expect(validExtensionCaptureId('../../token')).toBe(false)
    expect(validExtensionCaptureId('------------------------------------')).toBe(false)
    expect(validExtensionCaptureId(null)).toBe(false)
  })

  it('normalizes a complete capture and bounds text', () => {
    const capture = parseExtensionCapture({
      company: '  Acme   Corp ',
      title: ' Platform Engineer ',
      description: 'x'.repeat(21_000),
      location: ' Remote ',
      url: 'https://jobs.example/1#apply',
      source: 'json_ld',
    })
    expect(capture).toMatchObject({
      company: 'Acme Corp',
      title: 'Platform Engineer',
      location: 'Remote',
      source: 'json_ld',
    })
    expect(capture?.description).toHaveLength(20_000)
  })

  it('rejects incomplete and non-web captures', () => {
    expect(parseExtensionCapture({ company: '', title: 'Engineer', url: 'https://example.test' })).toBeNull()
    expect(parseExtensionCapture({ company: 'Acme', title: 'Engineer', url: 'javascript:alert(1)' })).toBeNull()
  })
})
