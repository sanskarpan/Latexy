/** Tiny, opt-in interface cues. No files, network requests or idle audio graph. */
const preferenceKey = 'latexy:landing-sound'
let enabled = false
let context: AudioContext | undefined
let lastCue = -Infinity

export function initializeLandingSound() {
    try {
        enabled = localStorage.getItem(preferenceKey) === 'on'
    } catch {
        enabled = false
    }
    return enabled
}

export function isLandingSoundEnabled() {
    return enabled
}

export function setLandingSoundEnabled(value: boolean) {
    enabled = value
    try {
        localStorage.setItem(preferenceKey, value ? 'on' : 'off')
    } catch {
        /* Session-only preference. */
    }
    if (!value) disposeLandingSound()
}

export async function playLandingSound(kind: 'select' | 'section' = 'select') {
    if (!enabled || document.visibilityState !== 'visible') return
    const now = performance.now()
    if (now - lastCue < (kind === 'section' ? 1400 : 70)) return
    // Scroll never creates or resumes an audio context. Only an enabled click can.
    if (kind === 'section' && context?.state !== 'running') return
    try {
        if (!context) {
            if (!window.AudioContext) return
            context = new AudioContext()
        }
        const current = context
        if (current.state === 'suspended' && kind === 'select') await current.resume()
        if (!enabled || context !== current || current.state !== 'running') return
        lastCue = now
        const oscillator = current.createOscillator()
        const envelope = current.createGain()
        const start = current.currentTime
        const duration = kind === 'section' ? 0.07 : 0.045
        oscillator.type = 'sine'
        oscillator.frequency.setValueAtTime(kind === 'section' ? 520 : 920, start)
        oscillator.frequency.exponentialRampToValueAtTime(
            kind === 'section' ? 390 : 610,
            start + duration
        )
        envelope.gain.setValueAtTime(0, start)
        envelope.gain.linearRampToValueAtTime(kind === 'section' ? 0.009 : 0.025, start + 0.004)
        envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration)
        oscillator.connect(envelope)
        envelope.connect(current.destination)
        oscillator.onended = () => {
            oscillator.disconnect()
            envelope.disconnect()
        }
        oscillator.start(start)
        oscillator.stop(start + duration + 0.01)
    } catch {
        /* Audio availability must never interrupt a product action. */
    }
}

export function suspendLandingSound() {
    if (context?.state === 'running') void context.suspend().catch(() => {})
}

export function disposeLandingSound() {
    const previous = context
    context = undefined
    lastCue = -Infinity
    if (previous && previous.state !== 'closed') void previous.close().catch(() => {})
}
