import { describe, expect, it } from 'vitest'
import {
    isTrackablePath,
    landingPageKey,
    resolveDeviceClass,
    resolveLandingContext,
} from '@/lib/analytics/landing'

describe('landing page keys', () => {
    it('maps only known marketing paths to bounded keys', () => {
        expect(landingPageKey('/')).toBe('home')
        expect(landingPageKey('/try')).toBe('try')
        expect(landingPageKey('/pricing')).toBe('pricing')
        expect(landingPageKey('/templates/software-engineer')).toBe('templates')
        expect(landingPageKey('/resources')).toBe('resources')
        expect(landingPageKey('/platform/')).toBe('platform')
        expect(landingPageKey('/dashboard')).toBeNull()
    })

    it('excludes share, portfolio, workspace, and API surfaces', () => {
        expect(isTrackablePath('/r/secret-token')).toBe(false)
        expect(isTrackablePath('/u/sanskar')).toBe(false)
        expect(isTrackablePath('/share/token')).toBe(false)
        expect(isTrackablePath('/portfolio/person')).toBe(false)
        expect(isTrackablePath('/workspace/550e8400')).toBe(false)
        expect(isTrackablePath('/api/analytics')).toBe(false)
        expect(landingPageKey('/r/secret-token')).toBeNull()
    })
})

describe('landing device class', () => {
    it('compares mobile, tablet, and desktop from the viewport', () => {
        expect(resolveDeviceClass(390)).toBe('mobile')
        expect(resolveDeviceClass(820)).toBe('tablet')
        expect(resolveDeviceClass(1440)).toBe('desktop')
    })
})

describe('landing context', () => {
    it('leaves missing variant data missing instead of imputing a control group', () => {
        const context = resolveLandingContext('/', 390)
        expect(context.pageKey).toBe('home')
        expect(context.deviceClass).toBe('mobile')
        expect(context.experiment).toBeNull()
        expect(context.variant).toBeNull()
    })
})
