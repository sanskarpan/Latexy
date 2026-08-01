/**
 * How the editor should react to a y-websocket close code (Feature 40).
 *
 * The collab relay closes the handshake with 4001 (unauthorised), 4003 (no collaborator
 * row) or 4004 (resume missing) — see backend/app/api/ws_routes.py. Only 4003 means the
 * user actually lost edit rights; 4001 in particular is also what a transient DB failure
 * looks like, because _validate_better_auth_session returns None on ANY exception. Losing
 * the relay must therefore never lock the owner out of their own buffer: REST autosave
 * keeps working regardless.
 */

// Handshake rejections. Retrying them indefinitely can never succeed, so y-websocket must
// stop its reconnect loop.
export const TERMINAL_COLLAB_CLOSE_CODES = new Set([4001, 4003, 4004])

// A role change closes the socket so the client re-handshakes with the new role. It is
// deliberately NOT terminal: reconnecting is the whole point, and a promotion that landed
// here as 4003 used to leave the promoted user read-only — with less access than before.
export const COLLAB_CLOSE_ROLE_CHANGED = 4005

// 4001 is not proof of a dead session, so give the handshake a couple of backed-off
// retries before treating it as final.
export const MAX_TRANSIENT_COLLAB_RETRIES = 2

export type CollabCloseAction =
  /** Ordinary transient close — let y-websocket reconnect as usual. */
  | 'ignore'
  /** Possibly-transient handshake rejection — allow one more backed-off attempt. */
  | 'retry'
  /** Give up on the relay, but keep the buffer editable (REST autosave still runs). */
  | 'stop'
  /** Edit rights are genuinely gone — stop and make the buffer read-only. */
  | 'lock'

/** Decide what a y-websocket close code means for the collaboration session. */
export function classifyCollabClose(
  code: number | undefined,
  transientRetries: number,
): CollabCloseAction {
  // Checked before the terminal set so a role change always reconnects, however the
  // reconnect budget has been spent.
  if (code === COLLAB_CLOSE_ROLE_CHANGED) return 'retry'
  if (typeof code !== 'number' || !TERMINAL_COLLAB_CLOSE_CODES.has(code)) return 'ignore'
  if (code === 4003) return 'lock'
  if (code === 4001 && transientRetries < MAX_TRANSIENT_COLLAB_RETRIES) return 'retry'
  return 'stop'
}
