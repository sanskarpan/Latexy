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

  useInput((_input, _key) => {
    // Global key handling delegated to AppShell
  }, { isActive: !isBlocked })

  const isSlash = value.startsWith('/')
  const slashQuery = isSlash ? value.slice(1) : ''

  return (
    <Box flexDirection="column">
      {isSlash && value.length > 1 && <SlashSuggestions query={slashQuery} />}
      <Box gap={1} paddingX={1} borderStyle="round" borderColor={isBlocked ? 'gray' : 'cyan'}>
        <Text bold color="cyan">›</Text>
        {activeJobId != null && !isBlocked
          ? <Text dimColor>Running… (Ctrl+C to cancel)</Text>
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
      </Box>
    </Box>
  )
}
