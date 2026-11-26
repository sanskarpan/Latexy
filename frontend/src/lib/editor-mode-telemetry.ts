/**
 * Privacy-safe editor mode, auto-compile and SyncTeX telemetry (issue #2077).
 *
 * Only a bounded event type, the editor mode enum, a canonical route label, an
 * optional boolean/direction, a random retry id and a SHA-256 hash of the
 * document id leave the browser. LaTeX source, document content, prompts,
 * filenames, the raw document/resume id and per-user history are never sent.
 *
 * The consent gate is shared with the browser analytics boundary: nothing is
 * emitted until analytics consent is granted, and a withdrawal stops emission
 * immediately. Toggles and mode/sync repeats are deduplicated on the client;
 * the backend also deduplicates toggle retries idempotently.
 */

import { randomConsentId } from '@/lib/analytics/consent'
import { readAnalyticsConsent } from '@/lib/analytics/posthog'
import { createTraceHeaders } from '@/lib/telemetry'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export const EDITOR_MODES = ['source', 'wysiwyg', 'pdf'] as const
export type EditorMode = (typeof EDITOR_MODES)[number]

export const EDITOR_EVENT_TYPES = [
  'editor_mode_selected',
  'auto_compile_toggled',
  'synctex_used',
] as const
export type EditorEventType = (typeof EDITOR_EVENT_TYPES)[number]

export const SYNCTEX_DIRECTIONS = ['source_to_pdf', 'pdf_to_source'] as const
export type SyncTexDirection = (typeof SYNCTEX_DIRECTIONS)[number]

export const EDITOR_TOGGLE_DEDUPE_WINDOW_MS = 30 * 1000
export const EDITOR_MODE_DEDUPE_WINDOW_MS = 2 * 1000
export const EDITOR_SYNCTEX_DEDUPE_WINDOW_MS = 2 * 1000
export const EDITOR_TELEMETRY_PATH = '/telemetry/editor'
const MAX_DOCUMENT_ID_LENGTH = 128
const SAFE_DOCUMENT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const SHA256_HEX = /^[a-f0-9]{64}$/
const SAFE_EVENT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

const MODE_SET = new Set<string>(EDITOR_MODES)
const EVENT_SET = new Set<string>(EDITOR_EVENT_TYPES)
const DIRECTION_SET = new Set<string>(SYNCTEX_DIRECTIONS)

const STATIC_ROUTES = new Set([
  '/',
  '/try',
  '/templates',
  '/dashboard',
  '/workspace',
  '/workspaces',
  '/login',
  '/signup',
  '/billing',
  '/byok',
  '/settings',
  '/tracker',
])
const ROUTE_PATTERNS: Array<[RegExp, string]> = [
  [/^\/workspace\/[^/]+\/edit\/?$/, '/workspace/:resumeId/edit'],
  [/^\/workspace\/[^/]+\/optimize\/?$/, '/workspace/:resumeId/optimize'],
  [/^\/workspace\/[^/]+\/cover-letter\/?$/, '/workspace/:resumeId/cover-letter'],
  [/^\/workspace\/[^/]+\/career\/?$/, '/workspace/:resumeId/career'],
  [/^\/workspace\/[^/]+\/batch-tailor\/?$/, '/workspace/:resumeId/batch-tailor'],
  [/^\/workspaces\/[^/]+\/recruiter\/?$/, '/workspaces/:workspaceId/recruiter'],
  [/^\/workspaces\/[^/]+\/?$/, '/workspaces/:workspaceId'],
  [/^\/workspace\/[^/]+\/?$/, '/workspace/:resumeId'],
]
const CANONICAL_DYNAMIC_ROUTES = new Set(ROUTE_PATTERNS.map(([, label]) => label))

export interface EditorTelemetryEvent {
  event_type: EditorEventType
  mode: EditorMode
  route: string
  document_hash: string
  event_id: string
  enabled?: boolean
  direction?: SyncTexDirection
}

export interface EditorTelemetryOptions {
  mode: EditorMode | string
  route?: string
  documentId?: string | null
  documentHash?: string | null
}

