/** Bind a synced document only when doing so cannot replace a local draft. */
export function canSeedCollaborationDocument({ localValue, remoteValue, hasHistory, readOnly, paused }: {
  localValue: string; remoteValue: string; hasHistory: boolean; readOnly: boolean; paused: boolean
}): boolean {
  // A peer's intentional delete-all retains Yjs client clocks. Empty source
  // alone does not mean this room has never been initialized.
  return Boolean(localValue) && remoteValue === '' && !hasHistory && !readOnly && !paused
}

export function bindCollaborationWithoutDiscardingDraft<T>({
  hasLocalEdits,
  hasParentDraft = false,
  hasRecoveredDraft = false,
  localValue,
  remoteValue,
  bind,
}: {
  hasLocalEdits: boolean
  hasParentDraft?: boolean
  hasRecoveredDraft?: boolean
  localValue: string
  remoteValue: string
  bind: () => T
}): T | null {
  // A clean join adopts the live CRDT, which can legitimately be ahead of
  // SQL. Only a real local/recovered draft requires equality before binding.
  if ((hasLocalEdits || hasParentDraft || hasRecoveredDraft) && localValue !== remoteValue) return null
  return bind()
}
