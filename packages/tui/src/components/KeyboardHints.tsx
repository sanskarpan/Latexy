import React from 'react'
import { Box, Text } from 'ink'
import { useStore } from '@nanostores/react'
import { $activeJobId } from '../stores/messages.js'
import { $isBlocked } from '../stores/overlay.js'

export function KeyboardHints(): React.ReactElement {
  const activeJobId = useStore($activeJobId)
  const isBlocked = useStore($isBlocked)

  const hints: string[] = []
  hints.push('Ctrl+C exit')
  hints.push('Ctrl+L clear')
  if (isBlocked) {
    hints.push('Esc dismiss')
  } else if (activeJobId != null) {
    hints.push('/cancel')
  } else {
    hints.push('/compile')
    hints.push('/ats')
    hints.push('/list')
    hints.push('/help')
  }

  return (
    <Box paddingX={1}>
      <Text dimColor>{hints.join('  ·  ')}</Text>
    </Box>
  )
}
