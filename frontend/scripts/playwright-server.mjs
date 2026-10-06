#!/usr/bin/env node

import { cp, mkdtemp, rm, symlink } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const repositoryRoot = dirname(frontendRoot)
const nextCli = join(frontendRoot, 'node_modules', 'next', 'dist', 'bin', 'next')

const PARENT_POLL_INTERVAL_MS = 250
const inheritedRuntimeEnvironmentKeys = new Set([
  // POSIX and Windows process/runtime essentials.
  'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'TMP', 'TEMP',
  'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'APPDATA', 'LOCALAPPDATA',
  'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
  // Locale, terminal, CI, and color settings used by Node/tool output.
  'LANG', 'LANGUAGE', 'TERM', 'COLORTERM', 'TERM_PROGRAM', 'TERM_PROGRAM_VERSION',
  'CI', 'FORCE_COLOR', 'NO_COLOR',
  // Non-secret package-manager metadata needed by child tooling.
  'NPM_CONFIG_USER_AGENT', 'NPM_CONFIG_NODE_GYP', 'NPM_CONFIG_PREFIX',
  'NPM_EXECPATH', 'NPM_LIFECYCLE_EVENT', 'NPM_COMMAND', 'COREPACK_HOME', 'PNPM_HOME',
])

function inheritedEnvironment() {
  return Object.fromEntries(
    Object.entries(process.env).filter(([key]) => {
      const normalizedKey = key.toUpperCase()
      return inheritedRuntimeEnvironmentKeys.has(normalizedKey) || normalizedKey.startsWith('LC_')
    }),
  )
}

function watchParent(onParentGone) {
  const expectedParentPid = process.ppid
  // A process already reparented to init/launchd has no useful owner to
  // monitor. process.ppid is cheap and works on every supported platform.
  if (!expectedParentPid || expectedParentPid === 1) return () => {}

  let stopped = false
  const timer = setInterval(() => {
    if (stopped) return
    if (process.ppid !== expectedParentPid) {
      stopped = true
      clearInterval(timer)
      onParentGone()
    }
  }, PARENT_POLL_INTERVAL_MS)
  timer.unref()
  return () => {
    stopped = true
    clearInterval(timer)
  }
}

function signalProcessTree(child, signal) {
  if (!child?.pid || child.exitCode !== null) return

  if (process.platform === 'win32') {
    if (signal === 'SIGKILL') {
      spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
        stdio: 'ignore',
        windowsHide: true,
      })
    } else {
      // Windows has no POSIX signal groups. A normal kill gives the child a
      // chance to exit; cleanup's SIGKILL phase uses taskkill /T /F below.
      try {
        child.kill(signal)
      } catch {
        // The child may have exited between the exitCode check and kill.
      }
    }
    return
  }

  try {
    // detached:true gives Next its own process group, so this reaches all of
    // its workers/watchers rather than just the direct child.
    process.kill(-child.pid, signal)
  } catch {
    // If the process group disappeared first, the direct child can still be
    // alive briefly. Attempt a direct kill for that race; ignore an already
    // exited child so cleanup never turns into an uncaught exception.
    try {
      child.kill(signal)
    } catch {
      // Ignore already-exited/permission races during shutdown.
    }
  }
}

function readPort(argv) {
  const flagIndex = argv.indexOf('--port')
  const value = flagIndex >= 0 ? argv[flagIndex + 1] : process.env.PLAYWRIGHT_PORT
  const port = Number.parseInt(value ?? '5181', 10)
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`Invalid Playwright server port: ${value}`)
  }
  return port
}

function readMode(argv) {
  const flagIndex = argv.indexOf('--mode')
  const value = flagIndex >= 0 ? argv[flagIndex + 1] : process.env.PLAYWRIGHT_SERVER_MODE
  const mode = value ?? 'development'
  if (mode !== 'development' && mode !== 'production') {
    throw new Error(`Invalid Playwright server mode: ${mode}`)
  }
  return mode
}

function assertProductionNode(mode, version = process.versions.node) {
  if (mode !== 'production') return
  const major = Number.parseInt(version.split('.')[0], 10)
  if (major !== 22) {
    throw new Error(
      `Production Playwright server mode requires Node 22.x; received ${version}. ` +
      'Use `mise exec node@22 -- pnpm test`.',
    )
  }
}

