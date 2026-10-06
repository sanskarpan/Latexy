#!/usr/bin/env node

import { appendFileSync, readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

export const SCOPE_KEYS = [
  'backend',
  'frontend',
  'tui',
  'extension',
  'render_cv',
  'templates',
  'observability',
  'full_stack',
]

const ALL_SCOPE = Object.fromEntries(SCOPE_KEYS.map((key) => [key, true]))
const EMPTY_SCOPE = Object.fromEntries(SCOPE_KEYS.map((key) => [key, false]))
const SHA = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i
const SAFE_DOC_EXTENSIONS = new Set(['.adoc', '.md', '.rst', '.txt'])
const SAFE_ASSET_EXTENSIONS = new Set([
  '.avif',
  '.gif',
  '.jpeg',
  '.jpg',
  '.pdf',
  '.png',
  '.webp',
])
const EXECUTABLE_OR_CONFIG_EXTENSIONS = new Set([
  '.bash',
  '.cjs',
  '.css',
  '.go',
  '.html',
  '.java',
  '.js',
  '.json',
  '.mjs',
  '.py',
  '.rb',
  '.sh',
  '.sql',
  '.ts',
  '.tsx',
  '.yml',
  '.yaml',
])

function allScope() {
  return { ...ALL_SCOPE }
}

function emptyScope() {
  return { ...EMPTY_SCOPE }
}

function crossComponentScope() {
  return { ...emptyScope(), backend: true, frontend: true, full_stack: true }
}

function backendRuntimeScope(templates = false) {
  return { ...crossComponentScope(), templates }
}

function mergeScope(target, source) {
  for (const key of SCOPE_KEYS) target[key] ||= Boolean(source[key])
  return target
}

function isCanonicalPath(path) {
  if (typeof path !== 'string' || path.length === 0 || path.includes('\\') ||
      path.startsWith('/') || /^[A-Za-z]:/.test(path)) return false
  const parts = path.split('/')
  return parts.every((part) => part.length > 0 && part !== '.' && part !== '..')
}

function isSafeDocPath(path) {
  if (!isCanonicalPath(path)) return false
  const normalized = path
  const basename = normalized.split('/').pop() ?? ''
  const lower = normalized.toLowerCase()
  const extension = basename.includes('.')
    ? `.${basename.split('.').pop().toLowerCase()}`
    : ''
  const isKnownRootDoc = !normalized.includes('/') && /^(readme|changelog|license|notice)(?:[._-].*)?$/i.test(basename)
  const isProseRoot = isKnownRootDoc && (extension === '' || SAFE_DOC_EXTENSIONS.has(extension))
  const isProseTree = /^(docs|legal|features-checklist)\//i.test(lower)
  if (!isProseRoot && !isProseTree) return false
  if (EXECUTABLE_OR_CONFIG_EXTENSIONS.has(extension)) return false
  if (isProseTree) return SAFE_DOC_EXTENSIONS.has(extension) || SAFE_ASSET_EXTENSIONS.has(extension)
  return SAFE_DOC_EXTENSIONS.has(extension) || extension === ''
}

function pathScope(path) {
  const normalized = path
  const lower = normalized.toLowerCase()

  if (isSafeDocPath(normalized)) return emptyScope()

  if (
    lower === '.npmrc' ||
    lower === 'pnpm-workspace.yaml' ||
    lower === 'package.json' ||
    lower === 'pnpm-lock.yaml' ||
    lower.startsWith('patches/')
  ) {
    return { ...emptyScope(), frontend: true, tui: true, extension: true, full_stack: true }
  }

  if (
    lower.startsWith('.github/') ||
    lower.startsWith('scripts/ci/') ||
    lower === 'makefile' ||
    lower.startsWith('docker-compose') ||
    lower.startsWith('k8s/') ||
    lower.startsWith('nginx/') ||
    lower === '.env.production.example' ||
    lower === 'action.yml'
  ) {
    // action.yml is the root metadata for render-cv, but repository/CI config
    // changes remain all-gates because this switch is intentionally conservative.
    if (lower === 'action.yml') return { ...emptyScope(), render_cv: true }
    return allScope()
  }

  if (
    lower.startsWith('backend/app/data/templates/') ||
    lower.startsWith('backend/templates/') ||
    lower.startsWith('backend/app/data/template')
  ) {
    return { ...crossComponentScope(), templates: true }
  }

  if (
    lower === 'backend/app/core/config.py' ||
    lower === 'backend/app/main.py' ||
    lower.startsWith('backend/app/database/') ||
    lower.startsWith('backend/app/scripts/')
  ) {
    return backendRuntimeScope(lower.startsWith('backend/app/scripts/'))
  }

  if (
    lower === 'backend/modal_app.py' ||
    lower.startsWith('backend/alembic/') ||
    lower.startsWith('backend/dockerfile') ||
    lower === 'backend/requirements.txt' ||
    lower === 'backend/requirements.lock' ||
    lower === 'backend/requirements-dev.txt' ||
    lower === 'backend/requirements-dev.lock' ||
    lower.startsWith('backend/scripts/') ||
    lower === 'backend/setup.sh'
  ) {
    return backendRuntimeScope(
      lower.startsWith('backend/app/data/templates/') ||
      lower.startsWith('backend/templates/') ||
      lower.startsWith('backend/scripts/verify-template') ||
      lower.startsWith('backend/scripts/backfill_template'),
    )
  }

  if (
    lower.startsWith('backend/') &&
    (lower.startsWith('backend/app/api/') || lower.includes('/auth') || lower.includes('auth_') ||
      lower.includes('schema') || lower.startsWith('backend/app/models/') ||
      lower.startsWith('backend/app/database/models') || lower.startsWith('backend/database/models'))
  ) {
    return crossComponentScope()
  }

  if (lower.startsWith('backend/')) {
    return { ...emptyScope(), backend: true }
  }

  if (
    lower.startsWith('frontend/') &&
    (lower.startsWith('frontend/src/app/api/') ||
      lower.startsWith('frontend/src/auth') ||
      lower.includes('/auth') ||
      lower.includes('api-client') ||
      lower.endsWith('/api.ts') ||
      lower.includes('/session') ||
      lower.includes('/shared'))
  ) {
    return crossComponentScope()
  }

  if (
    lower.startsWith('frontend/') ||
    lower.startsWith('frontend/figma-plugin/')
  ) {
    if (
      lower === 'frontend/package.json' ||
      lower.startsWith('frontend/dockerfile') ||
      lower === 'frontend/next.config.js' ||
      lower === 'frontend/playwright.config.ts' ||
      lower === 'frontend/playwright.quality.config.ts' ||
      lower === 'frontend/.env.production.example' ||
      lower === 'frontend/vercel.json'
    ) return { ...emptyScope(), frontend: true, full_stack: true }
    return { ...emptyScope(), frontend: true }
  }

  if (lower.startsWith('packages/tui/')) return { ...emptyScope(), tui: true }
  if (lower.startsWith('packages/browser-extension/')) return { ...emptyScope(), extension: true }
  if (lower.startsWith('packages/')) return allScope()

  if (lower.startsWith('actions/render-cv/')) return { ...emptyScope(), render_cv: true }

  if (lower.startsWith('monitoring/') || lower.startsWith('scripts/monitoring/')) {
    return { ...emptyScope(), observability: true }
  }

  // Files outside the explicit allowlist are not presumed harmless. This also
  // catches future top-level tools, generated files, symlink targets, and docs
  // with an executable/configuration extension.
  return allScope()
}

export function classifyPaths(paths) {
  if (!Array.isArray(paths) || paths.length === 0) return allScope()
  const scope = emptyScope()
  for (const path of paths) {
    if (!isCanonicalPath(path) || path.includes('\0')) return allScope()
    mergeScope(scope, pathScope(path))
  }
  return scope
}

export function classifyChanges(changes) {
  if (!Array.isArray(changes) || changes.length === 0) return allScope()
  for (const change of changes) {
    if (!change || !isCanonicalPath(change.path) || change.path.includes('\0') ||
        (change.oldPath !== undefined && (!isCanonicalPath(change.oldPath) || change.oldPath.includes('\0'))) ||
        change.unsafe) return allScope()
    if (change.status === 'T' || change.status === 'U' || change.status === 'X' || change.status === 'B') return allScope()
    if (change.oldMode === '120000' || change.newMode === '120000' ||
        change.oldMode === '160000' || change.newMode === '160000') return allScope()
  }
  return classifyPaths(changes.flatMap((change) => [change.path, change.oldPath].filter(Boolean)))
}

function parseNameStatus(stdout) {
  const tokens = stdout.split('\0')
  if (tokens.at(-1) === '') tokens.pop()
  const changes = []
  for (let index = 0; index < tokens.length;) {
    const status = tokens[index++]
    if (!/^[A-Z][0-9]*$/.test(status)) return null
    const path = tokens[index++]
    if (typeof path !== 'string') return null
    if (status.startsWith('R') || status.startsWith('C')) {
      const newPath = tokens[index++]
      if (typeof newPath !== 'string') return null
      changes.push({ status: status[0], path: newPath, oldPath: path })
    } else {
      changes.push({ status: status[0], path })
    }
  }
  return changes
}

function parseRaw(stdout) {
  const tokens = stdout.split('\0')
  if (tokens.at(-1) === '') tokens.pop()
  const changes = []
  for (let index = 0; index < tokens.length;) {
    const header = tokens[index++]
    const fields = header.trim().split(/\s+/)
    if (fields.length < 5 || !fields[0].startsWith(':')) return null
    const oldMode = fields[0].slice(1)
    const newMode = fields[1]
    const status = fields[4]
    if (!/^\d{6}$/.test(oldMode) || !/^\d{6}$/.test(newMode) || !/^[A-Z][0-9]*$/.test(status)) return null
    const path = tokens[index++]
    if (typeof path !== 'string') return null
    if (status.startsWith('R') || status.startsWith('C')) {
      const newPath = tokens[index++]
      if (typeof newPath !== 'string') return null
      changes.push({ status: status[0], path: newPath, oldPath: path, oldMode, newMode })
    } else {
      changes.push({ status: status[0], path, oldMode, newMode })
    }
  }
  return changes
}

function correlateChanges(names, modes) {
  if (!names || !modes || names.length !== modes.length) return null
  const correlated = []
  for (let index = 0; index < names.length; index += 1) {
    const name = names[index]
    const mode = modes[index]
    if (name.status !== mode.status || name.path !== mode.path ||
        (name.oldPath ?? null) !== (mode.oldPath ?? null)) return null
    correlated.push({ ...name, oldMode: mode.oldMode, newMode: mode.newMode })
  }
  return correlated
}

function gitDiff(repoRoot, base, head, raw, threeDot) {
  const args = raw
    ? ['diff', '--raw', '-z', '--no-renames', `${base}${threeDot ? '...' : '..'}${head}`]
    : ['diff', '--name-status', '-z', '--no-renames', `${base}${threeDot ? '...' : '..'}${head}`]
  const result = spawnSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    windowsHide: true,
  })
  if (result.error || result.status !== 0 || typeof result.stdout !== 'string') return null
  return result.stdout
}

