import localFont from 'next/font/local'

export const reviewDisplay = localFont({
    src: './fonts/LatexyDisplay600.woff2',
    display: 'swap',
    weight: '600',
    variable: '--font-review-display',
    fallback: ['Arial', 'sans-serif'],
})

export const reviewBody = localFont({
    src: [
        { path: './fonts/LatexyReading400.woff2', weight: '400', style: 'normal' },
        { path: './fonts/LatexyReading500.woff2', weight: '500', style: 'normal' },
        { path: './fonts/LatexyReading600.woff2', weight: '600', style: 'normal' },
    ],
    display: 'swap',
    variable: '--font-review-body',
    fallback: ['Arial', 'sans-serif'],
})

export const reviewFonts = `${reviewDisplay.variable} ${reviewBody.variable}`
