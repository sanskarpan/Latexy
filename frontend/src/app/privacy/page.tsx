import type { Metadata } from 'next'
import LegalDoc from '@/components/marketing/LegalDoc'

export const metadata: Metadata = {
  title: 'Privacy Policy — Latexy',
  description: 'How Latexy collects, uses, and safeguards your information.',
  alternates: { canonical: '/privacy' },
  openGraph: {
    title: 'Privacy Policy - Latexy',
    description: 'How Latexy collects, uses, and safeguards your information.',
    url: '/privacy',
    type: 'website',
  },
}

export default function PrivacyPage() {
  return <LegalDoc file="privacy-policy" />
}