function shouldCopy(relativePath) {
  const parts = relativePath.split('/')
  const name = parts.at(-1) ?? ''
  if (parts.some((part) => part === 'node_modules' || part === '.git')) return false
  if (parts.some((part) => part === '.next' || part.startsWith('.next-'))) return false
  if (name.startsWith('.env')) return false
  if (name === 'tsconfig.tsbuildinfo') return false
  if (parts[0] === 'test-results' || parts[0].startsWith('playwright-report')) return false
  return true
}

async function copyFrontend(runtimeRoot) {
  await cp(frontendRoot, runtimeRoot, {
    recursive: true,
    filter(source) {
      const relativePath = source.slice(frontendRoot.length + 1).replaceAll('\\', '/')
      return relativePath === '' || shouldCopy(relativePath)
    },
  })

  const runtimeNodeModules = join(runtimeRoot, 'node_modules')
  if (!existsSync(join(frontendRoot, 'node_modules'))) {
    throw new Error(`Missing frontend dependencies at ${join(frontendRoot, 'node_modules')}`)
  }
  await symlink(join(frontendRoot, 'node_modules'), runtimeNodeModules, 'dir')
}

async function copyStandaloneAssets(runtimeRoot, serverPath) {
  const standaloneRoot = dirname(serverPath)
  for (const [source, destination] of [
    [join(runtimeRoot, 'public'), join(standaloneRoot, 'public')],
    [join(runtimeRoot, '.next', 'static'), join(standaloneRoot, '.next', 'static')],
  ]) {
    if (existsSync(source)) {
      await cp(source, destination, { recursive: true, force: true })
    }
  }
}

function serverEnvironment(port, mode = 'development') {
  const appUrl = `http://localhost:${port}`
  // Browser tests mock API traffic by default. Keep accidental unmocked calls
  // away from the live local backend; full-stack smoke passes this explicitly.
  const backendUrl =
    process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${port + 2000}`
  const trustedOrigins = new Set(
    (process.env.BETTER_AUTH_TRUSTED_ORIGINS ?? '')
      .split(',')
      .map((origin) => origin.trim())
      .filter(Boolean),
  )
  if (mode === 'production') trustedOrigins.add(appUrl)
  return {
    ...inheritedEnvironment(),
    NODE_ENV: mode,
    PORT: String(port),
    HOSTNAME: '127.0.0.1',
    NEXT_DIST_DIR: '.next',
    NEXT_PUBLIC_APP_URL: process.env.PLAYWRIGHT_APP_URL ?? appUrl,
    // The production auth module intentionally rejects an HTTP origin for
    // passkeys. The local Next listener is still plain HTTP, but using an
    // HTTPS origin here lets production builds collect the auth route while
    // browser tests continue to target `baseURL` over HTTP.
    BETTER_AUTH_URL:
      process.env.PLAYWRIGHT_AUTH_URL ??
      (mode === 'production' ? `https://localhost:${port}` : appUrl),
    NEXT_PUBLIC_API_URL: process.env.PLAYWRIGHT_API_URL ?? backendUrl,
    NEXT_PUBLIC_API_BASE_URL: process.env.PLAYWRIGHT_API_URL ?? backendUrl,
    BACKEND_URL: backendUrl,
    NEXT_PUBLIC_WS_URL:
      process.env.NEXT_PUBLIC_WS_URL ?? `ws://127.0.0.1:${port + 1000}`,
    NEXT_TELEMETRY_DISABLED: '1',
    // This launcher builds a disposable, local-only bundle. Some browser
    // contracts need Monaco's test hook, which normal production bundles omit.
    NEXT_PUBLIC_PLAYWRIGHT_TEST: '1',
    DATABASE_URL:
      process.env.PLAYWRIGHT_DATABASE_URL ??
      'postgresql://latexy:latexy_password@127.0.0.1:5434/latexy_test',
    BETTER_AUTH_SECRET:
      process.env.PLAYWRIGHT_BETTER_AUTH_SECRET ??
      'playwright-local-secret-with-at-least-32-characters',
    ...(trustedOrigins.size > 0
      ? { BETTER_AUTH_TRUSTED_ORIGINS: [...trustedOrigins].join(',') }
      : {}),
  }
}

function standaloneEntrypoint(runtimeRoot) {
  const standaloneRoot = join(runtimeRoot, '.next', 'standalone')
  // With outputFileTracingRoot set to the repository root, Next preserves the
  // disposable application's basename inside the standalone tree. The name is
  // intentionally random, so it cannot be represented by a static candidate.
  const candidates = [
    join(standaloneRoot, 'server.js'),
    join(standaloneRoot, 'frontend', 'server.js'),
    join(standaloneRoot, basename(runtimeRoot), 'server.js'),
  ]
  return candidates.find((candidate) => existsSync(candidate))
}

