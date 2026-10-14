'use client'

import Image from 'next/image'
import { useState } from 'react'

const layouts = ['Classic', 'Modern', 'Minimal'] as const

export default function DocumentGallery() {
    const [layout, setLayout] = useState<(typeof layouts)[number]>('Classic')
    const [focused, setFocused] = useState(false)
    return (
        <div className="lp-gallery">
            <div className="lp-gallery-art" data-layout={layout} data-focused={focused}>
                <Image
                    className="lp-gallery-light"
                    src="/marketing/document-gallery-light.webp?v=document-house-reference-2"
                    width={1440}
                    height={561}
                    alt="Three sample résumé layouts: Classic, Modern and Minimal, with Modern in the centre"
                    priority
                    quality={100}
                    sizes="(max-width: 1440px) 100vw, 1440px"
                />
                <Image
                    className="lp-gallery-dark"
                    src="/marketing/document-gallery-dark.webp?v=document-house-reference-2"
                    width={1440}
                    height={561}
                    alt="Three sample résumé layouts: Classic, Modern and Minimal, with Modern in the centre"
                    sizes="(max-width: 1440px) 100vw, 1440px"
                    quality={100}
                />
            </div>
            <div className="lp-gallery-controls">
                <span>Choose a layout</span>
                <div role="group" aria-label="Sample résumé layouts">
                    {layouts.map((name, index) => (
                        <button
                            type="button"
                            key={name}
                            aria-pressed={layout === name}
                            onClick={() => {
                                setLayout(name)
                                setFocused(true)
                            }}
                        >
                            <span>0{index + 1}</span>
                            {name}
                        </button>
                    ))}
                </div>
            </div>
            <p className="sr-only" aria-live="polite">
                {layout} selected · Sample layouts. Explore the template library to make one yours.
            </p>
        </div>
    )
}
