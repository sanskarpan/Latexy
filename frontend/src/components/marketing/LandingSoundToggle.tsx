'use client'

import { useEffect, useState } from 'react'
import { IconVolume, IconVolumeOff } from '@tabler/icons-react'
import { isLandingSoundEnabled, playLandingSound, setLandingSoundEnabled } from './landing-sound'

export default function LandingSoundToggle() {
    const [enabled, setEnabled] = useState(false)
    useEffect(() => setEnabled(isLandingSoundEnabled()), [])
    const Icon = enabled ? IconVolume : IconVolumeOff
    return (
        <button
            type="button"
            className="lp-sound-toggle"
            data-sound-toggle="true"
            aria-label="Interface sounds"
            aria-pressed={enabled}
            onClick={() => {
                const next = !enabled
                setLandingSoundEnabled(next)
                setEnabled(next)
                if (next) void playLandingSound()
            }}
        >
            <Icon size={16} aria-hidden="true" />
            <span>
                Interface sounds <span aria-hidden="true">{enabled ? 'On' : 'Off'}</span>
            </span>
        </button>
    )
}
