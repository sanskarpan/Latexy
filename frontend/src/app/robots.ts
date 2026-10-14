import type { MetadataRoute } from 'next'
import { siteUrl } from '@/lib/site-url'
import { NON_INDEXABLE_APP_ROOTS } from '@/lib/search-indexing'

export default function robots(): MetadataRoute.Robots {
    return {
        rules: {
            userAgent: '*',
            allow: '/',
            disallow: [
                '/api/',
                '/r/',
                ...NON_INDEXABLE_APP_ROOTS,
            ],
        },
        sitemap: `${siteUrl()}/sitemap.xml`,
    }
}
