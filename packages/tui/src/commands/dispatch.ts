import React from 'react'
import { parseSlashCommand } from './parser.js'
import { COMMAND_MAP, IMPLEMENTED_COMMANDS } from './registry.js'
import { addMessage, $activeJobId, clearMessages } from '../stores/messages.js'
import { openOverlay, closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'
import { writeConfig, clearConfig } from '../lib/config.js'
import { wsClient } from '../lib/ws-client.js'

// Lazy imports to avoid circular deps at module load
async function getLoginOverlay(): Promise<React.ReactElement> {
  const { LoginOverlay } = await import('../components/overlays/LoginOverlay.js')
  return React.createElement(LoginOverlay)
}

async function getResumePicker(): Promise<React.ReactElement> {
  const { ResumePicker } = await import('../components/overlays/ResumePicker.js')
  return React.createElement(ResumePicker)
}

// Tier 1: local handlers (no API call, just UI changes)
const LOCAL_HANDLERS: Record<string, (parsed: ReturnType<typeof parseSlashCommand>) => Promise<void>> = {
  list: async () => {
    openOverlay(await getResumePicker())
  },
  clear: async () => {
    clearMessages()
  },
  help: async (p) => {
    const cmdName = p?.positional[0]
    const cmd = cmdName ? COMMAND_MAP.get(cmdName) : null
    addMessage({
      role: 'system',
      content: cmd
        ? cmd.implemented
          ? `/${cmd.name} — ${cmd.description}\nUsage: ${cmd.usage}`
          : `/${cmd.name} — ${cmd.description}\nUsage: ${cmd.usage}\n\nNot implemented yet — this command is planned but has no handler, so running it will not do anything.`
        : `Available commands:\n${IMPLEMENTED_COMMANDS.map(c => `  /${c.name.padEnd(10)} ${c.description}`).join('\n')}`,
    })
  },
  logout: async () => {
    await clearConfig()
    const session = $session.get()
    $session.set({ ...session, token: null, isAuthenticated: false, email: null, plan: null, userId: null })
    wsClient.destroy()
    addMessage({ role: 'system', content: 'Logged out successfully.' })
    openOverlay(await getLoginOverlay())
  },
}

// Tier 2: API handlers (REST calls, job submission)
const API_HANDLERS: Record<string, (parsed: NonNullable<ReturnType<typeof parseSlashCommand>>) => Promise<void>> = {
  // Resume lifecycle
  new:        async p => (await import('../tools/resume-commands.js')).runNew(p),
  edit:       async p => (await import('../tools/resume-commands.js')).runEdit(p),
  fork:       async p => (await import('../tools/resume-commands.js')).runFork(p),
  diff:       async p => (await import('../tools/resume-commands.js')).runDiff(p),
  share:      async p => (await import('../tools/resume-commands.js')).runShare(p),
  export:     async p => (await import('../tools/resume-commands.js')).runExport(p),
  checkpoint: async p => (await import('../tools/resume-commands.js')).runCheckpoint(p),
  history:    async p => (await import('../tools/resume-commands.js')).runHistory(p),
  restore:    async p => (await import('../tools/account-commands.js')).runRestore(p),

  // AI
  optimize:   async p => (await import('../tools/ai-commands.js')).runOptimize(p),
  combined:   async p => (await import('../tools/ai-commands.js')).runCombined(p),
  ats:        async p => (await import('../tools/ai-commands.js')).runAts(p),
  'quick-ats': async p => (await import('../tools/ai-commands.js')).runQuickAts(p),
  cover:      async p => (await import('../tools/ai-commands.js')).runCover(p),
  interview:  async p => (await import('../tools/ai-commands.js')).runInterview(p),

  // Account / artefacts
  jobs:       async () => (await import('../tools/account-commands.js')).runJobs(),
  pdf:        async p => (await import('../tools/account-commands.js')).runPdf(p),
  log:        async p => (await import('../tools/account-commands.js')).runLog(p),
  analytics:  async p => (await import('../tools/account-commands.js')).runAnalytics(p),
  billing:    async () => (await import('../tools/account-commands.js')).runBilling(),
  tracker:    async p => (await import('../tools/account-commands.js')).runTracker(p),
  snippets:   async p => (await import('../tools/account-commands.js')).runSnippets(p),
  byok:       async () => (await import('../tools/account-commands.js')).runByok(),
  model:      async () => (await import('../tools/account-commands.js')).runModel(),
  settings:   async p => (await import('../tools/account-commands.js')).runSettings(p),

  compile: async (p) => {
    if ($activeJobId.get() != null) {
      addMessage({ role: 'error', content: 'A job is already running. Use /cancel to stop it first.' })
      return
    }
    const { runCompile } = await import('../tools/compile.js')
    await runCompile(p)
  },
  health: async () => {
    const { getApiClient } = await import('../lib/api-client.js')
    try {
      const result = await getApiClient().get<{ status: string }>('/health')
      addMessage({ role: 'system', content: `Backend status: ${result.status}` })
    } catch (err) {
      addMessage({ role: 'error', content: `Health check failed: ${String(err)}` })
    }
  },
  cancel: async (p) => {
    const jobId = p.positional[0] ?? $activeJobId.get()
    if (!jobId) {
      addMessage({ role: 'error', content: 'No active job to cancel.' })
      return
    }
    const { getApiClient } = await import('../lib/api-client.js')
    try {
      await getApiClient().delete(`/jobs/${jobId}`)
      addMessage({ role: 'system', content: `Job ${jobId} cancellation requested.` })
    } catch (err) {
      addMessage({ role: 'error', content: `Cancel failed: ${String(err)}` })
    }
  },
}

export async function dispatch(input: string): Promise<void> {
  if (input.startsWith('/')) {
    const parsed = parseSlashCommand(input)
    if (!parsed) return

    addMessage({ role: 'user', content: input })

    const localHandler = LOCAL_HANDLERS[parsed.name]
    if (localHandler) {
      await localHandler(parsed)
      return
    }

    const apiHandler = API_HANDLERS[parsed.name]
    if (apiHandler) {
      await apiHandler(parsed)
      return
    }

    // Distinguish "no such command" from "planned but not built". Telling a user
    // that /optimize is unknown when it is listed in the registry and described
    // in /help is simply misleading.
    const known = COMMAND_MAP.get(parsed.name)
    addMessage({
      role: 'error',
      content: known
        ? `/${parsed.name} is not implemented yet. Type /help to see what you can run today.`
        : `Unknown command: /${parsed.name}. Type /help to see available commands.`,
    })
    return
  }

  // Free-text input: agent mode (not yet implemented in Phase 1)
  addMessage({ role: 'user', content: input })
  addMessage({
    role: 'system',
    content: 'No model configured — run /byok to add an API key or /model to select a provider.',
  })
}

/**
 * Names dispatch will actually route.
 *
 * Exported so the parity test can compare it against the advertised registry
 * without executing anything — the two lists silently diverging is what left 25
 * commands answering "Unknown command".
 */
export function handlerNames(): Set<string> {
  return new Set([...Object.keys(LOCAL_HANDLERS), ...Object.keys(API_HANDLERS)])
}
