// WebKit r2370 refuses new non-keepalive loads during provisional navigation.
// It reports these cancellations as JavaScript-source access-control errors:
// https://github.com/microsoft/playwright/issues/43120#issuecomment-6005779122
// This test-only classifier requires positive old-document provenance; a text
// match, successful sign-out, or missing browser request alone is insufficient.
export interface PrefetchAttempt {
  url: string
  at: number
  method: string
  signalAborted: boolean
  keepalive: boolean
  metaPolicyUnrestricted: boolean
}

export interface NavigationDocument {
  id: string
  url: string
  startedAt: number
  hiddenAt: number | null
  signOutIntentAt: number | null
  fetches: PrefetchAttempt[]
  windowErrors: Array<{ kind: string; at: number }>
}

export interface NavigationLedger {
  version: 1
  runId: string
  overflow: boolean
  documents: NavigationDocument[]
}

export interface ObservedPageError {
  name: string
  message: string
  stack: string
  url: string
  observedAt: number
}

export interface SignOutNavigation {
  documentId: string
  intentAt: number
  connectionPolicyUnrestricted: boolean
  postSucceededAt: number | null
  replacementStartedAt: number | null
  replacementCommittedAt: number | null
}

// This is intentionally not a permissive CSP parser. Admit only no policy or
// the shipped, connection-unrestricted baseline. Unknown directives, source
// lists, comma/quote ambiguity and extra enforcement all fail closed.
export function connectionPolicyUnrestricted(raw: string): boolean {
  if (raw.length > 2_048 || /[^\x09\x20-\x7e]/.test(raw)) return false
  if (!raw.trim()) return true
  const baseline = new Set(["frame-ancestors 'none'", "base-uri 'self'", "object-src 'none'"])
  return raw.split(',').every(policy => {
    const directives = policy.split(';').map(value => value.trim()).filter(Boolean)
    return directives.length > 0 && directives.every(value => baseline.has(value.replace(/[ \t]+/g, ' ').toLowerCase()))
  })
}

// Deliberately limited to the two public-route prefetch signatures reproduced
// on the pinned runtime. No API, cross-origin or arbitrary-query allowance.
export function candidatePrefetchUrl(raw: string, appOrigin: string): string | null {
  try {
    const url = new URL(raw, appOrigin)
    if (url.username || url.password || url.origin !== appOrigin || !['/terms', '/byok'].includes(url.pathname) || url.hash) return null
    if ([...url.searchParams.keys()].length !== 1 || !url.searchParams.has('_rsc')) return null
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(url.searchParams.get('_rsc') ?? '')) return null
    return url.href
  } catch {
    return null
  }
}

export function classifySignOutPageErrors(input: {
  browserName: string
  appOrigin: string
  runId: string
  ledger: NavigationLedger | null
  navigation: SignOutNavigation | null
  errors: ObservedPageError[]
  browserRequestUrls: string[]
}) {
  const classified: Array<{ error: ObservedPageError; reason: string }> = []
  const unclassified: ObservedPageError[] = []
  const { ledger, navigation } = input
  const oldIndex = ledger?.documents.findIndex(doc => doc.id === navigation?.documentId) ?? -1
  const old = oldIndex < 0 ? undefined : ledger?.documents[oldIndex]
  const replacement = oldIndex < 0 ? undefined : ledger?.documents[oldIndex + 1]
  const target = `${input.appOrigin}/`
  const provenance = input.browserName === 'webkit'
    && ledger?.version === 1 && ledger.runId === input.runId && !ledger.overflow
    && ledger.documents.length <= 8
    && input.browserRequestUrls.length < 128
    && ledger.documents.every(doc => doc.fetches.length <= 128 && doc.windowErrors.length === 0)
    && navigation && old && replacement
    && navigation.connectionPolicyUnrestricted
    && old.url === `${input.appOrigin}/platform`
    && old.signOutIntentAt === navigation.intentAt
    && old.startedAt <= navigation.intentAt
    && navigation.postSucceededAt !== null && navigation.postSucceededAt >= navigation.intentAt
    && navigation.replacementStartedAt !== null && navigation.replacementStartedAt >= navigation.postSucceededAt
    && navigation.replacementCommittedAt !== null && navigation.replacementCommittedAt >= navigation.replacementStartedAt
    && old.hiddenAt !== null && old.hiddenAt >= navigation.replacementStartedAt
    && replacement.url === target && replacement.startedAt >= old.hiddenAt

  for (const error of input.errors) {
    const firstLine = error.stack.split('\n')[0]
    const match = /^Fetch API cannot load (https?:\/\/\S+) due to access control checks\.$/.exec(firstLine)
    const url = match ? candidatePrefetchUrl(match[1], input.appOrigin) : null
    const scheme = new URL(input.appOrigin).protocol.slice(0, -1)
    // Playwright's WebKit bridge splits the engine's text into name/message.
    const engineShape = error.name === `Fetch API cannot load ${scheme}`
      && error.message === firstLine.slice(`Fetch API cannot load ${scheme}:/`.length)
    const attempted = old?.fetches.some(attempt => attempt.url === url
      && attempt.method === 'GET' && !attempt.signalAborted && !attempt.keepalive && attempt.metaPolicyUnrestricted
      && attempt.at >= navigation!.replacementStartedAt!
      && attempt.at <= error.observedAt)
    if (provenance && url && engineShape && attempted
      && error.url === old.url
      && error.observedAt >= navigation.replacementStartedAt!
      && error.observedAt <= old.hiddenAt!
      && error.observedAt <= navigation.replacementCommittedAt!
      && !input.browserRequestUrls.includes(url)) {
      classified.push({ error, reason: 'proven WebKit same-origin prefetch refusal during sign-out document replacement' })
    } else {
      unclassified.push(error)
    }
  }
  return { classified, unclassified }
}

