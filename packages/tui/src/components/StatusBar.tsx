import React from 'react'
import { Box, Text } from 'ink'
import type { HealthStatus } from '../stores/ui.js'
import { theme } from '../lib/theme.js'

interface Props {
  email: string | null
  plan: string | null
  health: HealthStatus
  wsConnected: boolean
}

const PLAN_LABEL: Record<string, string> = {
  free: 'free', basic: 'basic', pro: 'pro', byok: 'byok', team: 'team',
}

export function StatusBar({ email, plan, health, wsConnected }: Props): React.ReactElement {
  const healthColor = theme.health[health] ?? 'gray'
  const planColor = plan ? (theme.plan[plan as keyof typeof theme.plan] ?? 'gray') : 'gray'
  const planLabel = plan ? (PLAN_LABEL[plan] ?? plan) : null

  const displayEmail = email
    ? (email.length > 30 ? email.slice(0, 27) + '…' : email)
    : null

  return (
    <Box paddingX={1} justifyContent="space-between">
      {/* Left: brand */}
      <Box gap={1}>
        <Text bold color="cyan">⬡</Text>
        <Text bold color="cyan">Latexy</Text>
      </Box>

      {/* Center: plan + email */}
      <Box gap={2}>
        {planLabel && (
          <Text color={planColor}>{planLabel}</Text>
        )}
        {displayEmail && (
          <Text dimColor>{displayEmail}</Text>
        )}
      </Box>

      {/* Right: WS status + health */}
      <Box gap={2}>
        <Text color={wsConnected ? 'green' : 'gray'}>
          {wsConnected ? '● connected' : '○ disconnected'}
        </Text>
        <Text color={healthColor as string}>✦ {health}</Text>
      </Box>
    </Box>
  )
}
