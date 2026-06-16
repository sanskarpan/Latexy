import React from 'react'
import { Box, Static, Text } from 'ink'
import { useStore } from '@nanostores/react'
import { $messages } from '../stores/messages.js'
import { MessageRow } from './MessageRow.js'
import type { Message } from '../stores/messages.js'

// Import version from package.json
const VERSION = '1.0.0'

function WelcomeBanner(): React.ReactElement {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      padding={2}
      alignSelf="center"
      marginY={1}
    >
      <Box gap={1} marginBottom={1}>
        <Text bold color="cyan">⬡</Text>
        <Text bold color="cyan">Latexy</Text>
        <Text dimColor>v{VERSION}</Text>
      </Box>
      <Text>LaTeX resume compilation in your terminal</Text>
      <Box marginTop={1} flexDirection="column">
        <Text dimColor>Type <Text color="cyan">/</Text> to see available commands</Text>
        <Text dimColor>Type <Text color="cyan">/help</Text> for documentation</Text>
      </Box>
    </Box>
  )
}

export function TranscriptView(): React.ReactElement {
  const messages = useStore($messages)

  if (messages.length === 0) {
    return (
      <Box flexDirection="column" flexGrow={1} alignItems="center" justifyContent="center">
        <WelcomeBanner />
      </Box>
    )
  }

  const completed: Message[] = []
  const active: Message[] = []

  for (const msg of messages) {
    if (msg.streaming === true || msg.toolState === 'running') {
      active.push(msg)
    } else {
      completed.push(msg)
    }
  }

  return (
    <Box flexDirection="column" flexGrow={1} overflow="hidden">
      <Static items={completed}>
        {(msg) => <MessageRow key={msg.id} message={msg} />}
      </Static>
      {active.map(msg => (
        <MessageRow key={msg.id} message={msg} />
      ))}
    </Box>
  )
}