export function sanitizeEditorRoute(pathname: string | null | undefined): string {
  if (!pathname) return '/other'
  const [withoutQuery] = pathname.trim().split('?', 1)
  const route = withoutQuery.split('#', 1)[0].slice(0, 128)
  if (!route.startsWith('/')) return '/other'
  if (STATIC_ROUTES.has(route) || CANONICAL_DYNAMIC_ROUTES.has(route)) return route
  for (const [pattern, label] of ROUTE_PATTERNS) {
    if (pattern.test(route)) return label
  }
  return '/other'
}

export function normalizeDocumentId(value: string | null | undefined): string | null {
  const trimmed = value?.trim().toLowerCase()
  if (!trimmed || trimmed.length > MAX_DOCUMENT_ID_LENGTH) return null
  return SAFE_DOCUMENT_ID.test(trimmed) ? trimmed : null
}

export function normalizeDocumentHash(value: string | null | undefined): string | null {
  const trimmed = value?.trim().toLowerCase()
  return trimmed && SHA256_HEX.test(trimmed) ? trimmed : null
}

export function browserDocumentRoute(): string {
  if (typeof window === 'undefined') return '/other'
  return sanitizeEditorRoute(window.location.pathname)
}

/**
 * Pure allowlisted builder. It drops unknown modes/types/directions and any
 * extra field, so a caller cannot accidentally attach source or a raw id.
 */
export function buildEditorTelemetryEvent(
  eventType: EditorEventType | string,
  options: EditorTelemetryOptions & {
    enabled?: boolean
    direction?: SyncTexDirection | string
    eventId?: string
  },
): EditorTelemetryEvent | null {
  if (!EVENT_SET.has(eventType)) return null
  if (!MODE_SET.has(options.mode)) return null
  const documentHash = normalizeDocumentHash(options.documentHash)
  if (!documentHash) return null

  const event: EditorTelemetryEvent = {
    event_type: eventType as EditorEventType,
    mode: options.mode as EditorMode,
    route: sanitizeEditorRoute(options.route),
    document_hash: documentHash,
    event_id:
      options.eventId && SAFE_EVENT_ID.test(options.eventId)
        ? options.eventId
        : randomConsentId(),
  }

  if (eventType === 'auto_compile_toggled') {
    if (typeof options.enabled !== 'boolean') return null
    event.enabled = options.enabled
  } else if (eventType === 'synctex_used') {
    if (!options.direction || !DIRECTION_SET.has(options.direction)) return null
    event.direction = options.direction as SyncTexDirection
  }

  return event
}

/** SHA-256 of the normalized document id. The raw id is never returned. */
export async function hashDocumentId(documentId: string): Promise<string | null> {
  const normalized = normalizeDocumentId(documentId)
  if (!normalized) return null
  const cryptoObject =
    typeof globalThis !== 'undefined'
      ? (globalThis.crypto as Crypto | undefined)
      : undefined
  if (!cryptoObject?.subtle || typeof TextEncoder === 'undefined') return null
  try {
    const digest = await cryptoObject.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(normalized),
    )
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('')
  } catch {
    return null
  }
}

export interface EditorTelemetryClientOptions {
  readConsent: () => 'granted' | 'denied' | null
  hashDocument: (documentId: string) => Promise<string | null>
  now: () => number
  send: (events: EditorTelemetryEvent[]) => void
  route?: () => string
}

export interface EditorTelemetryClient {
  selectMode: (mode: EditorMode | string, options?: Partial<EditorTelemetryOptions>) => boolean
  toggleAutoCompile: (
    enabled: boolean,
    options: Partial<EditorTelemetryOptions>,
  ) => boolean
  synctex: (
    direction: SyncTexDirection | string,
    options: Partial<EditorTelemetryOptions>,
  ) => boolean
  reset: () => void
}

