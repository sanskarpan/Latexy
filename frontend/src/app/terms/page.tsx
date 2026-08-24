import type { Metadata } from 'next'
import LegalDoc from '@/components/marketing/LegalDoc'

export const metadata: Metadata = {
  title: 'Terms of Service — Latexy',
  description: 'The terms that govern your use of Latexy.',
}

export default function TermsPage() {
  return <LegalDoc file="terms-of-service" />
}
