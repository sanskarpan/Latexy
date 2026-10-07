import React, { useState, useCallback } from 'react'
import { Box, Text } from 'ink'
import { CtrlSafeTextInput } from './CtrlSafeTextInput.js'
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

  /**
   * Accept text the terminal delivers as one chunk.
   *
   * Two things arrive here that ink-text-input treats as ordinary characters:
   *
   *  - A *pasted* command carries its own newline, so `/health\r` was inserted
   *    literally, grew the box to two lines, and never ran.
   *  - Raw control bytes that arrive as part of a pasted chunk. AppShell handles
   *    standalone Ctrl+L through Ink's key metadata, while CtrlSafeTextInput
   *    prevents its normalized letter from entering the controlled value.
   */
  const handleChange = useCallback((next: string) => {
    // C0 controls minus \t \n \r, which are handled below.
    const strip = (t: string): string => t.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
    if (!/[\r\n]/.test(next)) {
      setValue(strip(next))
      return
    }
    // Submit EVERY complete line, not just the first. Consuming one newline left
    // any second command stranded in the box with its literal \r, and a paste
    // whose first line was blank submitted nothing at all.
    const segments = next.split(/\r\n|[\r\n]/)
    // No trailing newline means the last segment is still being typed.
    const tail = segments.pop() ?? ''
    for (const segment of segments) {
      const line = strip(segment).trim()
      if (line) onSubmit(line)
    }
    setValue(strip(tail))
  }, [onSubmit])

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
      {/* `value.length > 1` meant a bare "/" showed nothing — while the welcome
          banner and the hint line both say "type / to see available commands". */}
      {isSlash && (
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
            <CtrlSafeTextInput
              value={value}
              onChange={handleChange}
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
