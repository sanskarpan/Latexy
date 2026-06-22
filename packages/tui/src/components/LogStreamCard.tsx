import React, { useMemo, useState } from 'react'
import { Box, Text, useInput } from 'ink'
import { ProgressBar } from './ProgressBar.js'

interface Props {
  lines: string[]
  maxVisible?: number
  percent?: number
  isActive?: boolean
}

function classifyLine(line: string): 'error' | 'warning' | 'success' | 'info' {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('[err]')) return 'error'
  if (lower.includes('warning') || lower.includes('warn')) return 'warning'
  if (lower.includes('success') || lower.includes('done') || lower.includes('complete')) return 'success'
  return 'info'
}

export function LogStreamCard({ lines, maxVisible = 25, percent, isActive = false }: Props): React.ReactElement {
  const [collapsed, setCollapsed] = useState(false)

  useInput((_input, key) => {
    if (key.return) {
      setCollapsed(c => !c)
    }
  }, { isActive })

  const visible = useMemo(
    () => (lines.length > maxVisible ? lines.slice(-maxVisible) : lines),
    [lines, maxVisible]
  )

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginY={1}>
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text bold color="gray">{collapsed ? '▶' : '▼'} Build Log</Text>
          <Text dimColor>({lines.length} lines)</Text>
        </Box>
        {percent != null && <ProgressBar value={percent} width={15} />}
      </Box>
      {!collapsed && visible.map((line, i) => {
        const kind = classifyLine(line)
        if (kind === 'error') {
          return <Text key={i} color="red" bold wrap="truncate-end">✗ {line}</Text>
        }
        if (kind === 'warning') {
          return <Text key={i} color="yellow" wrap="truncate-end">⚠ {line}</Text>
        }
        if (kind === 'success') {
          return <Text key={i} color="green" wrap="truncate-end">✓ {line}</Text>
        }
        return <Text key={i} dimColor wrap="truncate-end">{line}</Text>
      })}
    </Box>
  )
}
