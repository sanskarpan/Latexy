// Local-only fixture proxy around the real production worker. It never reads
// credentials, changes application files, or serves on a public interface.
import { createServer, request as httpRequest } from 'node:http'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { inheritedEnvironment, signalProcessTree, watchParent } from './playwright-server.mjs'

export function localUpstream(value) {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash || !url.port) {
    throw new Error('PWA acceptance requires an explicit loopback HTTP upstream')
  }
  return url
}

function upstreamRequestOptions(upstreamValue, requestTarget, { method, headers } = {}) {
  const upstream = localUpstream(upstreamValue)
  const localRequest = new URL(requestTarget, 'http://localhost')
  // A normalized pathname can begin with // after removing dot segments.
  // Keep it an HTTP request path; resolving it as a URL would replace the host.
  return {
    protocol: upstream.protocol, hostname: upstream.hostname, port: upstream.port,
    path: localRequest.pathname + localRequest.search,
    method, headers: { ...headers, host: upstream.host },
  }
}

export function versionedWorker(original, headers, version) {
  const body = version === 1 ? Buffer.from(original)
    : Buffer.concat([original, Buffer.from(`\n// isolated PWA acceptance version ${version}\n`)])
  const identity = {
    originalSha256: createHash('sha256').update(original).digest('hex'),
    derivedSha256: createHash('sha256').update(body).digest('hex'), version,
  }
  const nextHeaders = { ...headers, 'cache-control': 'no-cache', 'content-length': body.length }
  delete nextHeaders.etag
  delete nextHeaders['last-modified']
  delete nextHeaders['transfer-encoding']
  return { body, identity, headers: nextHeaders }
}

export function createPwaAcceptanceProxy(upstreamValue, requestUpstream = httpRequest) {
  const upstream = localUpstream(upstreamValue)
  let version = 1
  let workerIdentity = null
  const server = createServer((incoming, response) => {
    const localRequest = new URL(incoming.url, 'http://localhost')
    const pathname = localRequest.pathname
    const json = (status, value) => {
      response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
      response.end(JSON.stringify(value))
    }
    if (pathname === '/__pwa_acceptance__/worker-version') {
      if (incoming.method === 'POST') version += 1
      else if (incoming.method !== 'GET') return json(405, { error: 'method_not_allowed' })
      return json(200, { version, workerIdentity })
    }
    if (pathname === '/api/pwa-acceptance/private' || pathname === '/api/pwa-acceptance/private.pdf') {
      const owner = incoming.headers['x-test-owner']
      if (incoming.method !== 'GET' || !['alpha', 'beta'].includes(owner)) {
        return json(401, { error: 'synthetic_owner_required' })
      }
      response.writeHead(200, {
        'Content-Type': pathname.endsWith('.pdf') ? 'application/pdf' : 'application/json',
        'Cache-Control': 'private, no-store',
      })
      return response.end(pathname.endsWith('.pdf')
        ? `%PDF-1.4\nSynthetic private PDF for ${owner}\n%%EOF`
        : JSON.stringify({ owner, source: `Synthetic private source for ${owner}` }))
    }
    const isWorker = pathname === '/sw.js'
    const headers = { ...incoming.headers }
    // Appending a harmless version comment must not corrupt compressed bytes.
    if (isWorker) delete headers['accept-encoding']
    // Never interpret the incoming request target as a proxy destination.
    const outgoing = requestUpstream(upstreamRequestOptions(upstream, localRequest, {
      method: incoming.method, headers,
    }), upstreamResponse => {
      if (!isWorker || upstreamResponse.statusCode !== 200) {
        response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers)
        upstreamResponse.pipe(response)
        return
      }
      const chunks = []
      let size = 0
      upstreamResponse.on('data', chunk => {
        size += chunk.length
        if (size > 8 * 1024 * 1024) {
          upstreamResponse.destroy()
          json(502, { error: 'isolated_worker_exceeds_limit' })
          return
        }
        chunks.push(chunk)
      })
      upstreamResponse.on('end', () => {
        const original = Buffer.concat(chunks)
        const derived = versionedWorker(original, upstreamResponse.headers, version)
        workerIdentity = derived.identity
        response.writeHead(200, derived.headers)
        response.end(derived.body)
      })
    })
    outgoing.setTimeout(30_000, () => outgoing.destroy())
    outgoing.on('error', () => {
      if (response.headersSent) response.destroy()
      else json(502, { error: 'isolated_upstream_unavailable' })
    })
    incoming.pipe(outgoing)
  })
  return server
}

async function main() {
  const port = Number(process.env.PLAYWRIGHT_PWA_PORT ?? '5193')
  if (!Number.isInteger(port) || port < 1024 || port > 62535) throw new Error('Invalid PWA acceptance port')
  const existingUpstream = process.env.PWA_ACCEPTANCE_UPSTREAM_URL
  const upstream = localUpstream(existingUpstream ?? `http://127.0.0.1:${port + 1}`)
  const server = createPwaAcceptanceProxy(upstream.href)
  let child
  let stopping = false
  let stopParentWatch = () => {}
  async function stop(code = 0) {
    if (stopping) return
    stopping = true
    stopParentWatch()
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    if (child && child.exitCode === null) {
      signalProcessTree(child, 'SIGTERM')
      await Promise.race([new Promise(resolve => child.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 7000))])
      if (child.exitCode === null) signalProcessTree(child, 'SIGKILL')
    }
    process.exit(code)
  }
  process.once('SIGINT', () => void stop(130))
  process.once('SIGTERM', () => void stop(143))
  stopParentWatch = watchParent(() => void stop(1))
  if (!existingUpstream) {
    child = spawn(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), 'playwright-server.mjs'),
      '--port', upstream.port, '--mode', 'production'], {
      env: { ...inheritedEnvironment(), PLAYWRIGHT_APP_URL: `http://localhost:${port}` },
      stdio: 'inherit', detached: process.platform !== 'win32',
    })
    child.once('error', () => void stop(1))
    child.once('exit', () => { if (!stopping) void stop(1) })
  }
  server.listen(port, '127.0.0.1')
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) await main()
