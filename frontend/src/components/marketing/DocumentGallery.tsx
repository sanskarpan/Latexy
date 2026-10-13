'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useState } from 'react'
import { IconArrowRight } from '@tabler/icons-react'

const layouts = ['Classic', 'Modern', 'Minimal'] as const

export default function DocumentGallery() {
    const [layout, setLayout] = useState<(typeof layouts)[number]>('Modern')
    return (
        <div className="lp-gallery">
            <div className="lp-gallery-art" data-layout={layout}>
                <Image
                    className="lp-gallery-light"
                    src="/marketing/document-gallery-light.webp?v=document-house-1"
                    width={1440}
                    height={580}
                    alt="Three sample résumé layouts: Classic, Modern and Minimal, with Modern in the centre"
                    priority
                    sizes="(max-width: 1440px) 100vw, 1440px"
                />
                <Image
                    className="lp-gallery-dark"
                    src="/marketing/document-gallery-dark.webp?v=document-house-1"
                    width={1440}
                    height={580}
                    alt="Three sample résumé layouts: Classic, Modern and Minimal, with Modern in the centre"
                    sizes="(max-width: 1440px) 100vw, 1440px"
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
                            onClick={() => setLayout(name)}
                        >
                            <span>0{index + 1}</span>
                            {name}
                        </button>
                    ))}
                </div>
                <Link href="/templates" aria-label="Explore résumé templates">
                    Explore templates <IconArrowRight size={14} aria-hidden="true" />
                </Link>
            </div>
            <p className="lp-sample-note" aria-live="polite">
                {layout} selected · Sample layouts. Explore the template library to make one yours.
            </p>
        </div>
    )
}
