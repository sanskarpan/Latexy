#!/usr/bin/env node
/**
 * Production launch smoke test for the deployed Latexy stack.
 *
 * Default mode is read-only: GET requests only. Any job-creating or write
 * operation is behind an explicit opt-in flag:
 *   --guest-compile  one anonymous trial compile on /try
 *   --account        authenticated workspace compile/download/save/reload
 *   --deep-ats       authenticated synthetic deep ATS analysis (needs --account)
 *   --share          create/verify a public share link (needs --account)
 *
 * Evidence deliberately excludes cookies, bearer tokens, email addresses,
 * resume/job/share identifiers, page bodies, and LaTeX source. Only status,
 * timing, and derived summaries are written.
 */

import { existsSync } from 'node:fs'
import { mkdir, open, stat, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parseArgs } from 'node:util'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, '..', '..')

const DEFAULT_BASE_URL = 'https://latexy.xyz'
const DEFAULT_API_URL = 'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
const HTTP_TIMEOUT_MS = 30_000
const BROWSER_CHECK_TIMEOUT_MS = 180_000
const DEEP_ATS_BUDGET_MS = 180_000
const DEEP_ATS_POLL_MS = 3_000

const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed', 'cancelled', 'timeout', 'error'])
const SHA_PATTERN = /^[0-9a-f]{40}$/
const SAFE_TOKEN_PATTERN = /^[A-Za-z0-9_.:-]{1,64}$/

const SYNTHETIC_ATS_LATEX = String.raw`\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\begin{document}
\begin{center}{\Large Alex Taylor}\end{center}
\section*{Summary}
Software engineer with five years of experience building reliable web services and developer tooling.
\section*{Experience}
\textbf{Acme Corp} \hfill 2021--2026 \\
Engineer. Built APIs, improved reliability, and reviewed production changes.
\section*{Skills}
TypeScript, Python, PostgreSQL, Docker, Linux
\end{document}`

const USAGE = `Usage: node scripts/qa/production-launch-smoke.mjs [options]

Read-only by default. Optional checks create jobs or write data and require
explicit flags.

Options:
  --base-url <url>       Frontend origin (default: ${DEFAULT_BASE_URL})
  --api-url <url>        Backend origin (default: ${DEFAULT_API_URL})
  --out <path>           Evidence JSON path
                         (default: qa-evidence/production-smoke-<timestamp>.json)
  --guest-compile        Compile the built-in /try sample once. Consumes one
                         anonymous trial. Requires LATEXY_PRODUCTION_SMOKE=1.
  --account              Use LATEXY_QA_STORAGE_STATE to open a resume, compile,
                         download the PDF, save, and hard-reload.
                         Requires LATEXY_PRODUCTION_SMOKE=1.
  --deep-ats             Submit a synthetic deep ATS analysis and poll for up to
                         3 minutes. Requires --account.
  --share                Create and verify a public share link in a fresh
                         incognito context. Requires --account.
  --help                 Show this help.

Environment:
  LATEXY_PRODUCTION_SMOKE=1   Required opt-in gate for browser/write checks.
  LATEXY_QA_STORAGE_STATE     Playwright storage state for the dedicated QA
                              account. Keep it outside the checkout.

Exit codes:
  0  all required checks passed and no enabled optional check failed
  1  a required check or an enabled optional check failed
  2  invalid arguments or missing opt-in prerequisites
`

class SmokeFailure extends Error {
  constructor(code, details = {}) {
    super(code)
    this.name = 'SmokeFailure'
    this.code = code
    this.details = details
  }
}

function failUsage(message) {
  console.error(`production-launch-smoke: ${message}`)
  console.error('Run with --help for usage.')
  process.exit(2)
}

function normalizeOrigin(value, label) {
  let url
  try {
    url = new URL(value)
  } catch {
    failUsage(`${label} must be an absolute http(s) URL`)
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    failUsage(`${label} must be an absolute http(s) URL`)
  }
  return url.origin + url.pathname.replace(/\/+$/, '')
}

