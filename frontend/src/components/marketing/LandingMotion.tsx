'use client'

import { useEffect } from 'react'

/** Progressive motion: content stays visible without JavaScript or with reduced motion. */
export default function LandingMotion() {
    useEffect(() => {
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
            sections.forEach(section => {
                section.removeAttribute('data-inview')
                section.removeAttribute('data-revealed')
            })
        }
    }, [])
    return null
}
