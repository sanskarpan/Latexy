import React, { useEffect } from 'react'
import { useStore } from '@nanostores/react'
import { $session } from './stores/session.js'
import { $overlay, openOverlay } from './stores/overlay.js'
import { $ui } from './stores/ui.js'
import { AppShell } from './components/AppShell.js'
import { wsClient } from './lib/ws-client.js'
import { initApiClient } from './lib/api-client.js'
import { readConfig } from './lib/config.js'
import { addMessage } from './stores/messages.js'

export function App(): React.ReactElement {
  const _session = useStore($session)
  const _overlay = useStore($overlay)

  useEffect(() => {
    const init = async (): Promise<void> => {
      const cfg = await readConfig()

      const backendUrl = cfg.backendUrl
      const wsUrl = backendUrl.replace(/^http/, 'ws') + '/ws/jobs'

      initApiClient(backendUrl, cfg.token)

      $session.set({
        token: cfg.token,
        userId: cfg.userId ?? null,
        email: cfg.email ?? null,
        plan: null,
        backendUrl,
        wsUrl,
        isAuthenticated: cfg.token != null,
      })

      if (cfg.token) {
        wsClient.connect(wsUrl, cfg.token)
        wsClient.on('connected', () => {
          $ui.set({ ...$ui.get(), wsConnected: true })
          wsClient.drain()
        })
        wsClient.on('disconnected', () => {
          $ui.set({ ...$ui.get(), wsConnected: false })
        })

        // Validate token + get user info
        const { getApiClient } = await import('./lib/api-client.js')
        try {
          const me = await getApiClient().get<{ id: string; email: string; plan?: string }>('/api/me')
          $session.set({
            ...$session.get(),
            userId: me.id,
            email: me.email,
            plan: (me.plan ?? null) as 'free' | 'basic' | 'pro' | 'byok' | 'team' | null,
          })
          addMessage({ role: 'system', content: `Welcome back, ${me.email}` })
        } catch {
          // Invalid token — show login
          $session.set({ ...$session.get(), token: null, isAuthenticated: false })
          const { LoginOverlay } = await import('./components/overlays/LoginOverlay.js')
          openOverlay(React.createElement(LoginOverlay))
        }

        // Background health poll every 30s
        const poll = async () => {
          try {
            await getApiClient().get('/health')
            $ui.set({ ...$ui.get(), healthStatus: 'healthy' })
          } catch {
            $ui.set({ ...$ui.get(), healthStatus: 'unhealthy' })
          }
        }
        await poll()
        setInterval(() => { void poll() }, 30_000)
      } else {
        const { LoginOverlay } = await import('./components/overlays/LoginOverlay.js')
        openOverlay(React.createElement(LoginOverlay))
      }
    }

    init().catch(err => {
      addMessage({ role: 'error', content: `Startup error: ${String(err)}` })
    })
  }, [])

  return <AppShell />
}
