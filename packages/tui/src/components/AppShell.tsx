import React from 'react'
import { Box, useInput, useApp } from 'ink'
import { useStore } from '@nanostores/react'
import { $session } from '../stores/session.js'
import { $overlay, $isBlocked, closeOverlay } from '../stores/overlay.js'
import { $ui } from '../stores/ui.js'
import { clearMessages } from '../stores/messages.js'
import { StatusBar } from './StatusBar.js'
import { TranscriptView } from './TranscriptView.js'
import { PromptInput } from './PromptInput.js'
import { KeyboardHints } from './KeyboardHints.js'
import { useWSEventRouter } from '../hooks/useJobStream.js'

async function lazyDispatch(input: string): Promise<void> {
  const { dispatch } = await import('../commands/dispatch.js')
  return dispatch(input)
}

export function AppShell(): React.ReactElement {
  const session = useStore($session)
  const overlay = useStore($overlay)
  const ui = useStore($ui)
  const isBlocked = useStore($isBlocked)
  const { exit } = useApp()

  useWSEventRouter()

  useInput((input, key) => {
    if (key.ctrl && input === 'c' && !isBlocked) {
      exit()
      return
    }
    if (key.ctrl && input === 'l') {
      clearMessages()
      return
    }
    if (key.escape && overlay) {
      closeOverlay()
      return
    }
  })

  return (
    <Box flexDirection="column" height="100%">
      <StatusBar
        email={session.email}
        plan={session.plan}
        health={ui.healthStatus}
        wsConnected={ui.wsConnected}
      />
      <Box flexGrow={1} flexDirection="column" overflow="hidden">
        <TranscriptView />
      </Box>
      {overlay != null && (
        <Box flexDirection="column">
          <Box dimColor>
            <Box marginX={4} marginY={1}>
              {overlay as React.ReactElement}
            </Box>
          </Box>
        </Box>
      )}
      <PromptInput onSubmit={(input) => { void lazyDispatch(input) }} />
      <KeyboardHints />
    </Box>
  )
}
