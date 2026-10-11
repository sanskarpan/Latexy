import type { Page, TestInfo } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

// This is a pinned Next 15 production React diagnostic, not an application
// fix or an acceptance run. Never guess a hook for another bundle version.
export const LEGACY_SETTINGS_REACT_CHUNK = /\/_next\/static\/chunks\/082d2186-[a-f0-9]+\.js$/
const CLAIM_HOOK = 'function rD(e){'
const HYDRATION_STATE = 'var rP=null,rN=null,rL=!1,rT=null,r_=!1'
const MAX_CHUNK_BYTES = 8 * 1024 * 1024

const CLAIM_CAPTURE = `try{
var d=globalThis.__legacySettingsHydrationDiagnostics;
if(d&&d.hostClaims.length<8){
var hint=function(n){var id=n&&n.id;return id==="main-content"?id:/^[BS]:[0-9]+$/.test(id||"")?"stream-boundary":id?"other":null};
var node=function(n){return n?{type:n.nodeType,tag:n.nodeName,idHint:hint(n)}:null};
var chain=[],f=e;
while(f&&chain.length<24){chain.push(typeof f.type==="string"?f.type:typeof f.type==="function"?(f.type.name||"anonymous-function"):"fiber:"+f.tag);f=f.return}
d.hostClaims.push({atMs:Math.round(performance.now()*100)/100,expectedTag:typeof e.type==="string"?e.type:null,expectedIdHint:e.pendingProps&&e.pendingProps.id==="main-content"?"main-content":e.pendingProps&&e.pendingProps.id?"other":null,candidate:node(rN),next:node(rN&&rN.nextSibling),parent:node(rN&&rN.parentNode),parentFiberTag:rP&&typeof rP.type==="string"?rP.type:null,chain:chain});
}
}catch(diagnosticError){}`

export function instrumentPinnedLegacySettingsReact(source: string): string {
  if (Buffer.byteLength(source) > MAX_CHUNK_BYTES
    || source.split(CLAIM_HOOK).length !== 2
    || source.split(HYDRATION_STATE).length !== 2) {
    throw new Error('The pinned Settings hydration diagnostic hook is absent or ambiguous')
  }
  // The original rD body and throw remain unchanged after the observer.
  return ';globalThis.__legacySettingsHydrationDiagnostics&&(globalThis.__legacySettingsHydrationDiagnostics.hookLoaded=true);\n'
    + source.replace(CLAIM_HOOK, CLAIM_HOOK + CLAIM_CAPTURE)
}

type StructuralState = {
  hookLoaded: boolean
  hostClaims: unknown[]
  snapshots: unknown[]
}

