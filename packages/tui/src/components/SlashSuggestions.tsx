import React, { useMemo } from 'react'
import { Box, Text } from 'ink'
import { SLASH_COMMANDS } from '../commands/registry.js'

interface Props {
  query: string
  maxItems?: number
}

export function SlashSuggestions({ query, maxItems = 5 }: Props): React.ReactElement | null {
  const matches = useMemo(() => {
    const q = query.toLowerCase()
    return SLASH_COMMANDS.filter(c =>
      c.name.startsWith(q) || c.description.toLowerCase().includes(q)
    ).slice(0, maxItems)
  }, [query, maxItems])

  if (matches.length === 0) return null

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1}>
      {matches.map(cmd => (
        <Box key={cmd.name} gap={2}>
          <Text color="cyan">/{cmd.name}</Text>
          <Text dimColor>{cmd.description}</Text>
        </Box>
      ))}
    </Box>
  )
}
