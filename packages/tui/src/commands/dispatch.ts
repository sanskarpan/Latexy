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

async function getResumePicker(
  opts: { archived?: boolean; documentType?: string } = {},
): Promise<React.ReactElement> {
  const { ResumePicker } = await import('../components/overlays/ResumePicker.js')
  return React.createElement(ResumePicker, { ...opts })
}

// Tier 1: local handlers (no API call, just UI changes)
const LOCAL_HANDLERS: Record<string, (parsed: ReturnType<typeof parseSlashCommand>) => Promise<void>> = {
  list: async (p) => {
    // The flags were documented in the registry and thrown away here — `parsed`
    // was discarded entirely, so /list --archived listed active resumes.
    openOverlay(await getResumePicker({
      archived: p?.args['archived'] === true,
      documentType: typeof p?.args['type'] === 'string' ? p.args['type'] : undefined,
    }))
  },
  clear: async () => {
    clearMessages()
  },
  workbench: async () => {
    const { openWorkbench } = await import('../stores/workbench.js')
    openWorkbench()
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
    // The bare $activeJobId read here was the same check-then-act shape removed
    // from the other job commands: compile.ts only sets it after its POST
    // resolves, so two compiles — or a compile racing an optimize — both got
    // through and only one could be tracked or cancelled. /compile is the most
    // used command in the TUI, so it was the worst place to leave it.
    const { withJobSlot } = await import('../tools/shared.js')
    const { runCompile } = await import('../tools/compile.js')
    await withJobSlot(async () => { await runCompile(p) })
  },
  health: async () => {
    const { getApiClient } = await import('../lib/api-client.js')
    try {
      const result = await getApiClient().get<{ status: string }>('/health')
      addMessage({ role: 'system', content: `Backend status: ${result.status}` })
    } catch (err) {
      // String(err) rendered "TypeError: fetch failed" when the backend was down.
      const { describeError } = await import('../tools/shared.js')
      addMessage({ role: 'error', content: `Health check failed: ${describeError(err)}` })
    }
  },
  cancel: async (p) => {
    const jobId = p.positional[0] ?? $activeJobId.get()
    if (!jobId) {
      addMessage({ role: 'error', content: 'No active job to cancel.' })
      return
    }
    const { getApiClient } = await import('../lib/api-client.js')
    // The slot is held by $activeJobId until a terminal event arrives. If the
    // socket dropped, or the worker died, or the job settled while the TUI was
    // not listening, that event never comes — and /cancel used to leave
    // $activeJobId set, so the one command the error message tells the user to
    // run could not clear it. Every subsequent job was refused with "a job is
    // already running" until the process was restarted.
    const releaseIfCurrent = (): void => {
      if ($activeJobId.get() === jobId) $activeJobId.set(null)
    }
    try {
      // DELETE /jobs/{id} answers 200 {"success":true} even for an id that was
      // never a job, so the response cannot distinguish a real cancellation from
      // a no-op. Confirm the job exists first, otherwise any typo was reported
      // back as a successful cancellation.
      const client = getApiClient()
      let state: { status?: string } | null
      try {
        state = await client.get<{ status?: string } | null>(`/jobs/${jobId}/state`)
      } catch {
        // An id we cannot look up must not keep the slot hostage either.
        releaseIfCurrent()
        addMessage({ role: 'error', content: `No job with id ${jobId} — see /jobs for recent ones.` })
        return
      }

      // Optional chaining, not `state.status`: a body that is not an object
      // threw here and the cancellation never reached the server.
      const status = String(state?.status ?? '').toLowerCase()
      if (['completed', 'failed', 'cancelled', 'canceled'].includes(status)) {
        releaseIfCurrent()
        addMessage({
          role: 'system',
          content: `Job ${jobId} already ${status} — nothing to cancel. You can start a new one.`,
        })
        return
      }

      await client.delete(`/jobs/${jobId}`)
      releaseIfCurrent()
      addMessage({ role: 'system', content: `Job ${jobId} cancellation requested.` })
    } catch (err) {
      const { describeError } = await import('../tools/shared.js')
      addMessage({ role: 'error', content: `Cancel failed: ${describeError(err)}` })
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
