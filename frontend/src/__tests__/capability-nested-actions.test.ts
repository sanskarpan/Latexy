import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'

it('enforces nested capability admission, live revocation, and recovery regressions', () => {
  // Keep this suite runnable without installing the frontend dependency tree,
  // and include the same checks in the normal Vitest/CI entry point.
  const output = execFileSync(process.execPath, [
    '--test', fileURLToPath(new URL('./capability-nested-actions.node.test.mjs', import.meta.url)),
  ], { encoding: 'utf8', timeout: 20_000 })
  expect(output).toMatch(/fail 0/)
})
