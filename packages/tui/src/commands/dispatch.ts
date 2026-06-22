import React from 'react'
import { parseSlashCommand } from './parser.js'
import { COMMAND_MAP } from './registry.js'
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
        ? `/${cmd.name} — ${cmd.description}\nUsage: ${cmd.usage}`
        : `Available commands:\n${[...COMMAND_MAP.keys()].map(k => `  /${k}`).join('\n')}`,
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

    // Unknown command
    addMessage({
      role: 'error',
      content: `Unknown command: /${parsed.name}. Type /help to see available commands.`,
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
