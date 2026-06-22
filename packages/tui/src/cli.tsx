import React from 'react'
import { render } from 'ink'
import { App } from './app.js'
import { runHeadless } from './headless.js'

const args = process.argv.slice(2)
const isCI = process.env['CI'] === 'true' || process.stdout.isTTY !== true
const hasJsonFlag = args.includes('--json')
const subcommand = args.find(a => !a.startsWith('-'))

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
  const { unmount } = render(React.createElement(App), { patchConsole: false })
  const shutdown = () => { unmount(); process.exit(0) }
  process.on('SIGTERM', shutdown)
  process.on('SIGINT', shutdown)
}
