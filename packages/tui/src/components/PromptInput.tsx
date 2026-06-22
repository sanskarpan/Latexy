import React, { useState, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { useStore } from '@nanostores/react'
import { $isBlocked } from '../stores/overlay.js'
import { $activeJobId } from '../stores/messages.js'
import { SlashSuggestions } from './SlashSuggestions.js'

interface Props {
  onSubmit: (input: string) => void
}

export function PromptInput({ onSubmit }: Props): React.ReactElement {
  const [value, setValue] = useState('')
  const isBlocked = useStore($isBlocked)
  const activeJobId = useStore($activeJobId)

  const handleSubmit = useCallback((val: string) => {
    const trimmed = val.trim()
    if (!trimmed) return
    setValue('')
    onSubmit(trimmed)
  }, [onSubmit])

  useInput((_input, _key) => {}, { isActive: !isBlocked })

  const isSlash = value.startsWith('/')
  const slashQuery = isSlash ? value.slice(1) : ''
  const promptGlyph = activeJobId != null ? '◉' : '❯'
  const promptColor = activeJobId != null ? 'yellow' : 'cyan'

  if (isBlocked) {
    return (
      <Box flexDirection="column">
        <Box paddingX={1} borderStyle="single" borderColor="gray">
          <Text dimColor>[ overlay open — press Esc to dismiss ]</Text>
        </Box>
        <Box paddingX={1}>
          <Text dimColor>Ctrl+C exit  ·  Ctrl+L clear  ·  Esc close overlay  ·  / for commands</Text>
        </Box>
      </Box>
    )
  }

  return (
    <Box flexDirection="column">
      {isSlash && value.length > 1 && (
        <SlashSuggestions
          query={slashQuery}
          isActive={!isBlocked}
          onComplete={(name) => { setValue(`/${name} `) }}
        />
      )}
      <Box gap={1} paddingX={1} borderStyle="single" borderColor="cyan">
        <Text bold color={promptColor}>{promptGlyph}</Text>
        {activeJobId != null
          ? <Text dimColor>Running… (/cancel to stop)</Text>
          : (
            <TextInput
              value={value}
              onChange={setValue}
              onSubmit={handleSubmit}
              placeholder="Ask anything or type /command"
              focus={!isBlocked}
            />
          )
        }
        {value.length > 80 && (
          <Text dimColor>{value.length}</Text>
        )}
      </Box>
      <Box paddingX={1}>
        <Text dimColor>Ctrl+C exit  ·  Ctrl+L clear  ·  Esc close overlay  ·  / for commands</Text>
      </Box>
    </Box>
  )
}
