import React, { useMemo, useState, useCallback, useEffect } from 'react'
import { Box, Text, useInput } from 'ink'
import { IMPLEMENTED_COMMANDS } from '../commands/registry.js'

interface Props {
  query: string
  maxItems?: number
  onComplete?: (name: string) => void
  isActive?: boolean
}

export function SlashSuggestions({ query, maxItems = 7, onComplete, isActive = true }: Props): React.ReactElement | null {
  const [selectedIndex, setSelectedIndex] = useState(0)

  const matches = useMemo(() => {
    const q = query.toLowerCase()
    // Name matches first. A flat OR ranked them by registry order, so typing
    // "co" offered /share — whose description happens to say "copy share link" —
    // above commands actually beginning with "co". Descriptions still match, so
    // searching by intent works; they just rank below the literal prefix.
    const byName = IMPLEMENTED_COMMANDS.filter(c => c.name.startsWith(q))
    const byDescription = IMPLEMENTED_COMMANDS.filter(
      c => !c.name.startsWith(q) && c.description.toLowerCase().includes(q),
    )
    return [...byName, ...byDescription].slice(0, maxItems)
  }, [query, maxItems])

  // Reset selection when matches change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const handleComplete = useCallback(() => {
    if (onComplete) {
      const cmd = matches[selectedIndex]
      if (cmd) onComplete(cmd.name)
    }
  }, [matches, selectedIndex, onComplete])

  useInput((input, key) => {
    if (matches.length === 0) return

    if (key.upArrow) {
      setSelectedIndex(i => (i - 1 + matches.length) % matches.length)
    } else if (key.downArrow) {
      setSelectedIndex(i => (i + 1) % matches.length)
    } else if (key.tab) {
      handleComplete()
    }
  }, { isActive })

  if (matches.length === 0) return null

  const totalMatches = IMPLEMENTED_COMMANDS.filter(c => {
    const q = query.toLowerCase()
    return c.name.startsWith(q) || c.description.toLowerCase().includes(q)
  }).length

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1} marginBottom={1}>
      <Box justifyContent="space-between">
        <Text bold dimColor>Commands</Text>
        <Text dimColor>{matches.length} of {totalMatches}</Text>
      </Box>
      {matches.map((cmd, i) => (
        <Box key={cmd.name} gap={2}>
          <Text bold color={i === selectedIndex ? 'cyan' : undefined} underline={i === selectedIndex}>
            /{cmd.name}
          </Text>
          <Text dimColor={i !== selectedIndex}>{cmd.description}</Text>
          <Box flexGrow={1} />
          <Text dimColor>{cmd.isLocal ? 'local' : 'api'}</Text>
        </Box>
      ))}
    </Box>
  )
}
