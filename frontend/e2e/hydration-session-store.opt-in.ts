import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, realpathSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'

import { test, expect } from '@playwright/test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { useSession as currentUseSession } from '../src/lib/auth-client'

const frontendRoot = path.resolve(process.cwd())
const HYDRATION_BASELINE_SHA = '2b84f7c2d04d85812249d718fdbae9bcd30db4a8'

const createSessionView = (useSession: typeof currentUseSession) => function SessionView({ label }: { label: string }) {
  const { data, isPending, error, isRefetching, refetch } = useSession()
  const status = error ? 'error' : isPending ? 'pending' : isRefetching ? 'refetching' : 'resolved'
  const token = data?.session?.token ?? ''
  const userId = data?.user?.id ?? ''
  return React.createElement(
    'div',
    { 'data-session-view': label },
    React.createElement('span', { 'data-session-state': label }, status),
    React.createElement('span', { 'data-session-user': label }, userId),
    React.createElement('span', { 'data-session-token': label }, token),
    React.createElement('button', { type: 'button', 'data-session-refetch': label, onClick: () => void refetch() }, 'Refetch'),
  )
}

const browserSource = (authClientPath: string, authSyncPath?: string, apiClientPath?: string) => `
import React from 'react'
import { hydrateRoot } from 'react-dom/client'
import { useSession } from ${JSON.stringify(authClientPath)}
${authSyncPath && apiClientPath ? `import { AuthSync } from ${JSON.stringify(authSyncPath)}
import { apiClient } from ${JSON.stringify(apiClientPath)}` : ''}

function SessionView({ label }) {
  const { data, isPending, error, isRefetching, refetch } = useSession()
  const status = error ? 'error' : isPending ? 'pending' : isRefetching ? 'refetching' : 'resolved'
  const token = data?.session?.token ?? ''
  const userId = data?.user?.id ?? ''
  return React.createElement(
    'div',
    { 'data-session-view': label },
    React.createElement('span', { 'data-session-state': label }, status),
    React.createElement('span', { 'data-session-user': label }, userId),
    React.createElement('span', { 'data-session-token': label }, token),
    React.createElement('button', { type: 'button', 'data-session-refetch': label, onClick: () => void refetch() }, 'Refetch'),
  )
}

${authSyncPath && apiClientPath ? "window.probeApiClientAuth = () => apiClient.getMe().then(() => true)" : ''}

window.startHydrationRepro = () => {
  hydrateRoot(
    document.getElementById('early-root'),
    ${authSyncPath && apiClientPath ? "React.createElement(React.Fragment, null, React.createElement(SessionView, { label: 'early' }), React.createElement(AuthSync))" : "React.createElement(SessionView, { label: 'early' })"},
  )
  const waitForResolvedSession = () => {
    if (document.querySelector('[data-session-user="early"]')?.textContent === 'owner-a') {
      hydrateRoot(document.getElementById('late-root'), React.createElement(SessionView, { label: 'late' }))
      return
    }
    window.setTimeout(waitForResolvedSession, 0)
  }
  waitForResolvedSession()
}
`

