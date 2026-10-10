import assert from 'node:assert/strict'
import test from 'node:test'
import { assertCompanionAvailable } from '../capabilities.js'

test('checks the current authenticated capability without cached grants', async () => {
  let options
  await assertCompanionAvailable('https://latexy.xyz', async (url, init) => {
    assert.equal(url, 'https://latexy.xyz/api/extension/entitlements')
    options = init
    return { ok: true, json: async () => ({ available: true, owner_id: 'owner-a' }) }
  })
  assert.equal(options.credentials, 'include')
  assert.equal(options.cache, 'no-store')
})
test('denies unavailable, unknown, malformed and failed capabilities', async () => {
  for (const available of [false, undefined, 'true', 1]) {
    await assert.rejects(assertCompanionAvailable('https://latexy.xyz', async () => ({ ok: true, json: async () => ({ available }) })))
  }
  await assert.rejects(assertCompanionAvailable('https://latexy.xyz', async () => ({ ok: false })))
  await assert.rejects(assertCompanionAvailable('https://latexy.xyz', async () => { throw new Error('offline') }))
  await assert.rejects(assertCompanionAvailable('https://untrusted.example', async () => { assert.fail('must not contact untrusted origin') }))
})

test('requires a confirmed owner so handoffs cannot cross accounts', async () => {
  for (const owner_id of [undefined, null, '', 1]) {
    await assert.rejects(assertCompanionAvailable('https://latexy.xyz', async () => ({ ok: true, json: async () => ({ available: true, owner_id }) })))
  }
  assert.deepEqual(await assertCompanionAvailable('https://latexy.xyz', async () => ({ ok: true, json: async () => ({ available: true, capture_available: true, owner_id: 'owner-a' }) })), { ownerId: 'owner-a', captureAvailable: true })
})

test('an application-board denial does not implicitly grant capture through extension access', async () => {
  const grant = await assertCompanionAvailable('https://latexy.xyz', async () => ({ ok: true, json: async () => ({ available: true, owner_id: 'owner-a', capture_available: false }) }))
  assert.equal(grant.captureAvailable, false)
})
