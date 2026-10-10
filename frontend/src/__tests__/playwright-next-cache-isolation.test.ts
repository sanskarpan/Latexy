import { readFileSync } from 'node:fs'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawn } from 'node:child_process'
import { describe, expect, it } from 'vitest'

// The lifecycle helpers are JavaScript-only because the launcher is executed
// directly by Playwright's webServer command.
import {
  assertProductionNode,
  copyStandaloneAssets,
  inheritedEnvironment,
  prepareRuntimeAssets,
  readMode,
  serverEnvironment,
  shouldCopy,
  signalProcessTree,
  standaloneEntrypoint,
} from '../../scripts/playwright-server.mjs'

const NEXT_CONFIG = readFileSync(new URL('../../next.config.js', import.meta.url), 'utf8')
const PLAYWRIGHT_CONFIG = readFileSync(new URL('../../playwright.config.ts', import.meta.url), 'utf8')
const QUALITY_CONFIG = readFileSync(new URL('../../playwright.quality.config.ts', import.meta.url), 'utf8')
const SERVER_SCRIPT = readFileSync(new URL('../../scripts/playwright-server.mjs', import.meta.url), 'utf8')
const FULL_STACK_SMOKE = readFileSync(new URL('../../../scripts/ci/full-stack-smoke.sh', import.meta.url), 'utf8')

