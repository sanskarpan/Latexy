import React from 'react'
import { render } from 'ink'
import { App } from './app.js'
import { runHeadless, parseHeadlessArgs } from './headless.js'

const args = process.argv.slice(2)
const isCI = process.env['CI'] === 'true' || process.stdout.isTTY !== true
const hasJsonFlag = args.includes('--json')
// The first true positional — not merely the first token without a leading dash,
// which picked up flag VALUES (`--compiler xelatex` resolved to "xelatex").
const subcommand = parseHeadlessArgs(args).positional[0]

if (isCI || hasJsonFlag) {
  runHeadless(subcommand, args).then(code => {
    process.exit(code)
  }).catch(err => {
    const msg = String(err)
    if (hasJsonFlag) {
      process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n')
    } else {
      process.stderr.write(`Error: ${msg}\n`)
    }
    process.exit(1)
  })
} else {
  const { unmount, waitUntilExit } = render(React.createElement(App), { patchConsole: false })
  const shutdown = (): void => { unmount(); process.exit(0) }
  process.on('SIGTERM', shutdown)
  process.on('SIGINT', shutdown)
  // Ink puts stdin in raw mode, so Ctrl+C arrives as the byte 0x03 and never as
  // a signal — the SIGINT handler above is unreachable from the keyboard. Ink's
  // exit() unmounts the UI but does not end the process, and the websocket
  // heartbeat and the health poll keep the event loop alive indefinitely, so
  // Ctrl+C tore down the interface and then hung with the shell never returning.
  void waitUntilExit().then(() => { process.exit(0) })
}
