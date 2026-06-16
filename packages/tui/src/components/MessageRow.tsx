import React from 'react'
import { Box, Text } from 'ink'
import type { Message } from '../stores/messages.js'
import { ToolUseCard } from './ToolUseCard.js'
import { LogStreamCard } from './LogStreamCard.js'
import { CompileResultCard } from './CompileResultCard.js'

interface Props {
  message: Message
}

function UserRow({ message }: Props): React.ReactElement {
  const time = new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <Box paddingX={1} marginY={1} gap={1}>
      <Text dimColor color="cyan">you  </Text>
      <Text>{message.content}</Text>
      <Box flexGrow={1} />
      <Text dimColor>{time}</Text>
    </Box>
  )
}

function AssistantRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1} gap={1}>
      <Text bold color="cyan">⬡  </Text>
      <Text wrap="wrap">
        {message.content}
        {message.streaming === true && <Text color="cyan">▌</Text>}
      </Text>
    </Box>
  )
}

function SystemRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1} gap={1}>
      <Text dimColor color="blue">  ·  </Text>
      <Text dimColor>{message.content}</Text>
    </Box>
  )
}

function ErrorRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1} gap={1}>
      <Text color="red">  ✗  </Text>
      <Text color="red">{message.content}</Text>
    </Box>
  )
}

export function MessageRow({ message }: Props): React.ReactElement {
  switch (message.role) {
    case 'user':
      return <UserRow message={message} />

    case 'assistant':
      return <AssistantRow message={message} />

    case 'tool_use':
      return <ToolUseCard message={message} />

    case 'log_stream': {
      const data = message.resultData as { lines: string[]; percent?: number } | undefined
      return <LogStreamCard lines={data?.lines ?? []} percent={data?.percent} />
    }

    case 'compile_result': {
      const d = (message.resultData as {
        pages?: number
        sizeBytes?: number
        compilationTimeMs?: number
        pdfUrl?: string
        atsScore?: number
      } | undefined) ?? {}
      return (
        <CompileResultCard
          pages={d.pages ?? null}
          sizeBytes={d.sizeBytes ?? null}
          compilationTimeMs={d.compilationTimeMs ?? 0}
          pdfUrl={d.pdfUrl ?? null}
          atsScore={d.atsScore ?? null}
        />
      )
    }

    case 'system':
      return <SystemRow message={message} />

    case 'error':
      return <ErrorRow message={message} />

    default:
      return <Box paddingX={2}><Text dimColor>[{message.role}]</Text></Box>
  }
}