describe('Playwright Next cache isolation', () => {
  it('keeps concurrent local and browser-test servers in separate generated trees', () => {
    expect(NEXT_CONFIG).not.toContain('port-specific directory')
    expect(SERVER_SCRIPT).toContain("mkdtemp(join(repositoryRoot, '.playwright-e2e-'))")
    expect(SERVER_SCRIPT).toContain('cwd: runtimeRoot')
    expect(PLAYWRIGHT_CONFIG).toContain('node scripts/playwright-server.mjs --port ${PORT}')
    expect(PLAYWRIGHT_CONFIG).toContain("process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === '1'")
    expect(PLAYWRIGHT_CONFIG).toContain('reuseExistingServer')
    expect(PLAYWRIGHT_CONFIG).toContain('workers: 1')
  })

  it('launches the configured server mode from a disposable copy without copying secrets', () => {
    expect(readMode([])).toBe('development')
    expect(readMode(['--mode', 'production'])).toBe('production')
    expect(() => assertProductionNode('production', '23.1.0')).toThrow(/Node 22/)
    expect(() => assertProductionNode('production', '22.23.2')).not.toThrow()
    expect(SERVER_SCRIPT).toContain("mode === 'production'")
    expect(SERVER_SCRIPT).not.toContain("[nextCli, 'start'")
    expect(SERVER_SCRIPT).toContain('did not emit a standalone server entrypoint')
    expect(SERVER_SCRIPT).toContain('spawn(process.execPath, [nextCli, \'build\']')
    expect(SERVER_SCRIPT).toContain("NEXT_TELEMETRY_DISABLED: '1'")
    expect(SERVER_SCRIPT).toContain("NEXT_PUBLIC_PLAYWRIGHT_TEST: '1'")
    expect(SERVER_SCRIPT).toContain("name.startsWith('.env')")
    expect(SERVER_SCRIPT).toContain("process.once('SIGINT'")
    expect(SERVER_SCRIPT).toContain("process.once('SIGTERM'")
    expect(SERVER_SCRIPT).toContain('detached: process.platform !== \'win32\'')
    expect(SERVER_SCRIPT).toContain('process.kill(-child.pid, signal)')
    expect(SERVER_SCRIPT).toContain('taskkill')
    expect(SERVER_SCRIPT).toContain('watchParent')
    expect(SERVER_SCRIPT).toContain('waitForChildExit(5_000)')
    expect(SERVER_SCRIPT).toContain("signalProcessTree(child, 'SIGKILL')")
    expect(SERVER_SCRIPT).toContain("await rm(runtimeRoot, { recursive: true, force: true })")
    expect(SERVER_SCRIPT).toContain('DATABASE_URL')
    expect(SERVER_SCRIPT).toContain('BETTER_AUTH_SECRET')
    expect(SERVER_SCRIPT).toContain('NEXT_PUBLIC_API_URL')
    expect(SERVER_SCRIPT).toContain('BACKEND_URL')
    expect(SERVER_SCRIPT).toContain('port + 2000')
    expect(SERVER_SCRIPT).toContain('BETTER_AUTH_URL')
    expect(QUALITY_CONFIG).toContain('ws://127.0.0.1:${PORT + 1000}')
    expect(QUALITY_CONFIG).toContain('node scripts/playwright-server.mjs --port ${PORT}')
    expect(PLAYWRIGHT_CONFIG).toContain("gracefulShutdown: { signal: 'SIGTERM'")
    expect(QUALITY_CONFIG).toContain("gracefulShutdown: { signal: 'SIGTERM'")
    expect(PLAYWRIGHT_CONFIG).toContain("const testTimeout = serverMode === 'production' ? 120_000 : 900_000")
    expect(PLAYWRIGHT_CONFIG).toContain("const navigationTimeout = serverMode === 'production' ? 60_000 : 900_000")
    expect(PLAYWRIGHT_CONFIG).toContain('actionTimeout: 12_000')
    expect(PLAYWRIGHT_CONFIG).toContain('navigationTimeout,')
    expect(PLAYWRIGHT_CONFIG).toContain('expect: { timeout: 12_000 }')
    expect(QUALITY_CONFIG).toContain("process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === '1'")
    expect(FULL_STACK_SMOKE).toContain('PLAYWRIGHT_REUSE_EXISTING_SERVER=1')
    expect(FULL_STACK_SMOKE).toContain('PLAYWRIGHT_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"')
    expect(FULL_STACK_SMOKE).toContain('PLAYWRIGHT_API_URL="http://127.0.0.1:${BACKEND_PORT}"')
  })

  it('checks cross-browser PDFs in the production bundle with bounded interactions', () => {
    expect(QUALITY_CONFIG).toContain('node scripts/playwright-server.mjs --port ${PORT} --mode production')
    expect(QUALITY_CONFIG).toContain('actionTimeout: 12_000')
    expect(QUALITY_CONFIG).toContain('timeout: 1_800_000')
    expect(QUALITY_CONFIG).toContain("serviceWorkers: 'block'")
    expect(PLAYWRIGHT_CONFIG).not.toContain("serviceWorkers: 'block'")
    expect(NEXT_CONFIG).toContain("disable: process.env.NODE_ENV === 'development'")
  })

  it('does not inherit ambient credentials into the disposable server', () => {
    const pathKeys = process.platform === 'win32' ? ['PATH'] : ['PATH', 'Path']
    const keys = [
      'SUPABASE_SERVICE_ROLE_KEY',
      'OPENAI_API_KEY',
      'GITHUB_CLIENT_SECRET',
      'MINIO_ACCESS_KEY',
      'AWS_ACCESS_KEY_ID',
      'REDIS_URL',
      'HTTPS_PROXY',
      'HTTP_PROXY',
      'PLAYWRIGHT_DATABASE_URL',
      'PLAYWRIGHT_BETTER_AUTH_SECRET',
      ...pathKeys,
      'SystemRoot',
      'SYSTEMROOT',
      'ComSpec',
      'COMSPEC',
      'USERPROFILE',
      'npm_Config_User_Agent',
    ]
    const userAgentKeys = Object.keys(process.env).filter(
      (key) => key.toLowerCase() === 'npm_config_user_agent',
    )
    keys.push(...userAgentKeys)
    const previous = new Map([...new Set(keys)].map((key) => [key, process.env[key]]))
    try {
      process.env.SUPABASE_SERVICE_ROLE_KEY = 'production-service-role'
      process.env.OPENAI_API_KEY = 'production-openai-key'
      process.env.GITHUB_CLIENT_SECRET = 'production-oauth-secret'
      process.env.MINIO_ACCESS_KEY = 'production-minio-key'
      process.env.AWS_ACCESS_KEY_ID = 'production-aws-key'
      process.env.REDIS_URL = 'redis://:production-password@example.test:6379/0'
      process.env.HTTPS_PROXY = 'https://proxy-user:proxy-password@example.test:8443'
      process.env.HTTP_PROXY = 'http://proxy-user:proxy-password@example.test:8080'
      process.env.PLAYWRIGHT_DATABASE_URL = 'postgresql://test.example/isolated'
      process.env.PLAYWRIGHT_BETTER_AUTH_SECRET = 'playwright-secret-override'
      process.env.PATH = '/test/bin'
      if (process.platform !== 'win32') process.env.Path = 'C:\\Windows\\System32'
      process.env.SystemRoot = 'C:\\Windows'
      process.env.SYSTEMROOT = 'C:\\Windows'
      process.env.ComSpec = 'C:\\Windows\\System32\\cmd.exe'
      process.env.COMSPEC = 'C:\\Windows\\System32\\cmd.exe'
      process.env.USERPROFILE = 'C:\\Users\\playwright'
      // POSIX env keys are case-sensitive, so avoid inheriting a second
      // ambient spelling of this allowlisted variable in Linux CI.
      for (const key of userAgentKeys) delete process.env[key]
      process.env.npm_Config_User_Agent = 'npm/10 node/v22'

      const inherited = inheritedEnvironment()
      const environment = serverEnvironment(5181)

      expect(inherited.SUPABASE_SERVICE_ROLE_KEY).toBeUndefined()
      expect(inherited.OPENAI_API_KEY).toBeUndefined()
      expect(inherited.GITHUB_CLIENT_SECRET).toBeUndefined()
      expect(inherited.MINIO_ACCESS_KEY).toBeUndefined()
      expect(inherited.AWS_ACCESS_KEY_ID).toBeUndefined()
      expect(inherited.REDIS_URL).toBeUndefined()
      expect(inherited.HTTPS_PROXY).toBeUndefined()
      expect(inherited.HTTP_PROXY).toBeUndefined()
      const getEnvironmentValue = (environment: Record<string, string | undefined>, name: string) =>
        Object.entries(environment).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1]
      expect(getEnvironmentValue(inherited, 'PATH')).toBe('/test/bin')
      if (process.platform !== 'win32') {
        expect(inherited.Path).toBe('C:\\Windows\\System32')
      }
      expect(getEnvironmentValue(inherited, 'SystemRoot')).toBe('C:\\Windows')
      expect(getEnvironmentValue(inherited, 'ComSpec')).toBe('C:\\Windows\\System32\\cmd.exe')
      expect(inherited.USERPROFILE).toBe('C:\\Users\\playwright')
      expect(getEnvironmentValue(inherited, 'npm_Config_User_Agent')).toBe('npm/10 node/v22')
      expect(environment.DATABASE_URL).toBe('postgresql://test.example/isolated')
      expect(environment.BETTER_AUTH_SECRET).toBe('playwright-secret-override')
    } finally {
      for (const [key, value] of previous) {
        if (value === undefined) delete process.env[key]
        else process.env[key] = value
      }
    }
  })

  it('resolves the standalone entry nested under the disposable runtime basename', async () => {
    const runtimeRoot = await mkdtemp(join(tmpdir(), '.playwright-e2e-'))
    const entrypoint = join(
      runtimeRoot,
      '.next',
      'standalone',
      basename(runtimeRoot),
      'server.js',
    )
    try {
      await mkdir(join(entrypoint, '..'), { recursive: true })
      await writeFile(entrypoint, '// test server')
      expect(standaloneEntrypoint(runtimeRoot)).toBe(entrypoint)
    } finally {
      await rm(runtimeRoot, { recursive: true, force: true })
    }
  })

  it('copies public and static assets beside the standalone server', async () => {
    const runtimeRoot = await mkdtemp(join(tmpdir(), '.playwright-e2e-'))
    const serverPath = join(runtimeRoot, '.next', 'standalone', 'server.js')
    try {
      await mkdir(join(runtimeRoot, 'public'), { recursive: true })
      await mkdir(join(runtimeRoot, '.next', 'static', 'chunks'), { recursive: true })
      await mkdir(join(runtimeRoot, '.next', 'standalone'), { recursive: true })
      await writeFile(join(runtimeRoot, 'public', 'manifest.json'), '{}')
      await writeFile(join(runtimeRoot, '.next', 'static', 'chunks', 'app.js'), 'app')
      await writeFile(serverPath, '// test server')

      await copyStandaloneAssets(runtimeRoot, serverPath)

      await expect(stat(join(runtimeRoot, '.next', 'standalone', 'public', 'manifest.json'))).resolves.toBeTruthy()
      await expect(stat(join(runtimeRoot, '.next', 'standalone', '.next', 'static', 'chunks', 'app.js'))).resolves.toBeTruthy()
    } finally {
      await rm(runtimeRoot, { recursive: true, force: true })
    }
  })

  it('prepares generated assets inside the disposable runtime with sanitized environment', async () => {
    expect(shouldCopy('public/monaco/vs/loader.js')).toBe(false)
    const runtimeRoot = await mkdtemp(join(tmpdir(), '.playwright-e2e-'))
    const marker = join(runtimeRoot, 'prepare-env')
    const previousSecret = process.env.SUPABASE_SERVICE_ROLE_KEY
    try {
      await mkdir(join(runtimeRoot, 'scripts'), { recursive: true })
      await writeFile(
        join(runtimeRoot, 'scripts', 'prepare-monaco.mjs'),
        [
          "import { mkdir, writeFile } from 'node:fs/promises'",
          "import { join } from 'node:path'",
          `const root = ${JSON.stringify(runtimeRoot)}`,
          "await mkdir(join(root, 'public', 'monaco', 'vs'), { recursive: true })",
          "await writeFile(join(root, 'public', 'monaco', 'vs', 'loader.js'), 'loader')",
          `await writeFile(${JSON.stringify(marker)}, process.env.SUPABASE_SERVICE_ROLE_KEY ?? '')`,
        ].join('\n'),
      )
      process.env.SUPABASE_SERVICE_ROLE_KEY = 'must-not-reach-runtime'

      prepareRuntimeAssets(runtimeRoot)

      await expect(stat(join(runtimeRoot, 'public', 'monaco', 'vs', 'loader.js'))).resolves.toBeTruthy()
      await expect(readFile(marker, 'utf8')).resolves.toBe('')
    } finally {
      if (previousSecret === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY
      else process.env.SUPABASE_SERVICE_ROLE_KEY = previousSecret
      await rm(runtimeRoot, { recursive: true, force: true })
    }
  })

  it('terminates a disposable server process group, including descendants', async () => {
    if (process.platform === 'win32') return

    const root = await mkdtemp(join(tmpdir(), 'latexy-playwright-lifecycle-'))
    const marker = join(root, 'descendant-stopped')
    const pidFile = join(root, 'descendant-pid')
    const readyFile = join(root, 'descendant-ready')
    const descendantCode = [
      "const fs = require('node:fs')",
      'const [marker, readyFile] = process.argv.slice(1)',
      "fs.writeFileSync(readyFile, 'ready')",
      "process.on('SIGTERM', () => { fs.writeFileSync(marker, 'stopped'); process.exit(0) })",
      'setInterval(() => {}, 1000)',
    ].join(';')
    const launcherCode = [
      "const { spawn } = require('node:child_process')",
      'const [descendantCode, marker, pidFile, readyFile] = process.argv.slice(1)',
      "const child = spawn(process.execPath, ['-e', descendantCode, marker, readyFile], { stdio: 'ignore' })",
      "require('node:fs').writeFileSync(pidFile, String(child.pid))",
      'setInterval(() => {}, 1000)',
    ].join(';')
    const launcher = spawn(process.execPath, ['-e', launcherCode, descendantCode, marker, pidFile, readyFile], {
      detached: true,
      stdio: 'ignore',
    })

    try {
      await expect
        .poll(async () => readFile(pidFile, 'utf8').catch(() => ''), { timeout: 2_000 })
        .not.toBe('')
      await expect
        .poll(async () => readFile(readyFile, 'utf8').catch(() => ''), { timeout: 2_000 })
        .toBe('ready')
      signalProcessTree(launcher, 'SIGTERM')
      await expect
        .poll(async () => readFile(marker, 'utf8').catch(() => ''), { timeout: 5_000 })
        .toBe('stopped')
    } finally {
      signalProcessTree(launcher, 'SIGKILL')
      await rm(root, { recursive: true, force: true })
    }
  }, 10_000)

  it('runs cleanup when its direct launcher disappears', async () => {
    // Windows does not consistently reparent child processes or expose the
    // parent PID's liveness after exit, so this POSIX process-lifecycle check
    // cannot be asserted there.
    if (process.platform === 'win32') return

    const root = await mkdtemp(join(tmpdir(), 'latexy-playwright-parent-'))
    const marker = join(root, 'parent-gone')
    const ready = join(root, 'monitor-ready')
    const launcherModule = pathToFileURL(
      join(process.cwd(), 'scripts', 'playwright-server.mjs'),
    ).href
    const monitoredCode = [
      "import { writeFileSync } from 'node:fs'",
      'const [launcherModule, marker, ready] = process.argv.slice(1)',
      'const { watchParent } = await import(launcherModule)',
      "watchParent(() => { writeFileSync(marker, 'gone'); process.exit(0) })",
      "writeFileSync(ready, 'ready')",
      'setInterval(() => {}, 1000)',
    ].join(';')
    const parentCode = [
      "const { spawn } = require('node:child_process')",
      'const [monitoredCode, launcherModule, marker, ready] = process.argv.slice(1)',
      "spawn(process.execPath, ['--input-type=module', '-e', monitoredCode, launcherModule, marker, ready], { stdio: 'ignore', detached: process.platform === 'win32', windowsHide: true })",
      "setInterval(() => { if (require('node:fs').existsSync(ready)) process.exit(0) }, 25)",
    ].join(';')
    const parent = spawn(process.execPath, ['-e', parentCode, monitoredCode, launcherModule, marker, ready], {
      detached: true,
      stdio: 'ignore',
    })

    try {
      // Exit only after the descendant has actually installed its monitor.
      // Cold module imports need not finish within an arbitrary 500 ms.
      await expect
        .poll(async () => readFile(ready, 'utf8').catch(() => ''), { timeout: 5_000 })
        .toBe('ready')
      await expect
        .poll(async () => readFile(marker, 'utf8').catch(() => ''), { timeout: 5_000 })
        .toBe('gone')
    } finally {
      signalProcessTree(parent, 'SIGKILL')
      await rm(root, { recursive: true, force: true })
    }
  }, 10_000)
})
