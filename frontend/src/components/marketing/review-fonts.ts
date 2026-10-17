import localFont from 'next/font/local'

export const reviewDisplay = localFont({
    src: './fonts/HubotSansVF.woff2',
    display: 'swap',
    weight: '200 900',
    variable: '--font-review-display',
    fallback: ['Arial', 'sans-serif'],
})

export const reviewBody = localFont({
    src: './fonts/MonaSansVF.woff2',
    display: 'swap',
    weight: '200 900',
    variable: '--font-review-body',
    fallback: ['Arial', 'sans-serif'],
})

export const reviewFonts = `${reviewDisplay.variable} ${reviewBody.variable}`
