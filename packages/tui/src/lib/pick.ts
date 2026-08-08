/**
 * Ask the user to choose something in an overlay, and await the answer.
 *
 * Overlays were fire-and-forget: `openOverlay(element)` took a pre-built node
 * with no props and no way to hand a value back, so `ResumePicker` could only
 * persist a default rather than answer "which resume did you mean?". Every
 * command that operates on a resume needs exactly that, so the picker is
 * promoted here into a reusable prompt.
 *
 * Cancelling (Esc) resolves `null` rather than rejecting — a user backing out is
 * an ordinary outcome, not an error, and callers should simply stop.
 */
import { closeOverlay } from '../stores/overlay.js'

export interface PickerItem {
  /** Value handed back to the caller. */
  id: string
  /** Primary line shown in the list. */
  label: string
  /** Optional dimmed detail shown after the label. */
  detail?: string
}

type Resolver = (value: string | null) => void

let pending: Resolver | null = null

/** Register the resolver for an in-flight pick. Used by the picker overlay. */
export function beginPick(resolve: Resolver): void {
  // A second prompt while one is open would strand the first caller forever.
  // Resolve it as cancelled so its `await` returns instead of hanging.
  if (pending) pending(null)
  pending = resolve
}

/** Settle the in-flight pick. Safe to call when nothing is pending. */
export function settlePick(value: string | null): void {
  const resolve = pending
  pending = null
  closeOverlay()
  if (resolve) resolve(value)
}

/** Whether a pick is currently awaiting an answer. */
export function pickPending(): boolean {
  return pending !== null
}
