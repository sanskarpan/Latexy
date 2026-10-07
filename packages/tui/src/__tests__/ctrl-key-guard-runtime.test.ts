import { PassThrough, Writable } from 'node:stream'
import React, { useState } from 'react'
import { render } from 'ink'
import { describe, expect, it } from 'vitest'
import { CtrlSafeTextInput } from '../components/CtrlSafeTextInput.js'

type ProbeOptions = {
  initial?: string
  focus?: boolean
  mask?: string
  onSubmit?: (value: string) => void
}

function waitForEffects(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 25))
}

async function send(probe: { stdin: PassThrough }, input: string, delay = 25): Promise<void> {
  probe.stdin.write(input)
  await new Promise((resolve) => setTimeout(resolve, delay))
}

async function mountProbe(options: ProbeOptions = {}) {
  const stdin = new PassThrough() as PassThrough & NodeJS.ReadStream
  stdin.isTTY = true
  stdin.setRawMode = (() => stdin) as typeof stdin.setRawMode
  stdin.ref = (() => stdin) as typeof stdin.ref
  stdin.unref = (() => stdin) as typeof stdin.unref
  const stdoutChunks: string[] = []
  const stdout = new Writable({
    write(chunk, _encoding, callback) {
      stdoutChunks.push(String(chunk))
      callback()
    },
  })
  Object.assign(stdout, {
    isTTY: true,
    columns: 80,
    rows: 24,
    // Advertise color so the focused inverse cursor is observable in the
    // captured render stream; the CLI PTY suite covers monochrome terminals.
    getColorDepth: () => 8,
    hasColors: () => true,
  })
  const stderrChunks: string[] = []
  const stderr = new Writable({
    write(chunk, _encoding, callback) {
      stderrChunks.push(String(chunk))
      callback()
    },
  })

  let value = options.initial ?? ''
  function Probe() {
    const [input, setInput] = useState(value)
    value = input
    return React.createElement(CtrlSafeTextInput, {
      value: input,
      onChange: setInput,
      focus: options.focus ?? true,
      showCursor: true,
      mask: options.mask,
      onSubmit: options.onSubmit,
    })
  }

  const app = render(React.createElement(Probe), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    exitOnCtrlC: false,
    debug: true,
    patchConsole: false,
  })
  let runtimeError: unknown
  void app.waitUntilExit().catch(error => { runtimeError = error })
  await waitForEffects()
  return {
    app: {
      ...app,
      unmount() {
        app.unmount()
        app.cleanup()
        stdout.destroy()
        stderr.destroy()
      },
    },
    stdin,
    value: () => value,
    error: () => runtimeError,
    stderr: () => stderrChunks.join(''),
    output: () => stdoutChunks.join(''),
  }
}