// Serialized by page.addInitScript; keep this function self-contained. A small
// synchronous, origin-local ledger survives document replacement. pagehide must
// persist successfully before any error can be classified, so missing/failed
// recording fails closed. It stores no bodies, cookies or authentication data.
export function installSignOutProvenance(options: { storageKey: string; runId: string }) {
  const previous = sessionStorage.getItem(options.storageKey)
  const ledger: NavigationLedger = previous ? JSON.parse(previous) : {
    version: 1, runId: options.runId, overflow: false, documents: [],
  }
  const doc: NavigationDocument = {
    id: crypto.randomUUID(), url: `${location.origin}${location.pathname}`,
    startedAt: Date.now(), hiddenAt: null, signOutIntentAt: null, fetches: [], windowErrors: [],
  }
  if (ledger.documents.length >= 8) ledger.overflow = true
  else ledger.documents.push(doc)
  const save = () => sessionStorage.setItem(options.storageKey, JSON.stringify(ledger))
  save()
  Object.defineProperty(window, '__latexySignOutProvenance', { value: {
    arm() {
      if (doc.signOutIntentAt !== null) throw new Error('Sign-out provenance was already armed')
      doc.signOutIntentAt = Date.now()
      save()
      return { documentId: doc.id, intentAt: doc.signOutIntentAt }
    },
  } })
  addEventListener('pagehide', () => { doc.hiddenAt = Date.now(); save() })
  for (const kind of ['error', 'unhandledrejection', 'securitypolicyviolation']) addEventListener(kind, () => {
    if (doc.windowErrors.length >= 16) ledger.overflow = true
    else doc.windowErrors.push({ kind, at: Date.now() })
    save()
  })
  const nativeFetch = window.fetch
  window.fetch = function (input, init) {
    // Recorder errors must not prevent the original fetch. Mark the ledger
    // unusable, retaining the original request and exception semantics.
    try {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
      if (!url.username && !url.password && url.origin === location.origin && ['/terms', '/byok'].includes(url.pathname)
        && !url.hash && [...url.searchParams.keys()].length === 1
        && /^[A-Za-z0-9_-]{1,80}$/.test(url.searchParams.get('_rsc') ?? '')
        && headers.get('RSC') === '1' && headers.get('Next-Router-Prefetch') === '1') {
        if (doc.fetches.length >= 128) ledger.overflow = true
        else doc.fetches.push({ url: url.href, at: Date.now(),
          method: (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase(),
          signalAborted: Boolean((init?.signal ?? (input instanceof Request ? input.signal : null))?.aborted),
          keepalive: Boolean(init?.keepalive ?? (input instanceof Request ? input.keepalive : false)),
          metaPolicyUnrestricted: [...document.querySelectorAll<HTMLMetaElement>('meta[http-equiv]')]
            .every(meta => meta.httpEquiv.toLowerCase() !== 'content-security-policy'),
        })
        save()
      }
    } catch {
      ledger.overflow = true
      // If persistence itself is unavailable, the absent pagehide record also
      // prevents classification. Do not manufacture application exceptions.
      try { save() } catch { /* The final ledger is untrusted/missing. */ }
    }
    return Reflect.apply(nativeFetch, this, [input, init])
  }
}
