import { readFile, writeFile, mkdir, chmod, rename, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { homedir } from 'node:os'
import TOML from '@iarna/toml'

export interface LatexyConfig {
  token: string | null
  email: string | null
  userId: string | null
  backendUrl: string
  /** Next.js app origin — Better Auth is mounted there, not on the FastAPI backend. */
  appUrl: string
  defaultResumeId: string | null
  activeModel: string | null
  activeProvider: string | null
}

/** Public service origins used by a fresh CLI install. Local and self-hosted
 * deployments can still override either value through config.toml or env. */
export const DEFAULT_BACKEND_URL =
  'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
export const DEFAULT_APP_URL = 'https://latexy.xyz'

const DEFAULT_CONFIG: LatexyConfig = {
  token: null,
  email: null,
  userId: null,
  backendUrl: DEFAULT_BACKEND_URL,
  appUrl: DEFAULT_APP_URL,
  defaultResumeId: null,
  activeModel: null,
  activeProvider: null,
}

// Env vars win over the persisted config so a stale config.toml cannot pin the CLI to a dead host
function envConfig(): Partial<LatexyConfig> {
  const env: Partial<LatexyConfig> = {}
  const token = process.env['LATEXY_SESSION_TOKEN']
  if (token) env.token = token
  const backendUrl = process.env['LATEXY_API_URL']
  if (backendUrl) env.backendUrl = backendUrl
  const appUrl = process.env['LATEXY_APP_URL']
  if (appUrl) env.appUrl = appUrl
  return env
}

function configDir(): string {
  const xdg = process.env['XDG_CONFIG_HOME']
  const base = xdg ?? join(homedir(), '.config')
  return join(base, 'latexy')
}

function configPath(): string {
  return join(configDir(), 'config.toml')
}

/** On-disk config only, no env overlay — writeConfig() uses this so ephemeral env values
 *  (LATEXY_API_URL/LATEXY_APP_URL) are never baked permanently into config.toml. */
async function readDiskConfig(): Promise<LatexyConfig> {
  let raw: string
  try {
    raw = await readFile(configPath(), 'utf-8')
  } catch {
    // No config yet — a first run, not a problem.
    return { ...DEFAULT_CONFIG }
  }

  try {
    const parsed = TOML.parse(raw) as Partial<LatexyConfig>
    return { ...DEFAULT_CONFIG, ...parsed }
  } catch (err) {
    // A config that exists but will not parse is different from having none:
    // falling back to defaults silently presents as being logged out, with
    // nothing to explain why. Say so, and leave the bad file in place rather
    // than overwriting the only copy of whatever is in it.
    process.stderr.write(
      `latexy: ${configPath()} could not be parsed (${String(err)}). ` +
        'Continuing with defaults — you will need to sign in again. ' +
        'Move or delete the file to silence this.\n',
    )
    return { ...DEFAULT_CONFIG }
  }
}

export async function readConfig(): Promise<LatexyConfig> {
  return { ...(await readDiskConfig()), ...envConfig() }
}

export async function writeConfig(patch: Partial<LatexyConfig>): Promise<void> {
  // 0o700: the token file itself is 0600, but the directory was being created
  // with the ambient umask (0755 by default), which is world-traversable.
  await mkdir(configDir(), { recursive: true, mode: 0o700 })
  const current = await readDiskConfig()
  const next = { ...current, ...patch }
  // @iarna/toml does not support null — strip null fields before serialising
  const toWrite = Object.fromEntries(Object.entries(next).filter(([, v]) => v !== null))
  const toml = TOML.stringify(toWrite as TOML.JsonMap)

  // Write-then-rename. writeFile() truncates first, so an interruption between
  // truncate and write left a half-written config that readDiskConfig could not
  // parse — which presents to the user as being mysteriously logged out. rename()
  // is atomic on POSIX, so a reader sees either the old file or the new one.
  const target = configPath()
  const tmp = `${target}.${process.pid}.tmp`
  try {
    await writeFile(tmp, toml, { encoding: 'utf-8', mode: 0o600 })
    await chmod(tmp, 0o600)
    await rename(tmp, target)
  } catch (err) {
    await rm(tmp, { force: true }).catch(() => {})
    throw err
  }
}

export async function clearConfig(): Promise<void> {
  await writeConfig({ token: null, email: null, userId: null })
}