function parseCli() {
  let parsed
  try {
    parsed = parseArgs({
      args: process.argv.slice(2),
      allowPositionals: false,
      strict: true,
      options: {
        'base-url': { type: 'string' },
        'api-url': { type: 'string' },
        out: { type: 'string' },
        'guest-compile': { type: 'boolean', default: false },
        account: { type: 'boolean', default: false },
        'deep-ats': { type: 'boolean', default: false },
        share: { type: 'boolean', default: false },
        help: { type: 'boolean', default: false },
      },
    })
  } catch (error) {
    failUsage(error instanceof Error ? error.message : 'invalid arguments')
  }

  const { values } = parsed
  if (values.help) {
    console.log(USAGE)
    process.exit(0)
  }

  const baseUrl = normalizeOrigin(values['base-url'] ?? DEFAULT_BASE_URL, '--base-url')
  const apiUrl = normalizeOrigin(values['api-url'] ?? DEFAULT_API_URL, '--api-url')
  const optionalFlags = ['guest-compile', 'account', 'deep-ats', 'share']
    .filter((flag) => values[flag])

  if (values['deep-ats'] && !values.account) failUsage('--deep-ats requires --account')
  if (values.share && !values.account) failUsage('--share requires --account')

  const needsOptIn = values['guest-compile'] || values.account
  if (needsOptIn && process.env.LATEXY_PRODUCTION_SMOKE !== '1') {
    failUsage('browser/write checks require LATEXY_PRODUCTION_SMOKE=1')
  }

  let storageStatePath = null
  if (values.account) {
    const configured = (process.env.LATEXY_QA_STORAGE_STATE ?? '').trim()
    if (!configured) {
      failUsage('--account requires LATEXY_QA_STORAGE_STATE (Playwright storage state path)')
    }
    storageStatePath = resolve(process.cwd(), configured)
    if (!existsSync(storageStatePath)) {
      failUsage('LATEXY_QA_STORAGE_STATE does not point to an existing file')
    }
    const pathFromRepo = relative(REPO_ROOT, storageStatePath)
    if (pathFromRepo && !pathFromRepo.startsWith('..') && !isAbsolute(pathFromRepo)) {
      failUsage('LATEXY_QA_STORAGE_STATE must be stored outside the repository')
    }
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  const out = values.out ?? join('qa-evidence', `production-smoke-${timestamp}.json`)

  return {
    baseUrl,
    apiUrl,
    out,
    optionalFlags,
    guestCompile: values['guest-compile'],
    account: values.account,
    deepAts: values['deep-ats'],
    share: values.share,
    storageStatePath,
  }
}

function isSafeToken(value) {
  return typeof value === 'string' && SAFE_TOKEN_PATTERN.test(value)
}

function safeString(value, max = 64) {
  return typeof value === 'string' && value.length <= max && SAFE_TOKEN_PATTERN.test(value) ? value : null
}

function timestamp() {
  return new Date().toISOString()
}

function elapsed(startedAt) {
  return Math.max(0, Date.now() - startedAt)
}

function sanitizeError(error) {
  if (error instanceof SmokeFailure) {
    const details = {}
    for (const [key, value] of Object.entries(error.details)) {
      if (typeof value === 'number' || typeof value === 'boolean') details[key] = value
      else if (isSafeToken(value)) details[key] = value
    }
    return { code: error.code, ...details }
  }
  const name = error && typeof error.name === 'string' ? error.name : 'error'
  return { code: isSafeToken(name) ? name : 'error' }
}

function optionalErrorCode(error) {
  const message = String(error && error.message ? error.message : '')
  const causeCode = String(error && error.cause && error.cause.code ? error.cause.code : '')
  if (/Executable doesn't exist|browserType\.launch/i.test(message)) return 'playwright_browser_missing'
  if (error && (error.name === 'TimeoutError' || error.name === 'AbortError')) return 'timeout'
  if (/Timeout/i.test(message)) return 'timeout'
  if (/^(ECONN|ENOTFOUND|EAI_AGAIN|UND_ERR)/.test(causeCode)) return 'network_error'
  if (/net::ERR|ECONN|ENOTFOUND/i.test(message)) return 'network_error'
  return 'optional_check_failed'
}

function printCheck(check) {
  const status = check.httpStatus === null ? '-' : String(check.httpStatus)
  const prefix = check.outcome === 'passed' ? 'PASS' : check.outcome === 'failed' ? 'FAIL' : 'SKIP'
  console.log(
    `[${prefix}] ${check.id.padEnd(42)} ${status.padStart(4)} ${String(check.elapsedMs).padStart(7)}ms  ${check.summary}`,
  )
}

function createRecorder() {
  const checks = []
  return {
    checks,
    add(check) {
      checks.push(check)
      printCheck(check)
    },
  }
}

function skippedOptionalCheck(id, label, method = 'BROWSER', url = null) {
  return {
    id,
    label,
    kind: 'optional',
    required: false,
    method,
    url,
    timestamp: timestamp(),
    httpStatus: null,
    elapsedMs: 0,
    outcome: 'skipped',
    summary: 'flag not enabled',
  }
}

/**
 * Execute one GET check and reduce the response to a redacted verdict.
 * `evaluate` receives the parsed JSON (or null) and response headers, and must
 * return { pass, summary, details }.
 */
async function runHttpCheck(recorder, spec) {
  const {
    id,
    label,
    url,
    method = 'GET',
    required = true,
    bodyKind = 'json',
    evaluate,
  } = spec

  const check = {
    id,
    label,
    kind: required ? 'read-only' : 'optional',
    required,
    method,
    url,
    timestamp: timestamp(),
    httpStatus: null,
    elapsedMs: 0,
    outcome: 'failed',
    summary: 'not run',
  }
  const started = Date.now()

  try {
    const response = await fetch(url, {
      method,
      redirect: 'follow',
      headers: {
        accept: bodyKind === 'json' ? 'application/json' : '*/*',
        'user-agent': 'latexy-production-launch-smoke/1.0 (read-only)',
      },
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
    })
    check.httpStatus = response.status

    let body = null
    if (bodyKind === 'json') {
      try {
        body = await response.json()
      } catch {
        body = null
      }
    } else if (response.body) {
      await response.body.cancel().catch(() => {})
    }

    const verdict = await evaluate({
      status: response.status,
      body,
      headers: response.headers,
    })
    check.outcome = verdict.pass ? 'passed' : 'failed'
    check.summary = verdict.summary
    if (verdict.details && typeof verdict.details === 'object') {
      Object.assign(check, verdict.details)
    }
  } catch (error) {
    check.outcome = 'failed'
    check.summary = 'request_failed'
    check.error = sanitizeError(error)
  } finally {
    check.elapsedMs = elapsed(started)
  }

  recorder.add(check)
  return check
}

function expectStatus(status, expected, summarySuffix) {
  return {
    pass: status === expected,
    summary: status === expected ? summarySuffix ?? `HTTP ${status}` : `HTTP ${status} (expected ${expected})`,
  }
}

function jsonBody(body) {
  return body && typeof body === 'object' && !Array.isArray(body) ? body : null
}

async function probeAsset(url) {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) {
    return { status: null, contentType: null, ok: false, reason: 'missing_url' }
  }
  try {
    const response = await fetch(url, {
      method: 'GET',
      redirect: 'follow',
      headers: { 'user-agent': 'latexy-production-launch-smoke/1.0 (read-only)' },
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
    })
    const contentType = response.headers.get('content-type') ?? ''
    if (response.body) await response.body.cancel().catch(() => {})
    return { status: response.status, contentType, ok: response.status === 200, reason: null }
  } catch {
    return { status: null, contentType: null, ok: false, reason: 'network_error' }
  }
}

async function runReadOnlyChecks(recorder, config) {
  const api = config.apiUrl
  const base = config.baseUrl

  // ---------------- Backend ----------------

  await runHttpCheck(recorder, {
    id: 'backend.health',
    label: 'Backend health',
    url: `${api}/health`,
    evaluate: ({ status, body, headers }) => {
      const health = jsonBody(body)
      const healthStatus = safeString(health?.status)
      const database = safeString(health?.database)
      const redis = safeString(health?.redis)
      const redisCache = safeString(health?.redis_cache)
      const storage = safeString(health?.storage)
      const deploymentTarget = safeString(health?.deployment_target)
      const commitSha = typeof health?.commit_sha === 'string' && SHA_PATTERN.test(health.commit_sha) ? health.commit_sha : null
      const deploymentHold = headers.get('x-latexy-deployment-hold')
      const pass = status === 200 && healthStatus === 'healthy'
      const summaryParts = [`status=${healthStatus ?? 'missing'}`]
      if (!pass) summaryParts.push(`expected=healthy db=${database ?? '?'} redis=${redis ?? '?'} cache=${redisCache ?? '?'} storage=${storage ?? '?'}`)
      return {
        pass,
        summary: summaryParts.join('; '),
        details: {
          healthStatus,
          database,
          redis,
          redisCache,
          storage,
          latexAvailable: typeof health?.latex_available === 'boolean' ? health.latex_available : null,
          deploymentTarget,
          commitSha,
          deploymentHold: deploymentHold === 'true' || deploymentHold === 'false' ? deploymentHold : null,
        },
      }
    },
  })

  await runHttpCheck(recorder, {
    id: 'backend.readyz',
    label: 'Backend readiness',
    url: `${api}/readyz`,
    evaluate: ({ status, body }) => {
      const ready = jsonBody(body)
      const readyStatus = safeString(ready?.status)
      const checks = ready?.checks && typeof ready.checks === 'object' ? ready.checks : {}
      const safeChecks = {}
      for (const key of ['database', 'redis', 'redis_cache']) {
        safeChecks[key] = safeString(checks[key])
      }
      return {
        pass: status === 200 && readyStatus === 'ready',
        summary: `status=${readyStatus ?? 'missing'} (HTTP ${status}, expected ready)`,
        details: { readyStatus, checks: safeChecks },
      }
    },
  })

  await runHttpCheck(recorder, {
    id: 'backend.jobs-health',
    label: 'Job system health',
    url: `${api}/jobs/health`,
    evaluate: ({ status, body }) => {
      const health = jsonBody(body)
      const jobsStatus = safeString(health?.status)
      const redis = health?.redis && typeof health.redis === 'object' ? health.redis : null
      const redisChecks = redis ? Object.keys(redis).length : 0
      const redisOk = redis ? Object.values(redis).every((value) => value === true) : false
      return {
        pass: status === 200 && jobsStatus === 'healthy',
        summary: `status=${jobsStatus ?? 'missing'} redis_ok=${redisOk} (HTTP ${status}, expected healthy)`,
        details: { jobsStatus, redisChecks, redisOk },
      }
    },
  })

  await runHttpCheck(recorder, {
    id: 'backend.entitlements',
    label: 'Effective entitlements (anonymous, quotas omitted)',
    url: `${api}/config/entitlements?include_quotas=false`,
    evaluate: ({ status, body }) => {
      const payload = jsonBody(body)
      const features = payload?.features && typeof payload.features === 'object' ? payload.features : null
      const keys = features ? Object.keys(features) : []
      const enabled = keys.filter((key) => features[key] === true).length
      const disabled = keys.filter((key) => features[key] === false).length
      return {
        pass: status === 200 && keys.length > 0 && typeof features?.compile === 'boolean',
        summary: `${keys.length} features (${enabled} enabled, ${disabled} disabled); compile=${String(features?.compile)}`,
        details: { featureCount: keys.length, enabledCount: enabled, disabledCount: disabled, compileEnabled: features?.compile === true },
      }
    },
  })

  await runHttpCheck(recorder, {
    id: 'backend.templates',
    label: 'Template catalog and sample assets',
    url: `${api}/templates/`,
    evaluate: async ({ status, body }) => {
      const templates = Array.isArray(body) ? body : []
      const withThumbnail = templates.filter((item) => typeof item?.thumbnail_url === 'string' && /^https?:\/\//i.test(item.thumbnail_url))
      const withPdf = templates.filter((item) => typeof item?.pdf_url === 'string' && /^https?:\/\//i.test(item.pdf_url))
      const thumbnailProbe = withThumbnail.length > 0 ? await probeAsset(withThumbnail[0].thumbnail_url) : null
      const pdfProbe = withPdf.length > 0 ? await probeAsset(withPdf[0].pdf_url) : null
      const categories = [...new Set(templates.map((item) => item?.category).filter((value) => typeof value === 'string'))].sort()
      const assetsOk = Boolean(thumbnailProbe?.ok && pdfProbe?.ok)
      const pass = status === 200 && templates.length > 0 && withThumbnail.length > 0 && withPdf.length > 0 && assetsOk
      const summary = `${templates.length} templates; ${withThumbnail.length} thumbnail_url; ${withPdf.length} pdf_url; ` +
        `sample thumbnail=${thumbnailProbe?.status ?? 'n/a'} pdf=${pdfProbe?.status ?? 'n/a'}`
      return {
        pass,
        summary,
        details: {
          templateCount: templates.length,
          withThumbnail: withThumbnail.length,
          withPdf: withPdf.length,
          categories,
          sampleThumbnailStatus: thumbnailProbe?.status ?? null,
          sampleThumbnailContentType: thumbnailProbe?.contentType ?? null,
          samplePdfStatus: pdfProbe?.status ?? null,
          samplePdfContentType: pdfProbe?.contentType ?? null,
        },
      }
    },
  })

  await runHttpCheck(recorder, {
    id: 'backend.subscription-plans',
    label: 'Subscription catalog and quotas',
    url: `${api}/subscription/plans`,
    evaluate: ({ status, body }) => {
      const payload = jsonBody(body)
      const plans = payload?.plans && typeof payload.plans === 'object' ? payload.plans : null
      const billing = payload?.billing && typeof payload.billing === 'object' ? payload.billing : null
      const billingMode = safeString(billing?.mode)
      const billingAvailable = typeof billing?.available === 'boolean' ? billing.available : null
      const billingFeatureEnabled = typeof billing?.feature_enabled === 'boolean' ? billing.feature_enabled : null

      const quotaSummary = (sku) => {
        const quotas = plans?.[sku]?.quotas
        if (!quotas || typeof quotas !== 'object') return null
        const out = {}
        for (const [dimension, policy] of Object.entries(quotas)) {
          if (!policy || typeof policy !== 'object') continue
          if (!Number.isFinite(policy.limit) || typeof policy.window !== 'string') continue
          out[dimension] = { limit: policy.limit, window: policy.window }
        }
        return Object.keys(out).length > 0 ? out : null
      }

      const freeQuotas = quotaSummary('free')
      const basicQuotas = quotaSummary('basic')
      const pass = status === 200 && billingMode !== null && billingAvailable !== null && freeQuotas !== null && basicQuotas !== null
      const describe = (name, quotas) => {
        if (!quotas) return `${name}=missing`
        const compilations = quotas.compilations ? `${quotas.compilations.limit}/${quotas.compilations.window}` : 'n/a'
        return `${name}.compilations=${compilations}`
      }
      return {
        pass,
        summary: `billing mode=${billingMode ?? 'missing'} available=${String(billingAvailable)}; ${describe('free', freeQuotas)}; ${describe('basic', basicQuotas)}`,
        details: {
          billing: {
            mode: billingMode,
            available: billingAvailable,
            featureEnabled: billingFeatureEnabled,
          },
          freeQuotas,
          basicQuotas,
        },
      }
    },
  })

  const protectedChecks = [
    ['backend.protected.resumes', 'Protected resumes API', '/resumes/'],
    ['backend.protected.developer-keys', 'Protected developer keys API', '/developer/keys'],
    ['backend.protected.tracker-applications', 'Protected tracker applications API', '/tracker/applications'],
  ]
  for (const [id, label, path] of protectedChecks) {
    await runHttpCheck(recorder, {
      id,
      label,
      url: `${api}${path}`,
      evaluate: ({ status }) => ({
        pass: status === 401,
        summary: status === 401 ? '401 without credentials as expected' : `HTTP ${status} (expected 401)`,
        details: { authRequired: status === 401 },
      }),
    })
  }

  // ---------------- Frontend ----------------

  await runHttpCheck(recorder, {
    id: 'frontend.deployment-identity',
    label: 'Frontend deployment identity',
    url: `${base}/api/deployment-identity`,
    evaluate: ({ status, body }) => {
      const payload = jsonBody(body)
      const commitSha = typeof payload?.commitSha === 'string' && SHA_PATTERN.test(payload.commitSha) ? payload.commitSha : null
      const source = safeString(payload?.source)
      const sourceValid = source === 'vercel' || source === 'build'
      return {
        pass: status === 200 && commitSha !== null && sourceValid,
        summary: `commit=${commitSha ? commitSha.slice(0, 12) : 'missing'} source=${source ?? 'missing'}`,
        details: { commitSha, source },
      }
    },
  })

  const pages = [
    ['frontend.home', 'Public home page', '/'],
    ['frontend.pricing', 'Public pricing page', '/pricing'],
    ['frontend.templates', 'Public templates page', '/templates'],
    ['frontend.try', 'Public studio page', '/try'],
    ['frontend.login', 'Login page', '/login'],
    ['frontend.faq', 'FAQ page', '/faq'],
    ['frontend.privacy', 'Privacy page', '/privacy'],
    ['frontend.terms', 'Terms page', '/terms'],
    ['frontend.robots', 'robots.txt', '/robots.txt'],
    ['frontend.sitemap', 'sitemap.xml', '/sitemap.xml'],
    ['frontend.llms', 'llms.txt', '/llms.txt'],
  ]
  for (const [id, label, path] of pages) {
    await runHttpCheck(recorder, {
      id,
      label,
      url: `${base}${path}`,
      bodyKind: 'none',
      evaluate: ({ status }) => expectStatus(status, 200, 'HTTP 200'),
    })
  }
}

async function loadPlaywright() {
  try {
    return await import('@playwright/test')
  } catch {
    // Fall through to the frontend workspace, where @playwright/test is a
    // devDependency. Read-only mode never reaches this function.
  }

  let resolved = null
  try {
    const requireFromFrontend = createRequire(join(REPO_ROOT, 'frontend', 'package.json'))
    resolved = requireFromFrontend.resolve('@playwright/test')
  } catch {
    resolved = null
  }
  if (!resolved) {
    throw new SmokeFailure('playwright_not_installed', {
      hint: 'Run pnpm --dir frontend install',
    })
  }
  return import(pathToFileURL(resolved).href)
}

async function chromiumFromPlaywright() {
  const playwright = await loadPlaywright()
  const chromium = playwright?.chromium ?? playwright?.default?.chromium
  if (!chromium) throw new SmokeFailure('playwright_chromium_unavailable')
  return chromium
}

async function dismissOptionalOverlay(page) {
  const candidates = ['Skip', 'Skip for now', 'Skip tour', 'Close']
  for (const name of candidates) {
    const button = page.getByRole('button', { name, exact: true }).first()
    if (await button.isVisible().catch(() => false)) {
      await button.click({ timeout: 5_000 }).catch(() => {})
      return
    }
  }
}

async function runGuestCompileCheck(recorder, config) {
  return runOptionalCheck(recorder, {
    id: 'optional.guest-compile',
    label: 'Anonymous studio compile (consumes one trial)',
    method: 'BROWSER',
    url: `${config.baseUrl}/try`,
    run: async (check) => {
      const chromium = await chromiumFromPlaywright()
      const browser = await chromium.launch({ headless: true })
      try {
        const context = await browser.newContext({
          viewport: { width: 1440, height: 1000 },
          acceptDownloads: false,
        })
        const page = await context.newPage()
        page.setDefaultTimeout(30_000)

        const response = await page.goto(`${config.baseUrl}/try`, {
          waitUntil: 'domcontentloaded',
          timeout: 60_000,
        })
        check.httpStatus = response ? response.status() : null
        if (!response || response.status() !== 200) {
          throw new SmokeFailure('try_page_unavailable', { httpStatus: check.httpStatus })
        }

        await page.locator('[data-editor-mode]').first().waitFor({ state: 'visible', timeout: 60_000 })
        await dismissOptionalOverlay(page)

        const compileButton = page.locator('button[aria-label="Update PDF preview"]').first()
        if (!(await compileButton.isVisible().catch(() => false))) {
          throw new SmokeFailure('guest_compile_unavailable')
        }
        await compileButton.click({ timeout: 30_000 })

        await page.locator('.react-pdf__Page__canvas').first().waitFor({
          state: 'visible',
          timeout: BROWSER_CHECK_TIMEOUT_MS,
        })

        return {
          summary: 'sample kept; one compile submitted; PDF canvas rendered; one anonymous trial consumed',
          details: { tryStatus: check.httpStatus, pdfCanvasVisible: true, trialConsumed: true },
        }
      } finally {
        await browser.close().catch(() => {})
      }
    },
  })
}

async function openAccountWorkspace(config, check) {
  const chromium = await chromiumFromPlaywright()
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
    storageState: config.storageStatePath,
  })
  const page = await context.newPage()
  page.setDefaultTimeout(30_000)

  try {
    const workspaceResponse = await page.goto(`${config.baseUrl}/workspace`, {
      waitUntil: 'domcontentloaded',
      timeout: 60_000,
    })
    const workspaceStatus = workspaceResponse ? workspaceResponse.status() : null
    check.httpStatus = workspaceStatus
    if (!workspaceResponse || workspaceStatus !== 200) {
      throw new SmokeFailure('workspace_unavailable', { httpStatus: workspaceStatus })
    }

    // Read the session token from the same Better Auth endpoint AuthSync uses.
    // It stays in memory and is never written to evidence or logs.
    const auth = await page.evaluate(async () => {
      try {
        const response = await fetch('/api/auth/get-session', {
          credentials: 'include',
          cache: 'no-store',
        })
        if (!response.ok) return { token: null }
        const data = await response.json().catch(() => null)
        const token = data && data.session ? data.session.token : null
        return { token: typeof token === 'string' && token.length > 0 ? token : null }
      } catch {
        return { token: null }
      }
    })
    if (!auth || !auth.token) throw new SmokeFailure('account_not_authenticated')

    await dismissOptionalOverlay(page)

    // Prefer opening an existing resume. Creating one is the fallback when the
    // QA account has no documents.
    const editLinks = page.locator('a[href*="/workspace/"][href$="/edit"]')
    let resumeSource = 'opened'
    let editorUrl = null

    const foundExisting = await page.waitForFunction(
      () => document.querySelectorAll('a[href*="/workspace/"][href$="/edit"]').length > 0,
      undefined,
      { timeout: 45_000 },
    ).then(() => true).catch(() => false)

    if (foundExisting) {
      const href = await editLinks.first().getAttribute('href')
      if (!href) throw new SmokeFailure('workspace_resume_link_missing')
      editorUrl = new URL(href, config.baseUrl).href
      await page.goto(editorUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    } else {
      resumeSource = 'created'
      await page.goto(`${config.baseUrl}/workspace/new`, {
        waitUntil: 'domcontentloaded',
        timeout: 60_000,
      })
      const titleInput = page.locator('#new-resume-title').first()
      await titleInput.waitFor({ state: 'visible', timeout: 45_000 })
      await titleInput.fill(`QA production smoke ${new Date().toISOString()}`)
      const startBlank = page.getByRole('button', { name: 'Start from Blank', exact: true }).first()
      if (!(await startBlank.isVisible().catch(() => false))) {
        throw new SmokeFailure('blank_resume_creation_unavailable')
      }
      await startBlank.click({ timeout: 30_000 })
      await page.waitForURL(/\/workspace\/[^/]+\/edit/, { timeout: 60_000 })
      editorUrl = page.url()
    }

    if (!/\/workspace\/[^/]+\/edit/.test(new URL(editorUrl).pathname)) {
      throw new SmokeFailure('workspace_editor_not_opened')
    }

    await page.locator('[data-editor-mode]').first().waitFor({ state: 'visible', timeout: 90_000 })
    await dismissOptionalOverlay(page)

    // Compile. Visual mode labels the action "Update preview"; source mode and
    // in-flight states are covered by the same bounded locator.
    const compileButton = page.getByRole('button', { name: /^(Compile|Update preview|Preparing…)$/ }).first()
    if (!(await compileButton.isVisible().catch(() => false))) {
      throw new SmokeFailure('workspace_compile_unavailable')
    }
    await compileButton.click({ timeout: 30_000 })
    await page.locator('.react-pdf__Page__canvas').first().waitFor({
      state: 'visible',
      timeout: BROWSER_CHECK_TIMEOUT_MS,
    })

    // Download the rendered PDF and verify the file signature. The bytes and
    // filename are intentionally not recorded.
    const downloadButton = page.getByRole('button', { name: 'PDF', exact: true }).first()
    await downloadButton.waitFor({ state: 'visible', timeout: 60_000 })
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: BROWSER_CHECK_TIMEOUT_MS }),
      downloadButton.click({ timeout: 30_000 }),
    ])
    const downloadPath = await download.path()
    if (!downloadPath) throw new SmokeFailure('pdf_download_missing')
    const handle = await open(downloadPath, 'r')
    let magicOk = false
    let pdfBytes = null
    try {
      const header = Buffer.alloc(5)
      const { bytesRead } = await handle.read(header, 0, 5, 0)
      magicOk = bytesRead === 5 && header.toString('latin1') === '%PDF-'
    } finally {
      await handle.close().catch(() => {})
    }
    const pdfStat = await stat(downloadPath).catch(() => null)
    pdfBytes = pdfStat ? pdfStat.size : null
    if (!magicOk) throw new SmokeFailure('pdf_download_not_pdf')

    // Save through the toolbar action and require the resume PUT to succeed.
    const saveButton = page.getByRole('button', { name: 'Save', exact: true }).first()
    await saveButton.waitFor({ state: 'visible', timeout: 30_000 })
    const [saveResponse] = await Promise.all([
      page.waitForResponse(
        (response) => response.request().method() === 'PUT' && /\/resumes\/[^/]+$/.test(new URL(response.url()).pathname),
        { timeout: 60_000 },
      ),
      saveButton.click({ timeout: 30_000 }),
    ])
    if (saveResponse.status() !== 200) {
      throw new SmokeFailure('resume_save_failed', { httpStatus: saveResponse.status() })
    }

    // Hard reload and require the editor shell to come back. This does not
    // compare user content or titles.
    const reloadResponse = await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 })
    const reloadStatus = reloadResponse ? reloadResponse.status() : null
    if (!reloadResponse || reloadStatus !== 200) {
      throw new SmokeFailure('editor_reload_failed', { httpStatus: reloadStatus })
    }
    await page.locator('[data-editor-mode]').first().waitFor({ state: 'visible', timeout: 90_000 })

    return {
      summary: `${resumeSource} resume; compiled; PDF %PDF- verified; saved; hard-reload editor loaded`,
      details: {
        authenticated: true,
        resumeSource,
        workspaceStatus,
        compiled: true,
        pdfDownloaded: true,
        pdfMagic: true,
        pdfBytes,
        saved: true,
        reloadStatus,
        editorLoadedAfterReload: true,
      },
      runtime: {
        browser,
        context,
        page,
        token: auth.token,
      },
    }
  } catch (error) {
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
    throw error
  }
}

