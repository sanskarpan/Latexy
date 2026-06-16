import React from 'react'
import { Box, Text } from 'ink'

interface Props {
  value: number      // 0–100
  width?: number
  showPercent?: boolean
}

export function ProgressBar({ value, width = 20, showPercent = true }: Props): React.ReactElement {
  const clamped = Math.max(0, Math.min(100, value))
  const filled = Math.round((clamped / 100) * width)
  const empty = width - filled
  const bar = '█'.repeat(filled) + '░'.repeat(empty)
  const color = clamped > 75 ? 'green' : clamped >= 40 ? 'yellow' : 'red'

  return (
    <Box gap={1}>
      <Text color={color}>{bar}</Text>
      {showPercent && <Text dimColor>{clamped}%</Text>}
    </Box>
  )
}
