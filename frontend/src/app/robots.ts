import type { MetadataRoute } from 'next'
import { siteUrl } from '@/lib/site-url'

export default function robots(): MetadataRoute.Robots {
    return {
        rules: {
            userAgent: '*',
            allow: '/',
            disallow: [
                '/api/',
            '/workspace/',
            '/r/',
                '/dashboard',
                '/admin/',
                '/billing',
                '/settings',
                '/login',
                '/signup',
                '/reset-password',
                '/verify-email',
            ],
        },
        sitemap: `${siteUrl()}/sitemap.xml`,
    }
}