async function runAccountCheck(recorder, config) {
  let runtime = null
  const check = await runOptionalCheck(recorder, {
    id: 'optional.account',
    label: 'Authenticated workspace compile/download/save/reload',
    method: 'BROWSER',
    url: `${config.baseUrl}/workspace`,
    run: async (checkResult) => {
      const result = await openAccountWorkspace(config, checkResult)
      runtime = result.runtime
      return { summary: result.summary, details: result.details }
    },
  })
  return { check, runtime }
}

async function runDeepAtsCheck(recorder, config, accountRuntime) {
  return runOptionalCheck(recorder, {
    id: 'optional.deep-ats',
    label: 'Synthetic deep ATS analysis to terminal state',
    method: 'POST',
    url: `${config.apiUrl}/ats/deep-analyze`,
    run: async (check) => {
      if (!accountRuntime || !accountRuntime.token) {
        throw new SmokeFailure('blocked_by_account_check')
      }

      const headers = {
        authorization: `Bearer ${accountRuntime.token}`,
        'content-type': 'application/json',
        accept: 'application/json',
      }
      const submit = await fetch(`${config.apiUrl}/ats/deep-analyze`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ latex_content: SYNTHETIC_ATS_LATEX }),
        signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
      })
      check.httpStatus = submit.status
      let submitBody = null
      try {
        submitBody = await submit.json()
      } catch {
        submitBody = null
      }
      const jobId = typeof submitBody?.job_id === 'string' ? submitBody.job_id : null
      if (submit.status !== 200 || !submitBody?.success || !jobId) {
        throw new SmokeFailure('deep_ats_submit_failed', { httpStatus: submit.status })
      }

      const started = Date.now()
      let polls = 0
      let terminalStatus = 'unknown'
      while (Date.now() - started < DEEP_ATS_BUDGET_MS) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, DEEP_ATS_POLL_MS))
        polls += 1
        const poll = await fetch(`${config.apiUrl}/jobs/${encodeURIComponent(jobId)}/state`, {
          headers,
          signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
        })
        if (poll.status === 401 || poll.status === 403) {
          throw new SmokeFailure('deep_ats_poll_unauthorized', { httpStatus: poll.status })
        }
        if (poll.status !== 200) continue
        let state = null
        try {
          state = await poll.json()
        } catch {
          state = null
        }
        terminalStatus = safeString(state?.status) ?? 'unknown'
        if (TERMINAL_JOB_STATUSES.has(terminalStatus)) break
      }

      if (!TERMINAL_JOB_STATUSES.has(terminalStatus)) {
        check.terminalStatus = terminalStatus
        check.polls = polls
        throw new SmokeFailure('deep_ats_timeout', { polls })
      }
      if (terminalStatus !== 'completed') {
        check.terminalStatus = terminalStatus
        check.polls = polls
        throw new SmokeFailure(`deep_ats_${terminalStatus}`, { polls })
      }

      return {
        summary: `synthetic resume; terminal=${terminalStatus}; polls=${polls}; bounded=180s`,
        details: {
          submitStatus: submit.status,
          terminalStatus,
          polls,
          boundedSeconds: 180,
          syntheticResume: true,
        },
      }
    },
  })
}

