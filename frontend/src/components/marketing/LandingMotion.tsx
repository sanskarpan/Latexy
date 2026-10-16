'use client'

import { useEffect } from 'react'
import {
    disposeLandingSound,
    initializeLandingSound,
    playLandingSound,
    suspendLandingSound,
} from './landing-sound'

/** Progressive motion: content stays visible without JavaScript or with reduced motion. */
export default function LandingMotion() {
    useEffect(() => {
        initializeLandingSound()
        const sounded = new WeakSet<Element>()
        const onClick = (event: MouseEvent) => {
            const target = event.target instanceof Element ? event.target : null
            const control = target?.closest('button, a, summary, select')
            if (
                !control ||
                control.closest('[data-sound-toggle]') ||
                control.matches(':disabled, [aria-disabled="true"]')
            )
                return
            if (control.closest('.lp-page, .lp-header, .lp-footer')) void playLandingSound()
        }
        const onVisibility = () => {
            if (document.hidden) suspendLandingSound()
        }
        document.addEventListener('click', onClick)
        document.addEventListener('visibilitychange', onVisibility)
        const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
        let observer: IntersectionObserver | undefined
        const sections = Array.from(
            document.querySelectorAll<HTMLElement>(
                '.lp-gallery, .lp-feature-row, .lp-full-section, .lp-footer'
            )
        )
        const configure = () => {
            observer?.disconnect()
            sections.forEach(section => {
                section.removeAttribute('data-inview')
                section.removeAttribute('data-revealed')
            })
            if (preference.matches) return
            observer = new IntersectionObserver(
                entries => {
                    entries.forEach(entry => {
                        const section = entry.target as HTMLElement
                        section.dataset.inview = String(entry.isIntersecting)
                        if (entry.isIntersecting) section.dataset.revealed = 'true'
                        if (entry.isIntersecting && !sounded.has(section)) {
                            sounded.add(section)
                            void playLandingSound('section')
                        }
                    })
                },
                { threshold: 0.12 }
            )
            sections.forEach(section => observer?.observe(section))
        }
        configure()
        preference.addEventListener('change', configure)
        return () => {
            observer?.disconnect()
            preference.removeEventListener('change', configure)
            document.removeEventListener('click', onClick)
            document.removeEventListener('visibilitychange', onVisibility)
            disposeLandingSound()
            sections.forEach(section => {
                section.removeAttribute('data-inview')
                section.removeAttribute('data-revealed')
            })
        }
    }, [])
    return null
}