function sendEditorTelemetry(events: EditorTelemetryEvent[]): void {
  const body = JSON.stringify({ events })
  try {
    void fetch(`${API_BASE}${EDITOR_TELEMETRY_PATH}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...createTraceHeaders(),
      },
      body,
      credentials: 'include',
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Telemetry must never break the editor.
  }
}

export function createEditorTelemetryClient(
  options: EditorTelemetryClientOptions,
): EditorTelemetryClient {
  const hashCache = new Map<string, string>()
  const lastToggle = new Map<string, { enabled: boolean; at: number }>()
  const lastMode = new Map<string, { mode: string; at: number }>()
  const lastSync = new Map<string, { direction: string; at: number }>()

  function resolvedRoute(explicit?: string): string {
    if (explicit) return sanitizeEditorRoute(explicit)
    return options.route ? options.route() : browserDocumentRoute()
  }

  function emit(
    eventType: EditorEventType,
    mode: string,
    documentId: string | null | undefined,
    extra: { enabled?: boolean; direction?: string; route?: string },
  ): boolean {
    if (options.readConsent() !== 'granted') return false
    const normalizedId = normalizeDocumentId(documentId)
    if (!normalizedId) return false

    const route = resolvedRoute(extra.route)
    void (async () => {
      let hash = hashCache.get(normalizedId)
      if (!hash) {
        const computed = normalizeDocumentHash(
          await options.hashDocument(normalizedId),
        )
        if (!computed) return
        hash = computed
        hashCache.set(normalizedId, computed)
      }
      // Consent may have been withdrawn while the digest was computed.
      if (options.readConsent() !== 'granted') return
      const event = buildEditorTelemetryEvent(eventType, {
        mode,
        route,
        documentHash: hash,
        enabled: extra.enabled,
        direction: extra.direction,
      })
      if (event) options.send([event])
    })()
    return true
  }

  function selectMode(
    mode: EditorMode | string,
    extra: Partial<EditorTelemetryOptions> = {},
  ): boolean {
    if (!MODE_SET.has(mode)) return false
    const documentId = normalizeDocumentId(extra.documentId)
    if (!documentId) return false
    const now = options.now()
    const key = `${documentId}:${mode}`
    const previous = lastMode.get(key)
    if (
      previous !== undefined &&
      now - previous.at < EDITOR_MODE_DEDUPE_WINDOW_MS
    ) {
      return false
    }
    lastMode.set(key, { mode, at: now })
    return emit('editor_mode_selected', mode, documentId, { route: extra.route })
  }

  function toggleAutoCompile(
    enabled: boolean,
    extra: Partial<EditorTelemetryOptions>,
  ): boolean {
    if (!MODE_SET.has(extra.mode ?? '')) return false
    if (typeof enabled !== 'boolean') return false
    const documentId = normalizeDocumentId(extra.documentId)
    if (!documentId) return false
    const mode = String(extra.mode)
    const now = options.now()
    const key = `${documentId}:${mode}`
    const previous = lastToggle.get(key)
    if (
      previous !== undefined &&
      previous.enabled === enabled &&
      now - previous.at < EDITOR_TOGGLE_DEDUPE_WINDOW_MS
    ) {
      return false
    }
    lastToggle.set(key, { enabled, at: now })
    return emit('auto_compile_toggled', mode, documentId, {
      enabled,
      route: extra.route,
    })
  }

  function synctex(
    direction: SyncTexDirection | string,
    extra: Partial<EditorTelemetryOptions>,
  ): boolean {
    if (!DIRECTION_SET.has(direction)) return false
    if (!MODE_SET.has(extra.mode ?? '')) return false
    const documentId = normalizeDocumentId(extra.documentId)
    if (!documentId) return false
    const mode = String(extra.mode)
    const now = options.now()
    const key = `${documentId}:${mode}:${direction}`
    const previous = lastSync.get(key)
    if (
      previous !== undefined &&
      now - previous.at < EDITOR_SYNCTEX_DEDUPE_WINDOW_MS
    ) {
      return false
    }
    lastSync.set(key, { direction, at: now })
    return emit('synctex_used', mode, documentId, { direction, route: extra.route })
  }

  return {
    selectMode,
    toggleAutoCompile,
    synctex,
    reset: () => {
      hashCache.clear()
      lastToggle.clear()
      lastMode.clear()
      lastSync.clear()
    },
  }
}

export const editorModeTelemetry = createEditorTelemetryClient({
  readConsent: readAnalyticsConsent,
  hashDocument: hashDocumentId,
  now: () => Date.now(),
  send: sendEditorTelemetry,
})
