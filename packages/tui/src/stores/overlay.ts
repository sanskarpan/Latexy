import { atom, computed } from 'nanostores'
import type { ReactNode } from 'react'

export const $overlay = atom<ReactNode | null>(null)
export const $isBlocked = computed($overlay, o => o !== null)

export function openOverlay(node: ReactNode): void {
  $overlay.set(node)
}

export function closeOverlay(): void {
  $overlay.set(null)
}
