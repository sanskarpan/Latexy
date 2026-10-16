import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let sound: typeof import('../components/marketing/landing-sound')
let stored: string | null
let visible: string
let timestamp: number
let created: FakeAudioContext[]
const parameter = () => ({
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
})
class FakeAudioContext {
    state = 'running'
    currentTime = 0
    destination = {}
    constructor() {
        created.push(this)
    }
    createOscillator = vi.fn(() => ({
        type: '',
        frequency: parameter(),
        connect: vi.fn(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
    }))
    createGain = vi.fn(() => ({ gain: parameter(), connect: vi.fn(), disconnect: vi.fn() }))
    resume = vi.fn(async () => {
        this.state = 'running'
    })
    suspend = vi.fn(async () => {
        this.state = 'suspended'
    })
    close = vi.fn(async () => {
        this.state = 'closed'
    })
}

beforeEach(async () => {
    vi.resetModules()
    stored = null
    visible = 'visible'
    timestamp = 0
    created = []
    vi.stubGlobal('localStorage', {
        getItem: () => stored,
        setItem: (_: string, value: string) => {
            stored = value
        },
    })
    vi.stubGlobal('document', {
        get visibilityState() {
            return visible
        },
    })
    vi.stubGlobal('window', { AudioContext: FakeAudioContext })
    vi.stubGlobal('AudioContext', FakeAudioContext)
    vi.spyOn(performance, 'now').mockImplementation(() => timestamp)
    sound = await import('../components/marketing/landing-sound')
})
afterEach(() => {
    sound.disposeLandingSound()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe('landing sound lifecycle', () => {
    it('allocates no audio on load, ordinary interactions, or scroll before opt-in', async () => {
        expect(sound.initializeLandingSound()).toBe(false)
        await sound.playLandingSound()
        await sound.playLandingSound('section')
        expect(created).toHaveLength(0)
    })
    it('restores the choice without allowing scroll to unlock audio', async () => {
        stored = 'on'
        expect(sound.initializeLandingSound()).toBe(true)
        await sound.playLandingSound('section')
        expect(created).toHaveLength(0)
    })
    it('creates one context after opt-in and bounds cue duration and gain', async () => {
        sound.setLandingSoundEnabled(true)
        await sound.playLandingSound()
        timestamp += 100
        await sound.playLandingSound()
        expect(created).toHaveLength(1)
        expect(created[0].createOscillator).toHaveBeenCalledTimes(2)
        expect(created[0].createOscillator.mock.results[0].value.stop).toHaveBeenCalledWith(0.055)
        expect(
            created[0].createGain.mock.results[0].value.gain.linearRampToValueAtTime
        ).toHaveBeenCalledWith(0.025, 0.004)
    })
    it('rate limits section cues and ignores hidden tabs', async () => {
        sound.setLandingSoundEnabled(true)
        await sound.playLandingSound()
        timestamp = 1500
        await sound.playLandingSound('section')
        timestamp = 1600
        await sound.playLandingSound('section')
        visible = 'hidden'
        timestamp = 4000
        await sound.playLandingSound('section')
        expect(created[0].createOscillator).toHaveBeenCalledTimes(2)
    })
    it('closes immediately on mute and never resumes from scroll after suspension', async () => {
        sound.setLandingSoundEnabled(true)
        await sound.playLandingSound()
        sound.suspendLandingSound()
        timestamp = 2000
        await sound.playLandingSound('section')
        expect(created[0].resume).not.toHaveBeenCalled()
        sound.setLandingSoundEnabled(false)
        expect(created[0].close).toHaveBeenCalledOnce()
        await sound.playLandingSound()
        expect(created).toHaveLength(1)
        expect(stored).toBe('off')
    })
    it('handles blocked storage and unavailable audio without disrupting interactions', async () => {
        vi.stubGlobal('localStorage', {
            getItem() {
                throw Error('blocked')
            },
            setItem() {
                throw Error('blocked')
            },
        })
        expect(sound.initializeLandingSound()).toBe(false)
        sound.setLandingSoundEnabled(true)
        vi.stubGlobal('window', {})
        await expect(sound.playLandingSound()).resolves.toBeUndefined()
        expect(created).toHaveLength(0)
    })
})
