import React, { useMemo } from 'react'
import { Box, Text } from 'ink'

interface Props {
  lines: string[]
  maxVisible?: number
}

function classifyLine(line: string): 'error' | 'warning' | 'info' {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('[err]')) return 'error'
  if (lower.includes('warning') || lower.includes('warn')) return 'warning'
  return 'info'
}

export function LogStreamCard({ lines, maxVisible = 20 }: Props): React.ReactElement {
  const visible = useMemo(
    () => (lines.length > maxVisible ? lines.slice(-maxVisible) : lines),
    [lines, maxVisible]
  )

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginY={1}>
      <Box justifyContent="space-between">
        <Text bold color="gray">pdflatex log</Text>
        <Text dimColor>{lines.length} lines</Text>
      </Box>
      {visible.map((line, i) => {
        const kind = classifyLine(line)
        const color = kind === 'error' ? 'red' : kind === 'warning' ? 'yellow' : undefined
        return (
          <Text key={i} color={color} wrap="truncate-end">
            {line}
          </Text>
        )
      })}
    </Box>
  )
}
