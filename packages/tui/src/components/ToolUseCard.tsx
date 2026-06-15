import React from 'react'
import { Box, Text } from 'ink'
import type { Message } from '../stores/messages.js'

interface Props {
  message: Message
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

const STATE_ICON: Record<string, string> = {
  running: '◐',
  success: '✓',
  error: '✗',
  cancelled: '⊘',
}

const STATE_COLOR: Record<string, string> = {
  running: 'cyan',
  success: 'green',
  error: 'red',
  cancelled: 'yellow',
}

export function ToolUseCard({ message }: Props): React.ReactElement {
  const { toolName, toolState = 'running', durationMs, toolResult } = message
  const icon = STATE_ICON[toolState] ?? '·'
  const color = STATE_COLOR[toolState] ?? 'white'

  return (
    <Box flexDirection="column" marginY={0} paddingX={2}>
      <Box gap={1}>
        <Text color={color}>{icon}</Text>
        <Text bold>{toolName ?? 'tool'}</Text>
        {toolState === 'running' && <Text dimColor>running...</Text>}
        {toolState === 'success' && durationMs != null && (
          <Text dimColor>{formatMs(durationMs)}</Text>
        )}
        {toolState === 'error' && <Text color="red">error</Text>}
        {toolState === 'cancelled' && <Text color="yellow">cancelled</Text>}
      </Box>
      {toolState === 'error' && toolResult != null && (
        <Box paddingLeft={3}>
          <Text color="red" wrap="wrap">
            {typeof (toolResult as Record<string, unknown>)['error'] === 'string'
              ? String((toolResult as Record<string, unknown>)['error'])
              : JSON.stringify(toolResult)}
          </Text>
        </Box>
      )}
    </Box>
  )
}
