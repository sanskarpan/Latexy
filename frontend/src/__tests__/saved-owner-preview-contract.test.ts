import { describe, expect, it } from 'vitest'
import { authenticatedUiOwnerSession, isolatedPreviewDatabase, ownedPdfCapture } from '../../scripts/saved-owner-preview-contract.mjs'

describe('saved-owner real preview evidence boundaries', () => {
  const email = 'test_real_renderer_11111111-1111-4111-8111-111111111111@example.invalid'
  const ownerId = '11111111-1111-4111-8111-111111111111'
  const authenticated = () => ({ user: { id: ownerId, email },
    session: { userId: ownerId, token: 'synthetic-authenticated-token' } })

  it('binds the browser-authenticated UI session to its exact synthetic owner', () => {
    expect(authenticatedUiOwnerSession(authenticated(), email)).toEqual({ id: ownerId,
      headers: { Authorization: 'Bearer synthetic-authenticated-token' } })
  })

  it.each([null, {}, { ...authenticated(), session: null },
    ...[undefined, null, '', 'synthetic\r\nheader', 'x'.repeat(4097)].map(token => ({
      ...authenticated(), session: { ...authenticated().session, token },
    })),
    { ...authenticated(), user: { ...authenticated().user, email: 'another@example.invalid' } },
    { ...authenticated(), user: { ...authenticated().user, id: 'not-an-owner-id' } },
    { ...authenticated(), session: { ...authenticated().session, userId: '22222222-2222-4222-8222-222222222222' } },
    { user: authenticated().user, token: 'synthetic-raw-signup-token' },
    { user: authenticated().user, session: { token: 'synthetic-missing-owner-token' } },
    { code: 'INVALID_ORIGIN', message: 'Synthetic error response' },
    { ...authenticated(), error: { code: 'SYNTHETIC_ERROR' } }])(
    'rejects absent, malformed, unrelated or error sessions without exposing their values', value => {
      expect(() => authenticatedUiOwnerSession(value, email))
        .toThrow('Browser-authenticated UI session does not match the exact synthetic owner')
    },
  )

  it('accepts only explicit isolated loopback databases, never production or ambiguous options', () => {
    expect(isolatedPreviewDatabase('postgresql://postgres@127.0.0.1:54321/latexy_ci_test'))
      .toBe('postgresql://postgres@127.0.0.1:54321/latexy_ci_test')
    for (const value of [undefined, '', 'postgresql://postgres@provider.invalid:5432/latexy_ci_test',
      'postgresql://postgres@127.0.0.1:54321/neondb', 'postgresql://postgres@127.0.0.1:54321/latexy_test?options=unsafe',
      'postgresql://postgres@127.0.0.1:54321/latexy_test#fragment', 'postgresql://postgres@127.0.0.1/latexy_test',
      'http://127.0.0.1:5432/latexy_test']) {
      expect(() => isolatedPreviewDatabase(value)).toThrow()
    }
  })

  const pdf = Buffer.from('%PDF-1.7\nSynthetic owner fixture only\n')
  const valid = () => ({ jobId: '11111111-1111-4111-8111-111111111111', artifactId: '', status: 200,
    deadlineAt: 1000, bodyBytes: pdf.length, bodyBase64: pdf.toString('base64') })

  it('keeps exact original-response bytes bound to a bounded successful owned download', () => {
    const captured = ownedPdfCapture(valid(), 500)
    expect(captured.jobId).toBe(valid().jobId)
    expect(captured.body).toEqual(pdf)
  })

  it.each([{ status: 403 }, { error: 'pdf_capture_deadline' }, { deadlineAt: 499 },
    { artifactId: 'a'.repeat(64) }, { jobId: 'another-resource' }, { bodyBytes: pdf.length + 1 },
    { bodyBytes: 21 * 1024 * 1024 }, { bodyBase64: '!!!!' },
    { bodyBytes: 5, bodyBase64: Buffer.from('html!').toString('base64') }])(
    'fails closed on bad capture %j', update => {
      expect(() => ownedPdfCapture({ ...valid(), ...update }, 500)).toThrow(/Owned PDF/)
    },
  )
})