test('real Better Auth SSR snapshot stays stable for a late consumer and refreshes safely', async ({ page }) => {
  const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), 'latexy-auth-hydration-'))
  const browserEntryPath = path.join(temporaryDirectory, 'client.tsx')
  const browserBundlePath = path.join(temporaryDirectory, 'client.js')
  const authClientPath = path.join(frontendRoot, 'src/lib/auth-client.ts')
  const authSyncPath = path.join(frontendRoot, 'src/components/AuthSync.tsx')
  const apiClientPath = path.join(frontendRoot, 'src/lib/api-client.ts')
  const baselineMode = process.env.HYDRATION_AUTH_CLIENT_BASELINE === '1'
  const browserAuthClientPath = baselineMode
    ? path.join(temporaryDirectory, 'baseline-auth-client.ts')
    : authClientPath
  if (baselineMode) {
    const baselineSource = execFileSync('git', ['show', `${HYDRATION_BASELINE_SHA}:frontend/src/lib/auth-client.ts`], {
      cwd: path.resolve(frontendRoot, '..'),
      encoding: 'utf8',
    })
    writeFileSync(browserAuthClientPath, baselineSource)
  }
  const nodeModulesPath = realpathSync(path.join(frontendRoot, 'node_modules'))
  const repoNodeModulesPath = path.resolve(frontendRoot, '..', 'node_modules')
  const vitestPackagePath = require.resolve('vitest/package.json', { paths: [frontendRoot] })
  const esbuildEntry = createRequire(vitestPackagePath).resolve('esbuild')
  const { build } = await import(esbuildEntry)
  const serverBundlePath = path.join(frontendRoot, `.tmp-${path.basename(temporaryDirectory)}-auth-client.cjs`)
  if (baselineMode) {
    await build({
      absWorkingDir: frontendRoot,
      entryPoints: [browserAuthClientPath],
      bundle: true,
      format: 'cjs',
      platform: 'node',
      outfile: serverBundlePath,
      external: ['react', 'react-dom', 'react-dom/server'],
      nodePaths: [nodeModulesPath, path.join(repoNodeModulesPath, '.pnpm', 'node_modules')],
      define: { 'process.env.NEXT_PUBLIC_APP_URL': 'undefined' },
    })
  }
  const serverSessionModule = baselineMode
    ? createRequire(serverBundlePath)(serverBundlePath)
    : { useSession: currentUseSession }
  const ServerSessionView = createSessionView(serverSessionModule.useSession)

  writeFileSync(browserEntryPath, browserSource(
    browserAuthClientPath,
    authSyncPath,
    apiClientPath,
  ))
  await build({
    absWorkingDir: frontendRoot,
    entryPoints: [browserEntryPath],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    outfile: browserBundlePath,
    nodePaths: [nodeModulesPath, path.join(repoNodeModulesPath, '.pnpm', 'node_modules')],
    alias: {
      '@': path.join(frontendRoot, 'src'),
      ...(baselineMode ? { '@/lib/auth-client': browserAuthClientPath } : {}),
    },
    define: {
      'process.env.NEXT_PUBLIC_APP_URL': 'undefined',
      'process.env.NEXT_PUBLIC_API_URL': 'window.location.origin',
      'process.env.NODE_ENV': '"production"',
    },
  })

  const serverMarkup = (label: string) => renderToStaticMarkup(React.createElement(ServerSessionView, { label }))
  expect(serverMarkup('early')).toContain('pending')
  expect(serverMarkup('late')).toContain('pending')

  const bundle = readFileSync(browserBundlePath)
  const html = `<!doctype html><html><body>
    <div id="early-root">${serverMarkup('early')}</div>
    <div id="late-root">${serverMarkup('late')}</div>
    <script src="/hydration-client.js"></script>
  </body></html>`
  let sessionRequestCount = 0
  const meAuthorizations: string[] = []
  let releaseRefresh: (() => void) | undefined
  const refreshHeld = new Promise<void>((resolve) => {
    releaseRefresh = resolve
  })
  const server = http.createServer(async (request, response) => {
    if (request.url === '/hydration-client.js') {
      response.writeHead(200, { 'content-type': 'application/javascript' })
      response.end(bundle)
      return
    }
    if (request.url === '/api/auth/get-session') {
      const requestNumber = sessionRequestCount++
      if (requestNumber === 0) {
        response.writeHead(200, { 'content-type': 'application/json' })
        response.end(JSON.stringify({ session: { token: 'fixture-token-1' }, user: { id: 'owner-a' } }))
        return
      }
      if (requestNumber === 1) {
        await refreshHeld
        response.writeHead(200, { 'content-type': 'application/json' })
        response.end(JSON.stringify({ session: { token: 'fixture-token-2' }, user: { id: 'owner-a' } }))
        return
      }
      if (requestNumber === 2) {
        response.writeHead(503, { 'content-type': 'application/json' })
        response.end(JSON.stringify({ error: 'fixture refresh failure' }))
        return
      }
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ session: { token: 'fixture-token-3' }, user: { id: 'owner-a' } }))
      return
    }
    if (request.url === '/me') {
      meAuthorizations.push(String(request.headers.authorization ?? ''))
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ userId: 'owner-a' }))
      return
    }
    response.writeHead(200, { 'content-type': 'text/html' })
    response.end(html)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Hydration fixture server did not bind')

  const unexpectedErrors: string[] = []
  const consoleErrors: string[] = []
  const failedSessionResponses: string[] = []
  page.on('pageerror', (error) => unexpectedErrors.push(error.message))
  page.on('response', (response) => {
    if (response.status() === 503) failedSessionResponses.push(new URL(response.url()).pathname)
  })
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    consoleErrors.push(message.text())
  })
  try {
    await page.goto(`http://127.0.0.1:${address.port}`)
    await page.evaluate(() => (window as unknown as { startHydrationRepro: () => void }).startHydrationRepro())
    await expect(page.locator('[data-session-user="late"]')).toHaveText('owner-a')
    await expect(page.locator('[data-session-token="late"]')).toHaveText('fixture-token-1')
    if (baselineMode) {
      expect(unexpectedErrors.some((message) => /Minified React error #42[3-5]/.test(message))).toBe(true)
      return
    }
    expect(unexpectedErrors).toEqual([])
    expect(consoleErrors).toEqual([])

    const firstMeRequest = page.waitForResponse((response) => new URL(response.url()).pathname === '/me')
    await page.evaluate(() => (window as unknown as { probeApiClientAuth: () => Promise<boolean> }).probeApiClientAuth())
    await firstMeRequest
    expect(meAuthorizations).toEqual(['Bearer fixture-token-1'])

    await page.locator('[data-session-refetch="late"]').click()
    await expect(page.locator('[data-session-state="late"]')).toHaveText('refetching')
    expect(sessionRequestCount).toBe(2)
    releaseRefresh?.()
    await expect(page.locator('[data-session-token="late"]')).toHaveText('fixture-token-2')
    await expect(page.locator('[data-session-state="late"]')).toHaveText('resolved')
    const secondMeRequest = page.waitForResponse((response) => new URL(response.url()).pathname === '/me')
    await page.evaluate(() => (window as unknown as { probeApiClientAuth: () => Promise<boolean> }).probeApiClientAuth())
    await secondMeRequest
    expect(meAuthorizations).toEqual(['Bearer fixture-token-1', 'Bearer fixture-token-2'])

    await page.locator('[data-session-refetch="late"]').click()
    await expect(page.locator('[data-session-state="late"]')).toHaveText('error')
    await expect(page.locator('[data-session-user="late"]')).toHaveText('owner-a')
    await expect(page.locator('[data-session-token="late"]')).toHaveText('fixture-token-2')
    const retainedTokenMeRequest = page.waitForResponse((response) => new URL(response.url()).pathname === '/me')
    await page.evaluate(() => (window as unknown as { probeApiClientAuth: () => Promise<boolean> }).probeApiClientAuth())
    await retainedTokenMeRequest
    expect(meAuthorizations).toEqual(['Bearer fixture-token-1', 'Bearer fixture-token-2', 'Bearer fixture-token-2'])

    await page.locator('[data-session-refetch="late"]').click()
    await expect(page.locator('[data-session-token="late"]')).toHaveText('fixture-token-3')
    await expect(page.locator('[data-session-state="late"]')).toHaveText('resolved')
    expect(unexpectedErrors).toEqual([])
    const thirdMeRequest = page.waitForResponse((response) => new URL(response.url()).pathname === '/me')
    await page.evaluate(() => (window as unknown as { probeApiClientAuth: () => Promise<boolean> }).probeApiClientAuth())
    await thirdMeRequest
    expect(meAuthorizations).toEqual([
      'Bearer fixture-token-1',
      'Bearer fixture-token-2',
      'Bearer fixture-token-2',
      'Bearer fixture-token-3',
    ])
    expect(failedSessionResponses).toEqual(['/api/auth/get-session'])
    expect(consoleErrors).toHaveLength(1)
    expect(consoleErrors[0]).toContain('503 (Service Unavailable)')
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()))
    if (baselineMode) unlinkSync(serverBundlePath)
    rmSync(temporaryDirectory, { recursive: true, force: true })
  }
})
