import { readFile, writeFile, mkdir, chmod } from 'node:fs/promises'
import { join } from 'node:path'
import { homedir } from 'node:os'
import TOML from '@iarna/toml'

export interface LatexyConfig {
  token: string | null
  email: string | null
  userId: string | null
  backendUrl: string
  defaultResumeId: string | null
  activeModel: string | null
  activeProvider: string | null
}

const DEFAULT_CONFIG: LatexyConfig = {
  token: null,
  email: null,
  userId: null,
  backendUrl: process.env['LATEXY_API_URL'] ?? 'http://localhost:8030',
  defaultResumeId: null,
  activeModel: null,
  activeProvider: null,
}

function configDir(): string {
  const xdg = process.env['XDG_CONFIG_HOME']
  const base = xdg ?? join(homedir(), '.config')
  return join(base, 'latexy')
}

function configPath(): string {
  return join(configDir(), 'config.toml')
}

export async function readConfig(): Promise<LatexyConfig> {
  const envToken = process.env['LATEXY_SESSION_TOKEN'] ?? null
  try {
    const raw = await readFile(configPath(), 'utf-8')
    const parsed = TOML.parse(raw) as Partial<LatexyConfig>
    return { ...DEFAULT_CONFIG, ...parsed, ...(envToken ? { token: envToken } : {}) }
  } catch {
    return { ...DEFAULT_CONFIG, ...(envToken ? { token: envToken } : {}) }
  }
}

export async function writeConfig(patch: Partial<LatexyConfig>): Promise<void> {
  await mkdir(configDir(), { recursive: true })
  const current = await readConfig()
  const next = { ...current, ...patch }
  const toml = TOML.stringify(next as TOML.JsonMap)
  await writeFile(configPath(), toml, { encoding: 'utf-8', mode: 0o600 })
  await chmod(configPath(), 0o600)
}

export async function clearConfig(): Promise<void> {
  await writeConfig({ token: null, email: null, userId: null })
}
