import React, { useState, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { initApiClient } from '../../lib/api-client.js'
import { writeConfig } from '../../lib/config.js'
import { $session } from '../../stores/session.js'
import { closeOverlay } from '../../stores/overlay.js'
import { addMessage } from '../../stores/messages.js'
import { wsClient } from '../../lib/ws-client.js'
import { $ui } from '../../stores/ui.js'

type Step = 'email' | 'password' | 'loading' | 'error'

interface AuthResponse {
  token: string
  user: { id: string; email: string; plan?: string }
}

export function LoginOverlay(): React.ReactElement {
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState(process.env['LATEXY_EMAIL'] ?? '')
  const [password, setPassword] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const handleEmailSubmit = useCallback((val: string) => {
    if (!val.trim()) return
    setEmail(val.trim())
    setStep('password')
  }, [])

  const handlePasswordSubmit = useCallback(async (val: string) => {
    if (!val.trim()) return
    setStep('loading')
    setErrorMsg(null)

    const session = $session.get()
    const client = initApiClient(session.backendUrl, null)

    try {
      // Better Auth signin endpoint
      const res = await client.post<AuthResponse>('/api/auth/sign-in/email', {
        email: email.trim(),
        password: val,
      })

      // Clear password from process env
      if ('LATEXY_PASSWORD' in process.env) {
        delete process.env['LATEXY_PASSWORD']
      }

      const { token, user } = res
      await writeConfig({ token, email: user.email, userId: user.id })

      const newClient = initApiClient(session.backendUrl, token)
      void newClient // used for side effects
      const wsUrl = session.wsUrl

      $session.set({
        ...session,
        token,
        userId: user.id,
        email: user.email,
        plan: (user.plan ?? null) as 'free' | 'basic' | 'pro' | 'byok' | 'team' | null,
        isAuthenticated: true,
      })

      wsClient.connect(wsUrl, token)
      wsClient.on('connected', () => {
        $ui.set({ ...$ui.get(), wsConnected: true })
        wsClient.drain()
      })

      closeOverlay()
      addMessage({ role: 'system', content: `Welcome, ${user.email}` })
    } catch (err) {
      setErrorMsg(String(err))
      setStep('error')
      setPassword('')
    }
  }, [email])

  useInput((_input, key) => {
    if (key.escape && step === 'error') {
      setStep('email')
      setErrorMsg(null)
    }
  })

  return (
    <Box flexDirection="column" padding={2} borderStyle="round" borderColor="cyan">
      <Text bold color="cyan">Welcome to Latexy</Text>
      <Text dimColor>Sign in to continue</Text>
      <Box marginTop={1} />

      {step === 'email' && (
        <Box gap={1}>
          <Text>Email:</Text>
          <TextInput
            value={email}
            onChange={setEmail}
            onSubmit={handleEmailSubmit}
            placeholder="you@example.com"
          />
        </Box>
      )}

      {step === 'password' && (
        <>
          <Text dimColor>Email: {email}</Text>
          <Box gap={1} marginTop={1}>
            <Text>Password:</Text>
            <TextInput
              value={password}
              onChange={setPassword}
              onSubmit={(val) => { void handlePasswordSubmit(val) }}
              mask="*"
              placeholder="••••••••"
            />
          </Box>
        </>
      )}

      {step === 'loading' && (
        <Text color="yellow">Signing in…</Text>
      )}

      {step === 'error' && (
        <Box flexDirection="column" gap={1}>
          <Text color="red">✗ {errorMsg}</Text>
          <Text dimColor>Press Esc to try again</Text>
        </Box>
      )}
    </Box>
  )
}