async function main() {
  const argv = process.argv.slice(2)
  const port = readPort(argv)
  const mode = readMode(argv)
  assertProductionNode(mode)
  const runtimeRoot = await mkdtemp(join(repositoryRoot, '.playwright-e2e-'))
  let child
  let stopping = false
  let stopParentWatch = () => {}
  let copyComplete = false
  let parentGone = false

  const cleanup = async (exitCode) => {
    if (stopping) return
    stopping = true
    const waitForChildExit = async (timeoutMs) => {
      if (!child || child.exitCode !== null) return
      await new Promise((resolve) => {
        let settled = false
        const finish = () => {
          if (settled) return
          settled = true
          clearTimeout(timer)
          child.off('exit', finish)
          resolve()
        }
        const timer = setTimeout(finish, timeoutMs)
        child.once('exit', finish)
      })
    }

    if (child && child.exitCode === null) {
      signalProcessTree(child, 'SIGTERM')
      await waitForChildExit(5_000)
    }
    if (child && child.exitCode === null) {
      signalProcessTree(child, 'SIGKILL')
      await waitForChildExit(1_000)
    }
    stopParentWatch()
    await rm(runtimeRoot, { recursive: true, force: true })
    if (exitCode !== undefined) process.exit(exitCode)
  }

  const stop = (signal) => {
    void cleanup(128 + (signal === 'SIGINT' ? 2 : 15))
  }
  process.once('SIGINT', () => stop('SIGINT'))
  process.once('SIGTERM', () => stop('SIGTERM'))
  stopParentWatch = watchParent(() => {
    parentGone = true
    if (copyComplete) void cleanup(1)
  })

  try {
    await copyFrontend(runtimeRoot)
    copyComplete = true
    if (parentGone) {
      await cleanup(1)
      return
    }
    const startNext = async () => {
      const standalone = mode === 'production' ? standaloneEntrypoint(runtimeRoot) : undefined
      if (mode === 'production' && !standalone) {
        throw new Error('Next production build did not emit a standalone server entrypoint')
      }
      if (standalone) await copyStandaloneAssets(runtimeRoot, standalone)
      if (stopping) return
      // `output: standalone` intentionally does not support `next start`; use
      // the traced server and fail explicitly if its layout changes.
      const nextArgs = mode === 'production'
        ? [standalone]
        : [nextCli, 'dev', '--port', String(port)]
      child = spawn(process.execPath, nextArgs, {
        cwd: runtimeRoot,
        env: serverEnvironment(port, mode),
        stdio: 'inherit',
        detached: process.platform !== 'win32',
      })
      child.once('error', async (error) => {
        console.error(`[playwright-server] ${error.message}`)
        await cleanup(1)
      })
      child.once('exit', async (code, signal) => {
        if (stopping) return
        await cleanup(code ?? (signal ? 1 : 0))
      })
    }

    if (mode === 'production') {
      console.error('[playwright-server] Building isolated production bundle')
      // The repository `pnpm build` command also validates the standalone
      // server layout. That layout is an image-packaging concern and can be
      // incomplete when Next traces through the disposable node_modules
      // symlink, even though the normal `.next` output needed by `next start`
      // is complete. Build the exact Next artifact directly for this harness;
      // CI's regular frontend-build job still runs the full validation.
      child = spawn(process.execPath, [nextCli, 'build'], {
        cwd: runtimeRoot,
        env: serverEnvironment(port, mode),
        stdio: 'inherit',
        detached: process.platform !== 'win32',
      })
      child.once('error', async (error) => {
        console.error(`[playwright-server] ${error.message}`)
        await cleanup(1)
      })
      child.once('exit', async (code, signal) => {
        if (stopping) return
        if (code !== 0 || signal) {
          await cleanup(code ?? 1)
          return
        }
        child = undefined
        try {
          await startNext()
        } catch (error) {
          console.error(`[playwright-server] ${error instanceof Error ? error.message : error}`)
          await cleanup(1)
        }
      })
    } else {
      await startNext()
    }
  } catch (error) {
    console.error(`[playwright-server] ${error instanceof Error ? error.message : error}`)
    await cleanup(1)
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main()
}

export {
  readPort,
  serverEnvironment,
  readMode,
  assertProductionNode,
  shouldCopy,
  signalProcessTree,
  standaloneEntrypoint,
  copyStandaloneAssets,
  inheritedEnvironment,
  watchParent,
}
