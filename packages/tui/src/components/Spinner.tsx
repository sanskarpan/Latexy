import React, { useEffect, useRef, useState } from 'react'
import { Text } from 'ink'

/**
 * A braille spinner, local rather than from `@inkjs/ui`.
 *
 * `@inkjs/ui`'s Spinner rendered nothing under Ink 7 on Linux and took its whole
 * subtree with it — ToolUseCard's entire running branch came out as `"\n"`, so the
 * tool name vanished too. It passed on macOS, which is why the Ink 7 upgrade looked
 * clean locally and only failed in CI. The package has had no release since
 * 2024-05 and this was its only use in the codebase, so replacing it removes the
 * dependency rather than pinning around it.
 *
 * Frame 0 renders on the first paint, deliberately: a spinner whose first frame is
 * empty is indistinguishable from a broken one, both to a user and to a test.
 */
const FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'] as const
const INTERVAL_MS = 80

interface Props {
  /** Defaults to the accent colour used elsewhere for in-progress work. */
  color?: string
}

export function Spinner({ color = 'cyan' }: Props): React.ReactElement {
  const [frame, setFrame] = useState(0)
  // React StrictMode mounts effects twice, which would leave two intervals running
  // and spin at double speed. Bumping a generation on each mount and checking it
  // inside the callback keeps only the live one advancing.
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    const mine = generation.current
    const timer = setInterval(() => {
      if (generation.current !== mine) return
      setFrame(f => (f + 1) % FRAMES.length)
    }, INTERVAL_MS)
    return () => clearInterval(timer)
  }, [])

  return <Text color={color}>{FRAMES[frame]}</Text>
}

/** Exposed so tests can assert a spinner is present without hardcoding a glyph. */
export const SPINNER_FRAMES = FRAMES
