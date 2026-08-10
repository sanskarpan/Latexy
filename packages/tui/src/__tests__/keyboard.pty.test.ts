/**
 * Keyboard behaviour, driven through a real pty against the built CLI.
 *
 * This is the only automated coverage of the input layer. `ink-testing-library@4`
 * does not deliver keystrokes to Ink 5 — a minimal `useInput` probe that appends
 * every character it receives renders `[]` after two writes to its stdin — so
 * every keyboard fix was previously verified by hand, and three of them shipped
 * wrong before they were right (#1132).
 *
 * The work happens in `test-harness/pty_driver.py`: Python's stdlib `pty` needs no
 * npm dependency and no native build, and the driver starts its own stub backend,
 * so this needs nothing running. It does need `dist/` to be current — CI builds
 * before testing; locally, run `pnpm build` first.
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const DRIVER = join(process.cwd(), 'test-harness', 'pty_driver.py')
const DIST = join(process.cwd(), 'dist', 'cli.js')

function python(): string | null {
  for (const bin of ['python3', 'python']) {
    try {
      execFileSync(bin, ['--version'], { stdio: 'ignore' })
      return bin
    } catch { /* try the next one */ }
  }
  return null
}

const PY = python()
const READY = PY != null && existsSync(DRIVER) && existsSync(DIST)

if (!READY) {
  const why = PY == null ? 'no python3 on PATH'
    : !existsSync(DIST) ? 'dist/cli.js missing — run `pnpm build`'
      : 'driver missing'
  process.stderr.write(`keyboard.pty: skipped — ${why}\n`)
}

interface Result {
  prompt?: string
  exited?: boolean
  exit_code?: number | null
  exit_seconds?: number | null
  [k: string]: unknown
}

function run(scenario: string): Result {
  const raw = execFileSync(PY!, [DRIVER, scenario], {
    encoding: 'utf-8',
    timeout: 90_000,
    // A pty scenario writes nothing to stdout except its final JSON line.
    maxBuffer: 4 * 1024 * 1024,
  })
  const line = raw.trim().split('\n').filter(Boolean).pop() ?? '{}'
  return JSON.parse(line) as Result
}

;(READY ? describe : describe.skip)('keyboard behaviour in a real pty', () => {
  it('boots to a usable prompt with no crash', () => {
    const r = run('boot')
    expect(r['ready'], 'never reached a focused prompt').toBe(true)
    expect(r['booted']).toBe(true)
    expect(r['has_prompt']).toBe(true)
    expect(r['no_crash'], 'a stack trace reached the screen').toBe(true)
  }, 90_000)

  it('a bare / opens the command menu', () => {
    // The welcome banner and hint line both say "type / to see available
    // commands", but the list was gated on `value.length > 1`.
    const r = run('slash_menu')
    expect(r['suggestions_visible']).toBe(true)
    expect(r.prompt).toBe('/')
  }, 90_000)

  describe('Ctrl+L clears the transcript without touching the prompt', () => {
    // Ink normalises 0x0C to input='l' + key.ctrl before onChange runs, so
    // ink-text-input appends the letter. Filtering control bytes in onChange was
    // a no-op; the repair has to happen after the append.
    it('leaves an empty prompt empty', () => {
      expect(run('ctrl_l_empty').prompt).toBe('')
    }, 90_000)

    it('does not append to text already typed', () => {
      expect(run('ctrl_l_text').prompt).toBe('hello')
    }, 90_000)

    it('does not eat a real trailing l, nor double it', () => {
      // The decisive case: a repair applied before the append yields "abcll".
      expect(run('ctrl_l_trailing_l').prompt).toBe('abcl')
    }, 90_000)

    it('applies to any ctrl-modified letter', () => {
      expect(run('ctrl_a_text').prompt).toBe('abc')
    }, 90_000)

    it('does not break ordinary typing of the same letter', () => {
      expect(run('typing_l').prompt).toBe('llama')
    }, 90_000)
  })

  describe('pasted input', () => {
    it('a command pasted with its newline is submitted', () => {
      const r = run('paste_single')
      expect(r['submitted'], 'the paste was inserted literally instead of running').toBe(true)
      expect(r.prompt).toBe('')
    }, 90_000)

    it('every complete line of a multi-command paste runs', () => {
      const r = run('paste_multi')
      expect(r['first_ran']).toBe(true)
      expect(r['second_ran'], 'only the first newline was consumed').toBe(true)
      expect(r.prompt).toBe('')
    }, 90_000)

    it('a leading blank line does not swallow the command after it', () => {
      expect(run('paste_blank_first')['submitted']).toBe(true)
    }, 90_000)

    it('an incomplete trailing line stays in the box', () => {
      expect(run('paste_incomplete_tail').prompt).toBe('/clear')
    }, 90_000)
  })

  describe('Ctrl+C', () => {
    it('exits the process, and promptly', () => {
      // Ink's exit() unmounts but does not end the process, and the websocket
      // heartbeat plus the health poll kept the event loop alive — so this used
      // to tear down the UI and then hang with the shell never returning.
      const r = run('ctrl_c_exits')
      expect(r.exited, 'the process never exited').toBe(true)
      expect(r.exit_code).toBe(0)
      expect(r.exit_seconds ?? 99).toBeLessThan(5)
    }, 90_000)

    it('does not delete a real trailing c on the way out', () => {
      // ink-text-input deliberately does not append for Ctrl+C, so the guard
      // must exclude it or "abc" becomes "ab".
      const r = run('ctrl_c_keeps_c')
      expect(r['prompt_before_exit']).toBe('abc')
      expect(r.exited).toBe(true)
    }, 90_000)
  })
})
