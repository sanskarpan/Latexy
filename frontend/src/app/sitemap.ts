import type { MetadataRoute } from 'next'
import { siteUrl } from '@/lib/site-url'

export default function sitemap(): MetadataRoute.Sitemap {
    return [
        '/',
        '/platform',
        '/templates',
        '/pricing',
        '/resources',
        '/faq',
        '/developer',
        '/updates',
    ].map(path => ({
        url: `${siteUrl()}${path === '/' ? '' : path}`,
    }))
}
