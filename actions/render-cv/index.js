'use strict'

const { appendFile, mkdir, readFile, rename, rm, stat, writeFile } = require('node:fs/promises')
const { dirname, isAbsolute, relative, resolve, sep } = require('node:path')
const { randomUUID } = require('node:crypto')

const DEFAULT_API_URL = 'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
const COMPILERS = new Set(['pdflatex', 'xelatex', 'lualatex'])
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function input(name, fallback = '') {
  const key = `INPUT_${name.replace(/ /g, '_').toUpperCase()}`
  return String(process.env[key] ?? fallback).trim()
}

function workspacePath(workspace, configured, label) {
  if (!configured || configured.includes('\0')) throw new Error(`${label} path is invalid`)
  const root = resolve(workspace)
  const candidate = resolve(root, configured)
  const rel = relative(root, candidate)
  if (isAbsolute(rel) || rel === '..' || rel.startsWith(`..${sep}`)) {
    throw new Error(`${label} must stay inside GITHUB_WORKSPACE`)
  }
  return candidate
}

function sameOriginUrl(value, base, label) {
  const url = new URL(value, base)
  if (url.origin !== base.origin) {
    throw new Error(`${label} must use the configured Latexy API origin`)
  }
  if (url.username || url.password) throw new Error(`${label} must not contain credentials`)
  return url
}

function oneLine(value, maximum = 500) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').slice(0, maximum)
}

function validatedApiUrl(value) {
  const url = new URL(value)
  const local = new Set(['localhost', '127.0.0.1', '::1']).has(url.hostname)
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) {
    throw new Error('api-url must use HTTPS (HTTP is allowed only for local testing)')
  }
  url.pathname = url.pathname.replace(/\/$/, '')
  url.search = ''
  url.hash = ''
  return url
}

async function responseError(response) {
  const fallback = `HTTP ${response.status}`
  try {
    const body = await response.json()
    const detail = body?.error?.message || body?.detail || body?.error
    return typeof detail === 'string' && detail.trim() ? `${fallback}: ${detail.slice(0, 500)}` : fallback
  } catch {
    return fallback
  }
}

async function apiFetch(fetchImpl, url, apiKey, init = {}) {
  const response = await fetchImpl(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers || {}),
    },
    redirect: 'error',
    signal: init.signal || AbortSignal.timeout(30_000),
  })
  if (!response.ok) throw new Error(await responseError(response))
  return response
}

async function renderCv(config, dependencies = {}) {
  const fetchImpl = dependencies.fetchImpl || fetch
  const sleep = dependencies.sleep || ((ms) => new Promise((resolveSleep) => setTimeout(resolveSleep, ms)))
  const log = dependencies.log || (() => {})
  const started = Date.now()
  const deadline = started + config.timeoutSeconds * 1000

  const sourceInfo = await stat(config.sourcePath)
  if (!sourceInfo.isFile()) throw new Error('source must be a regular file')
  if (sourceInfo.size > 500_000) throw new Error('source exceeds the Latexy 500,000-byte limit')
  const latexContent = await readFile(config.sourcePath, 'utf8')
  if (!latexContent.trim()) throw new Error('source is empty')

  const compileUrl = new URL('/api/v1/compile', config.apiUrl)
  const queuedResponse = await apiFetch(fetchImpl, compileUrl, config.apiKey, {
    method: 'POST',
    body: JSON.stringify({ latex_content: latexContent, compiler: config.compiler }),
  })
  const queued = await queuedResponse.json()
  if (!UUID_PATTERN.test(queued?.job_id || '') || !queued?.poll_url) {
    throw new Error('Latexy returned an invalid queued-job response')
  }
  const pollUrl = sameOriginUrl(queued.poll_url, config.apiUrl, 'poll_url')
  log(`Latexy job ${queued.job_id} queued`)

  let completed
  while (Date.now() < deadline) {
    const response = await apiFetch(fetchImpl, pollUrl, config.apiKey)
    const job = await response.json()
    if (job.status === 'completed') {
      completed = job
      break
    }
    if (job.status === 'failed' || job.status === 'cancelled') {
      throw new Error(`Latexy job ${job.status}: ${oneLine(job.error || 'no error detail')}`)
    }
    const status = oneLine(job.status || 'unknown', 80)
    const stage = job.stage ? ` (${oneLine(job.stage, 120)})` : ''
    log(`Latexy job ${status}${stage}`)
    await sleep(Math.min(config.pollIntervalMs, Math.max(0, deadline - Date.now())))
  }
  if (!completed) throw new Error(`Latexy compilation timed out after ${config.timeoutSeconds} seconds`)
  if (!completed.pdf_url) throw new Error('Latexy completed the job without a downloadable PDF')

  const pdfResponse = await apiFetch(
    fetchImpl,
    sameOriginUrl(completed.pdf_url, config.apiUrl, 'pdf_url'),
    config.apiKey,
  )
  const pdf = Buffer.from(await pdfResponse.arrayBuffer())
  if (pdf.length < 5 || pdf.subarray(0, 5).toString('ascii') !== '%PDF-') {
    throw new Error('Latexy download did not contain a valid PDF header')
  }

  await mkdir(dirname(config.outputPath), { recursive: true })
  const temporary = `${config.outputPath}.${randomUUID()}.tmp`
  try {
    await writeFile(temporary, pdf, { mode: 0o600 })
    await rename(temporary, config.outputPath)
  } finally {
    await rm(temporary, { force: true })
  }
  return { jobId: queued.job_id, pdfPath: config.outputPath, bytes: pdf.length }
}

async function setOutput(name, value) {
  if (!process.env.GITHUB_OUTPUT) return
  await appendFile(process.env.GITHUB_OUTPUT, `${name}=${String(value).replace(/[\r\n]/g, '')}\n`)
}

function configurationFromEnvironment() {
  const workspace = process.env.GITHUB_WORKSPACE || process.cwd()
  const apiKey = input('api-key')
  if (!apiKey) throw new Error('api-key is required')
  const compiler = input('compiler', 'pdflatex').toLowerCase()
  if (!COMPILERS.has(compiler)) throw new Error(`Unsupported compiler: ${compiler}`)
  const timeoutSeconds = Number(input('timeout-seconds', '180'))
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 10 || timeoutSeconds > 900) {
    throw new Error('timeout-seconds must be an integer from 10 to 900')
  }
  return {
    apiKey,
    apiUrl: validatedApiUrl(input('api-url', DEFAULT_API_URL)),
    sourcePath: workspacePath(workspace, input('source', 'resume.tex'), 'source'),
    outputPath: workspacePath(workspace, input('output', 'resume.pdf'), 'output'),
    compiler,
    timeoutSeconds,
    pollIntervalMs: 2_000,
  }
}

async function main() {
  try {
    const config = configurationFromEnvironment()
    process.stdout.write(`::add-mask::${config.apiKey}\n`)
    const result = await renderCv(config, { log: (message) => console.log(message) })
    await setOutput('job-id', result.jobId)
    await setOutput('pdf-path', result.pdfPath)
    console.log(`Rendered ${result.bytes} bytes to ${result.pdfPath}`)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    process.stderr.write(`::error title=Latexy render failed::${oneLine(message)}\n`)
    process.exitCode = 1
  }
}

module.exports = {
  configurationFromEnvironment,
  renderCv,
  sameOriginUrl,
  validatedApiUrl,
  workspacePath,
}

if (require.main === module) void main()