export async function installLegacySettingsHydrationDiagnostics(page: Page) {
  let chunkDeliveries = 0
  const hookFailures: string[] = []
  const navigations: StructuralState[] = []

  await page.addInitScript(() => {
    const target = window as typeof window & { __legacySettingsHydrationDiagnostics?: StructuralState }
    const state: StructuralState = { hookLoaded: false, hostClaims: [], snapshots: [] }
    target.__legacySettingsHydrationDiagnostics = state
    const nodeKind = (node: Node | null) => {
      if (!node) return null
      const comment = node.nodeType === Node.COMMENT_NODE ? node.nodeValue : null
      return { type: node.nodeType, tag: node.nodeName,
        boundary: comment && comment.length <= 8 && /^[/$~!?&]+$/.test(comment) ? comment : null }
    }
    const childKinds = (parent: Node | null) => {
      const kinds = []
      let child = parent?.firstChild ?? null
      while (child && kinds.length < 12) { kinds.push(nodeKind(child)); child = child.nextSibling }
      return kinds
    }
    const snapshot = (event: string, force = false) => {
      // Reserve the last slot for the first mismatch; forced errors are bounded
      // too, even if React or another listener dispatches the error repeatedly.
      if (state.snapshots.length >= (force ? 24 : 23)) return
      const main = document.getElementById('main-content')
      state.snapshots.push({ atMs: Math.round(performance.now() * 100) / 100, event,
        mainCount: document.querySelectorAll('main').length,
        mainFirstNode: nodeKind(main?.firstChild ?? null),
        mainChildKinds: childKinds(main),
        pendingStreamTemplates: document.querySelectorAll('template[id^="B:"]').length,
        hiddenStreamSegments: document.querySelectorAll('[hidden][id^="S:"]').length,
        bootstrapModePresent: document.documentElement.hasAttribute('data-mode'),
        bootstrapContrastPresent: document.documentElement.hasAttribute('data-contrast') })
    }
    document.addEventListener('DOMContentLoaded', () => snapshot('DOMContentLoaded'), { once: true })
    window.addEventListener('error', event => {
      if (/Minified React error #418/.test(event.message)) snapshot('react-host-mismatch', true)
    })
    let lastSignature = ''
    const observer = new MutationObserver(() => {
      const main = document.getElementById('main-content')
      const signature = JSON.stringify([nodeKind(main?.firstChild ?? null),
        childKinds(main),
        document.querySelectorAll('template[id^="B:"]').length,
        document.querySelectorAll('[hidden][id^="S:"]').length])
      if (signature !== lastSignature) { lastSignature = signature; snapshot('stream-structure-changed') }
    })
    observer.observe(document, { childList: true, subtree: true })
    window.setTimeout(() => observer.disconnect(), 15_000)
  })

  await page.route(LEGACY_SETTINGS_REACT_CHUNK, async route => {
    try {
      const requested = new URL(route.request().url())
      if (requested.origin !== new URL(page.url()).origin || requested.protocol !== 'http:'
        || !['localhost', '127.0.0.1', '[::1]'].includes(requested.hostname)) {
        throw new Error('The Settings hydration diagnostic requires its own loopback origin')
      }
      const response = await route.fetch({ timeout: 15_000, maxRetries: 0 })
      if (!response.ok()) throw new Error('React chunk fetch failed')
      const instrumented = instrumentPinnedLegacySettingsReact(await response.text())
      // Update before delivery so browser hookLoaded cannot race the counter.
      chunkDeliveries++
      await route.fulfill({ response, contentType: 'application/javascript', body: instrumented })
    } catch {
      hookFailures.push('pinned-react-hook-unavailable')
      await route.abort('failed')
    }
  })

  async function checkpoint() {
    const state = await page.evaluate(() => (window as typeof window & {
      __legacySettingsHydrationDiagnostics?: StructuralState
    }).__legacySettingsHydrationDiagnostics ?? null)
    if (state) navigations.push(state)
  }

  return {
    async verifyHookLoaded(expectedDeliveries: number) {
      await page.waitForFunction(() => (window as typeof window & {
        __legacySettingsHydrationDiagnostics?: StructuralState
      }).__legacySettingsHydrationDiagnostics?.hookLoaded === true, undefined, { timeout: 15_000 })
      if (hookFailures.length || chunkDeliveries !== expectedDeliveries) {
        throw new Error('The pinned Settings hydration diagnostic delivery could not be verified')
      }
    },
    checkpoint,
    async attach(testInfo: TestInfo) {
      try { await checkpoint() } catch { hookFailures.push('state-checkpoint-unavailable') }
      const filename = testInfo.outputPath('settings-hydration-structural-diagnostic.json')
      await writeFile(filename, JSON.stringify({
        scope: 'failure-only synthetic Settings diagnostic; instrumented delivery is not acceptance evidence',
        chunk_deliveries: chunkDeliveries, hook_failures: hookFailures, navigations,
      }, null, 2) + '\n', { mode: 0o600 })
      await testInfo.attach('settings-hydration-structural-diagnostic', {
        path: filename,
        contentType: 'application/json',
      })
    },
  }
}