function resolveRange(event, eventName) {
  if (eventName === 'pull_request') {
    const base = event?.pull_request?.base?.sha
    const head = event?.pull_request?.head?.sha
    return SHA.test(base ?? '') && SHA.test(head ?? '') ? { base, head } : null
  }
  if (eventName === 'push') {
    const base = event?.before
    const head = event?.after
    if (typeof base !== 'string' || /^0+$/.test(base) || !SHA.test(base) || !SHA.test(head ?? '')) return null
    return { base, head }
  }
  return null
}

export function classifyEvent({ event, eventName, repoRoot = process.cwd() }) {
  const range = resolveRange(event, eventName)
  if (!range) return allScope()
  const threeDot = eventName === 'pull_request'
  const nameStatus = gitDiff(repoRoot, range.base, range.head, false, threeDot)
  const raw = gitDiff(repoRoot, range.base, range.head, true, threeDot)
  if (nameStatus === null || raw === null) return allScope()
  const names = parseNameStatus(nameStatus)
  const modes = parseRaw(raw)
  const changes = correlateChanges(names, modes)
  if (!changes) return allScope()
  return classifyChanges(changes)
}

export function classifyDiffOutputs(nameStatus, raw = '') {
  const names = parseNameStatus(nameStatus)
  const modes = parseRaw(raw)
  const changes = correlateChanges(names, modes)
  if (!changes) return allScope()
  return classifyChanges(changes)
}

function writeOutputs(scope, outputPath) {
  const lines = SCOPE_KEYS.map((key) => `${key}=${scope[key] ? 'true' : 'false'}\n`).join('')
  appendFileSync(outputPath, lines, { encoding: 'utf8' })
}

export function main(env = process.env) {
  let event
  try {
    event = JSON.parse(readFileSync(env.GITHUB_EVENT_PATH, 'utf8'))
  } catch {
    event = null
  }
  const scope = classifyEvent({
    event,
    eventName: env.GITHUB_EVENT_NAME,
    repoRoot: process.cwd(),
  })
  if (env.GITHUB_OUTPUT) writeOutputs(scope, env.GITHUB_OUTPUT)
  else process.stdout.write(`${JSON.stringify(scope)}\n`)
  return scope
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