describe('Ctrl-key guard with actual Ink input dispatch', () => {
  it('filters a normalized Ctrl+L before it mutates the controlled value', async () => {
    const probe = await mountProbe()
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('\x0c')
      await waitForEffects()
      expect(probe.value()).toBe('')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('preserves ordinary text and a real trailing l', async () => {
    const probe = await mountProbe({ initial: 'abcl' })
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('x')
      await waitForEffects()
      probe.stdin.write('\x0c')
      await waitForEffects()
      expect(probe.value(), probe.output()).toBe('abclx')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('does not insert control letters when the input focus is inactive', async () => {
    const probe = await mountProbe({ focus: false })
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('\x0c')
      await waitForEffects()
      expect(probe.value()).toBe('')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('keeps the full value when Ctrl+L arrives at a middle cursor', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\x1b[D')
      await send(probe, '\x0c')
      expect(probe.value()).toBe('abc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('does not delete a real trailing c for Ctrl+C', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('\x03')
      await waitForEffects()
      expect(probe.value()).toBe('abc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('keeps the cursor position after filtering Ctrl+L before the next character', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\x1b[D')
      await send(probe, '\x0c')
      await send(probe, 'x')
      expect(probe.value()).toBe('abxc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('handles repeated Ctrl+L without leaving a character behind', async () => {
    const probe = await mountProbe()
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\x0c')
      await send(probe, '\x0c')
      expect(probe.value()).toBe('')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('does not insert raw control bytes delivered in a coalesced chunk', async () => {
    const probe = await mountProbe()
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('\x0c\x0c')
      await waitForEffects()
      // A chunk is not normalized to key.ctrl by Ink; it still must not
      // corrupt a field with terminal control bytes.
      expect(probe.value()).toBe('')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('preserves printable pasted text and its cursor around raw control bytes', async () => {
    const probe = await mountProbe()
    try {
      probe.stdin.write('a\x0cb')
      await waitForEffects()
      expect(probe.value()).toBe('ab')
      await send(probe, 'x')
      expect(probe.value()).toBe('abx')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('clamps repeated left arrows before inserting at the start', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\x1b[D', 100)
      await send(probe, '\x1b[D', 100)
      await send(probe, '\x1b[D', 100)
      await send(probe, '\x1b[D', 100)
      await send(probe, 'x')
      expect(probe.value()).toBe('xabc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('keeps cursor editing keys and navigation from creating control text', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\x1b[D')
      await send(probe, '\x7f')
      expect(probe.value()).toBe('ac')
      await send(probe, '\x1b[C')
      await send(probe, '\x1b[3~')
      expect(probe.value()).toBe('a')
      await send(probe, '\x1b[A')
      await send(probe, '\x1b[B')
      await send(probe, '\x09')
      await send(probe, '\x1b')
      expect(probe.value()).toBe('a')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('renders a masked value without changing the underlying input', async () => {
    const probe = await mountProbe({ initial: 'abc', mask: '*' })
    try {
      expect(probe.error()).toBeUndefined()
      await waitForEffects()
      expect(probe.value()).toBe('abc')
      expect(probe.output()).toContain('***')
      expect(probe.output()).not.toContain('abc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('shows the focused cursor and omits it when focus is inactive', async () => {
    const focused = await mountProbe({ initial: 'abc', focus: true })
    let focusedOutput = ''
    try {
      expect(focused.error()).toBeUndefined()
      focusedOutput = focused.output()
    } finally {
      focused.app.unmount()
      focused.stdin.destroy()
    }

    const unfocused = await mountProbe({ initial: 'abc', focus: false })
    try {
      expect(unfocused.error()).toBeUndefined()
      if (process.env.FORCE_COLOR && process.env.FORCE_COLOR !== '0') {
        expect(focusedOutput).toContain('\u001b[7m')
      }
      // On monochrome terminals, Ink intentionally omits inverse styling
      // and trims trailing blank cells. Check text, not frame counts/timing;
      // the FORCE_COLOR run above provides the positive cursor-style check.
      const stripAnsi = (output: string) => output.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
      expect(stripAnsi(focusedOutput)).toContain('abc')
      expect(stripAnsi(unfocused.output())).toContain('abc')
      expect(unfocused.output()).not.toContain('\u001b[7m')
    } finally {
      unfocused.app.unmount()
      unfocused.stdin.destroy()
    }
  })

  it('submits the unchanged value for Enter', async () => {
    const submitted: string[] = []
    const probe = await mountProbe({ initial: 'abc', onSubmit: (value) => submitted.push(value) })
    try {
      expect(probe.error()).toBeUndefined()
      await send(probe, '\r')
      expect(submitted).toEqual(['abc'])
      expect(probe.value()).toBe('abc')
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })

  it('does not process controls after unmount', async () => {
    const probe = await mountProbe({ initial: 'abc' })
    probe.app.unmount()
    probe.stdin.write('\x0c')
    await waitForEffects()
    expect(probe.value()).toBe('abc')
    probe.stdin.destroy()
  })

  it.each(['l', 'L'] as const)('retains a genuine trailing %s around Ctrl+L', async (character) => {
    const probe = await mountProbe({ initial: character })
    try {
      expect(probe.error()).toBeUndefined()
      probe.stdin.write('\x0c')
      await waitForEffects()
      expect(probe.value()).toBe(character)
    } finally {
      probe.app.unmount()
      probe.stdin.destroy()
    }
  })
})
