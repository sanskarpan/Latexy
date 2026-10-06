import React, { useEffect, useState } from 'react'
import { Box, Text, useStdout } from 'ink'
import type { HealthStatus } from '../stores/ui.js'
import { theme } from '../lib/theme.js'

interface Props {
  email: string | null
  plan: string | null
  health: HealthStatus
  wsConnected: boolean
  /** Test/embedding override; normal rendering follows the live terminal width. */
  columns?: number
}

const PLAN_LABEL: Record<string, string> = {
  free: 'free', basic: 'basic', pro: 'pro', byok: 'byok', team: 'team',
}

export function StatusBar({ email, plan, health, wsConnected, columns }: Props): React.ReactElement {
  const { stdout } = useStdout()
  const [terminalColumns, setTerminalColumns] = useState(columns ?? stdout?.columns ?? 80)

  useEffect(() => {
    if (columns != null) {
      setTerminalColumns(columns)
      return
    }
    if (stdout == null) return
    const measure = (): void => { setTerminalColumns(stdout.columns ?? 80) }
    stdout.on('resize', measure)
    measure()
    return () => { stdout.off('resize', measure) }
  }, [columns, stdout])

  const healthColor = theme.health[health] ?? 'gray'
  const planColor = plan ? (theme.plan[plan as keyof typeof theme.plan] ?? 'gray') : 'gray'
  const planLabel = plan ? (PLAN_LABEL[plan] ?? plan) : null

  const displayEmail = email
    ? (email.length > 30 ? email.slice(0, 27) + '…' : email)
    : null
  const compact = terminalColumns < 72
  const narrow = terminalColumns < 48

  return (
    <Box paddingX={1} justifyContent="space-between">
      {/* Left: brand */}
      <Box gap={1}>
        <Text bold color="cyan">⬡</Text>
        {!narrow && <Text bold color="cyan">Latexy</Text>}
      </Box>

      {/* Center: plan + email */}
      <Box gap={2}>
        {planLabel && (
          <Text color={planColor}>{planLabel}</Text>
        )}
        {!compact && displayEmail && (
          <Text dimColor>{displayEmail}</Text>
        )}
      </Box>

      {/* Right: WS status + health */}
      <Box gap={2}>
        <Text color={wsConnected ? 'green' : 'gray'}>
          {narrow
            ? (wsConnected ? '●' : '○')
            : compact
              ? (wsConnected ? '● ws' : '○ ws')
              : (wsConnected ? '● connected' : '○ disconnected')}
        </Text>
        <Text color={healthColor as string}>{narrow ? '✦' : `✦ ${health}`}</Text>
      </Box>
    </Box>
  )
}
