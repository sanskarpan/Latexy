import { afterEach, describe, expect, it, vi } from 'vitest'
import { generateSessionId } from '@/lib/device-tracking'

describe('device tracking session identifiers', () => {
    afterEach(() => vi.unstubAllGlobals())

    it('uses the platform CSPRNG for a fixed 128-bit identifier', () => {
        const getRandomValues = vi.fn((bytes: Uint8Array) => {
            bytes.fill(0xab)
            return bytes
        })
        vi.stubGlobal('crypto', { getRandomValues })

        expect(generateSessionId()).toBe('ab'.repeat(16))
        expect(getRandomValues).toHaveBeenCalledOnce()
    })
})
