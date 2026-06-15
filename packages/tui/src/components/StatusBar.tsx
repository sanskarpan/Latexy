import React from 'react'
import { Box, Text } from 'ink'
import type { HealthStatus } from '../stores/ui.js'

interface Props {
  email: string | null
  plan: string | null
  health: HealthStatus
  wsConnected: boolean
}

const HEALTH_COLOR: Record<HealthStatus, string> = {
  healthy: 'green',
  degraded: 'yellow',
  unhealthy: 'red',
  unknown: 'gray',
}

const PLAN_LABEL: Record<string, string> = {
  free: 'FREE', basic: 'BASIC', pro: 'PRO', byok: 'BYOK', team: 'TEAM',
}

export function StatusBar({ email, plan, health, wsConnected }: Props): React.ReactElement {
  const healthColor = HEALTH_COLOR[health]
  const planLabel = plan ? (PLAN_LABEL[plan] ?? plan.toUpperCase()) : null

  return (
    <Box paddingX={1} justifyContent="space-between">
      <Text bold color="cyan">Latexy</Text>
      <Box gap={2}>
        {email && (
          <Text>
            {email}
            {planLabel && <Text color="magenta"> [{planLabel}]</Text>}
          </Text>
        )}
        <Text color={healthColor as string}>● {health}</Text>
        {!wsConnected && <Text color="yellow">⚡ disconnected</Text>}
        <Text dimColor>? help · / commands</Text>
      </Box>
    </Box>
  )
}
