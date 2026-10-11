import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

const flush = () => new Promise((resolve) => setImmediate(resolve))

test('denied popup hides capture/autofill and typing cannot re-enable a new action', async () => {
  const nodes = new Map()
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: id === 'companion-tools', disabled: false, value: '', classList: { toggle() {} }, listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener } })
    return nodes.get(id)
  }
  let inspected = 0
  const source = readFileSync(new URL('../popup.js', import.meta.url), 'utf8').replace(/^import .*\n/gm, '')
  vm.runInNewContext(source, {
    document: { getElementById: node },
    assertCompanionAvailable: async () => { throw new Error('Denied') },
    chrome: { storage: { local: { get: async () => ({}) } }, tabs: { query: async () => { inspected++; return [] } } },
    extractJobPosting() {}, autofillApplication() {},
  })
  await flush()
  assert.equal(node('companion-tools').hidden, true)
  for (const id of ['company', 'title', 'url']) { node(id).value = 'draft'; node(id).listeners.input() }
  assert.equal(node('save').disabled, true)
  await node('save').listeners.click()
  await node('autofill').listeners.click()
  assert.equal(inspected, 0)
})

test('capture bridge rejects a different account without deleting the original draft', async () => {
  let listener
  const replies = []
  let removed = 0
  const origin = 'https://latexy.xyz'
  const window = { location: { origin }, addEventListener: (_, fn) => { listener = fn }, postMessage: (message) => replies.push(message) }
  const source = readFileSync(new URL('../bridge.js', import.meta.url), 'utf8')
  let owner_id = 'owner-b'
  vm.runInNewContext(source, {
    window, AbortSignal,
    fetch: async () => ({ ok: true, json: async () => ({ available: true, capture_available: true, owner_id }) }),
    chrome: { storage: { local: {
      get: async (key) => ({ [key]: { ownerId: 'owner-a', capture: { title: 'Private draft' }, expiresAt: Date.now() + 100000 } }),
      remove: async () => { removed++ },
    } } },
  })
  const event = { source: window, origin, data: { source: 'latexy-web', type: 'LXY_CAPTURE_REQUEST', captureId: 'ffffffff-ffff-4fff-8fff-ffffffffffff' } }
  await listener(event)
  assert.equal(replies[0].capture, null)
  assert.equal(removed, 0)
  owner_id = 'owner-a'
  await listener(event)
  assert.equal(replies[1].capture.title, 'Private draft')
})
