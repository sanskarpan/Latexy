import { useInput } from 'ink'

/**
 * Stop ink-text-input inserting the letter from a ctrl-modified keypress.
 *
 * Ink normalises Ctrl+L into `input='l'` with `key.ctrl` set *before* any
 * onChange runs, so there is no 0x0C left to filter out — the character has
 * already been appended by the time we could see it. Pressing Ctrl+L to clear
 * the transcript therefore dropped a literal "l" into whatever field had focus.
 *
 * Repairing it inside the useInput handler does not work either: Ink calls every
 * registered handler for the same keypress and the order relative to
 * ink-text-input's is not guaranteed, so a functional update can be applied
 * before the append and then clobbered by onChange's direct setState. Schedule
 * the repair after the current keypress has reached every handler. An effect
 * depends on another render and can miss the first keypress in an empty field.
 *
 * Ctrl+C is excluded: ink-text-input deliberately does not append for it, so
 * removing a character there would delete a real trailing "c" the user typed.
 */
export function useCtrlKeyGuard(
  setValue: (update: (previous: string) => string) => void,
  isActive = true,
): void {
  useInput((input, key) => {
    if (key.ctrl && input.length === 1 && input !== 'c') {
      queueMicrotask(() => {
        setValue(v => (v.endsWith(input) ? v.slice(0, -1) : v))
      })
    }
  }, { isActive })
}
