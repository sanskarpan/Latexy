import React from 'react'
import { Box, Static } from 'ink'
import { useStore } from '@nanostores/react'
import { $messages } from '../stores/messages.js'
import { MessageRow } from './MessageRow.js'
import type { Message } from '../stores/messages.js'

export function TranscriptView(): React.ReactElement {
  const messages = useStore($messages)

  // Finalized messages go into Static (never re-renders once committed)
  // Active streaming messages go into the dynamic section below
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