async function findShareUrl(page) {
  const label = page.getByText('Shareable link', { exact: true }).first()
  await label.waitFor({ state: 'visible', timeout: 60_000 })
  const value = await label.locator('..').locator('span.font-mono').first().textContent().catch(() => null)
  const trimmed = typeof value === 'string' ? value.trim() : ''
  if (/^https?:\/\//i.test(trimmed)) {
    try {
      if (new URL(trimmed).pathname.startsWith('/r/')) return trimmed
    } catch {
      // fall through to the bounded scan
    }
  }

  const handle = await page.waitForFunction(
    () => {
      const nodes = Array.from(document.querySelectorAll('.font-mono'))
      for (const node of nodes) {
        const value = (node.textContent || '').trim()
        if (!/^https?:\/\//i.test(value)) continue
        try {
          if (new URL(value).pathname.startsWith('/r/')) return value
        } catch {
          // ignore malformed text
        }
      }
      return null
    },
    undefined,
    { timeout: 60_000 },
  )
  return handle.jsonValue()
}

async function runShareCheck(recorder, config, accountRuntime) {
  return runOptionalCheck(recorder, {
    id: 'optional.share',
    label: 'Public share link rendered in incognito context',
    method: 'BROWSER',
    url: `${config.baseUrl}/workspace`,
    run: async (check) => {
      if (!accountRuntime || !accountRuntime.page || !accountRuntime.context) {
        throw new SmokeFailure('blocked_by_account_check')
      }
      const { page, context } = accountRuntime
      await page.bringToFront()

      const shareButton = page.locator('button[aria-label="Share resume"], button[aria-label="Manage share link"]').first()
      if (!(await shareButton.isVisible().catch(() => false))) {
        throw new SmokeFailure('share_action_unavailable')
      }
      await shareButton.click({ timeout: 30_000 })
      await page.getByText('Share Resume', { exact: true }).first().waitFor({ state: 'visible', timeout: 30_000 })

      const generate = page.getByRole('button', { name: /Generate shareable link/i }).first()
      if (await generate.isVisible().catch(() => false)) {
        await generate.click({ timeout: 30_000 })
      }

      const shareUrl = await findShareUrl(page)
      if (typeof shareUrl !== 'string' || !/^https?:\/\//i.test(shareUrl)) {
        throw new SmokeFailure('share_url_missing')
      }

      const incognito = await context.browser().newContext({
        viewport: { width: 1280, height: 900 },
        acceptDownloads: false,
      })
      try {
        const incognitoPage = await incognito.newPage()
        incognitoPage.setDefaultTimeout(30_000)
        const response = await incognitoPage.goto(shareUrl, {
          waitUntil: 'domcontentloaded',
          timeout: 60_000,
        })
        check.httpStatus = response ? response.status() : null
        if (!response || response.status() !== 200) {
          throw new SmokeFailure('share_page_unavailable', { httpStatus: check.httpStatus })
        }

        const frame = incognitoPage.locator('iframe').first()
        await frame.waitFor({ state: 'visible', timeout: 60_000 })
        const frameSrc = await frame.getAttribute('src')
        let frameStatus = null
        let frameIsPdf = false
        if (frameSrc) {
          const absoluteFrameSrc = new URL(frameSrc, config.baseUrl).href
          const frameResponse = await incognito.request.get(absoluteFrameSrc, { timeout: 60_000 })
          frameStatus = frameResponse.status()
          frameIsPdf = (frameResponse.headers()['content-type'] ?? '').toLowerCase().includes('pdf')
        }

        const pass = frameStatus === 200 && frameIsPdf
        if (!pass) throw new SmokeFailure('share_pdf_frame_unavailable', { httpStatus: frameStatus })

        return {
          summary: `share link rendered without auth; PDF frame HTTP ${frameStatus}`,
          details: {
            sharePageRendered: true,
            pdfFrameVisible: true,
            pdfFrameStatus: frameStatus,
            pdfFrameIsPdf: frameIsPdf,
          },
        }
      } finally {
        await incognito.close().catch(() => {})
      }
    },
  })
}

async function runOptionalCheck(recorder, spec) {
  const check = {
    id: spec.id,
    label: spec.label,
    kind: 'optional',
    required: false,
    method: spec.method,
    url: spec.url,
    timestamp: timestamp(),
    httpStatus: null,
    elapsedMs: 0,
    outcome: 'failed',
    summary: 'not run',
  }
  const started = Date.now()

  try {
    const result = await spec.run(check)
    if (result && typeof result === 'object') {
      if (result.details && typeof result.details === 'object') Object.assign(check, result.details)
      if (typeof result.summary === 'string') check.summary = result.summary
    }
    check.outcome = 'passed'
    if (check.summary === 'not run') check.summary = 'passed'
  } catch (error) {
    check.outcome = 'failed'
    if (error instanceof SmokeFailure) {
      check.summary = error.code
      check.error = sanitizeError(error)
    } else {
      const code = optionalErrorCode(error)
      check.summary = code
      check.error = { code }
    }
  } finally {
    check.elapsedMs = elapsed(started)
  }

  recorder.add(check)
  return check
}

function summarize(checks) {
  const count = (outcome) => checks.filter((check) => check.outcome === outcome).length
  const required = checks.filter((check) => check.required)
  const enabledOptional = checks.filter((check) => !check.required && check.outcome !== 'skipped')
  return {
    total: checks.length,
    passed: count('passed'),
    failed: count('failed'),
    skipped: count('skipped'),
    required: required.length,
    requiredPassed: required.filter((check) => check.outcome === 'passed').length,
    requiredFailed: required.filter((check) => check.outcome === 'failed').length,
    optionalEnabled: enabledOptional.length,
    optionalFailed: enabledOptional.filter((check) => check.outcome === 'failed').length,
    ok: required.every((check) => check.outcome === 'passed') && enabledOptional.every((check) => check.outcome !== 'failed'),
  }
}

async function writeEvidence(path, evidence) {
  const absolute = resolve(process.cwd(), path)
  await mkdir(dirname(absolute), { recursive: true })
  await writeFile(absolute, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
  return absolute
}

async function main() {
  const config = parseCli()
  const recorder = createRecorder()
  const startedAt = timestamp()

  console.log('Latexy production launch smoke')
  console.log(`  frontend: ${config.baseUrl}`)
  console.log(`  backend:  ${config.apiUrl}`)
  console.log(`  mode:     ${config.optionalFlags.length === 0 ? 'read-only (GET only)' : `read-only + ${config.optionalFlags.join(', ')}`}`)
  if (config.guestCompile) {
    console.warn('WARNING: --guest-compile submits a real anonymous compile and consumes one trial.')
  }
  if (config.account) {
    console.warn('WARNING: --account performs writes with the dedicated QA account from LATEXY_QA_STORAGE_STATE.')
  }
  if (config.deepAts) {
    console.warn('WARNING: --deep-ats spends configured LLM quota and polls for up to 3 minutes.')
  }
  if (config.share) {
    console.warn('WARNING: --share creates or reuses a public share link on the QA resume.')
  }
  console.log('')

  await runReadOnlyChecks(recorder, config)

  let accountRuntime = null
  try {
    if (config.guestCompile) {
      await runGuestCompileCheck(recorder, config)
    } else {
      recorder.add(skippedOptionalCheck(
        'optional.guest-compile',
        'Anonymous studio compile (consumes one trial)',
        'BROWSER',
        `${config.baseUrl}/try`,
      ))
    }

    if (config.account) {
      const accountResult = await runAccountCheck(recorder, config)
      accountRuntime = accountResult.runtime
    } else {
      recorder.add(skippedOptionalCheck(
        'optional.account',
        'Authenticated workspace compile/download/save/reload',
        'BROWSER',
        `${config.baseUrl}/workspace`,
      ))
    }

    if (config.deepAts) {
      await runDeepAtsCheck(recorder, config, accountRuntime)
    } else {
      recorder.add(skippedOptionalCheck(
        'optional.deep-ats',
        'Synthetic deep ATS analysis to terminal state',
        'POST',
        `${config.apiUrl}/ats/deep-analyze`,
      ))
    }

    if (config.share) {
      await runShareCheck(recorder, config, accountRuntime)
    } else {
      recorder.add(skippedOptionalCheck(
        'optional.share',
        'Public share link rendered in incognito context',
        'BROWSER',
        `${config.baseUrl}/workspace`,
      ))
    }
  } finally {
    if (accountRuntime) {
      await accountRuntime.context.close().catch(() => {})
      await accountRuntime.browser.close().catch(() => {})
    }
  }

  const finishedAt = timestamp()
  const summary = summarize(recorder.checks)
  const evidence = {
    schemaVersion: 1,
    tool: 'latexy-production-launch-smoke',
    startedAt,
    finishedAt,
    config: {
      baseUrl: config.baseUrl,
      apiUrl: config.apiUrl,
      out: config.out,
      optionalFlags: config.optionalFlags,
      readOnlyByDefault: true,
    },
    environment: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
    },
    summary,
    checks: recorder.checks,
  }

  const evidencePath = await writeEvidence(config.out, evidence)

  console.log('')
  console.log(`Evidence: ${evidencePath}`)
  console.log(
    `Summary: ${summary.passed} passed, ${summary.failed} failed, ${summary.skipped} skipped ` +
      `(${summary.required} required, ${summary.optionalEnabled} optional run)`,
  )
  console.log(`RESULT: ${summary.ok ? 'PASS' : 'FAIL'}`)

  return summary.ok ? 0 : 1
}

main()
  .then((code) => {
    process.exitCode = code
  })
  .catch((error) => {
    console.error(`production-launch-smoke: ${error instanceof SmokeFailure ? error.code : 'unexpected_error'}`)
    process.exitCode = 1
  })
