import React from 'react'
import { Box, Text } from 'ink'
import { Spinner } from '@inkjs/ui'
import type { Message } from '../stores/messages.js'

interface Props {
  message: Message
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function ToolUseCard({ message }: Props): React.ReactElement {
  const { toolName, toolState = 'running', durationMs, toolResult } = message

  if (toolState === 'running') {
    return (
      <Box flexDirection="column" marginY={0} paddingX={2}>
        <Box gap={1}>
          <Spinner />
          <Text bold>{toolName ?? 'tool'}</Text>
          {durationMs != null && <Text dimColor>({(durationMs / 1000).toFixed(1)}s…)</Text>}
        </Box>
      </Box>
    )
  }

  if (toolState === 'success') {
    return (
      <Box paddingX={2}>
        <Text color="green">✓ {toolName ?? 'tool'}</Text>
        {durationMs != null && <Text dimColor>  {formatMs(durationMs)}</Text>}
      </Box>
    )
  }

  if (toolState === 'error') {
    const errMsg = toolResult != null
      ? (typeof (toolResult as Record<string, unknown>)['error'] === 'string'
        ? String((toolResult as Record<string, unknown>)['error'])
        : JSON.stringify(toolResult))
      : 'unknown error'
    return (
      <Box flexDirection="column" paddingX={2}>
        <Text color="red">✗ {toolName ?? 'tool'}  failed</Text>
        <Box paddingLeft={2}>
          <Text color="red" dimColor wrap="wrap">{errMsg}</Text>
        </Box>
      </Box>
    )
  }

  // cancelled
  return (
    <Box paddingX={2}>
      <Text color="gray">⊘ {toolName ?? 'tool'}  cancelled</Text>
    </Box>
  )
}
