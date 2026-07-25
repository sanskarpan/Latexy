import './globals.css'
import type { Metadata, Viewport } from 'next'
import { NotificationProvider } from '@/components/NotificationProvider'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { AuthSync } from '@/components/AuthSync'
import GlobalHeader from '@/components/GlobalHeader'
import EmailVerifyBanner from '@/components/EmailVerifyBanner'
import MarketingFooter from '@/components/marketing/MarketingFooter'
import TenantThemeSync from '@/components/TenantThemeSync'
import WebVitalsReporter from '@/components/WebVitalsReporter'
import { Toaster } from 'sonner'
import { FeatureFlagsProvider } from '@/contexts/FeatureFlagsContext'
import { EntitlementsProvider } from '@/contexts/EntitlementsContext'

export const metadata: Metadata = {
  title: 'Latexy | Precision Resume Intelligence',
  description: 'Compile, optimize, and score LaTeX resumes with enterprise-grade speed and ATS precision.',
  keywords: 'LaTeX, ATS, resume optimization, AI, job applications',
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'Latexy',
  },
}

export const viewport: Viewport = {
  themeColor: '#ff845d',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <FeatureFlagsProvider>
        <EntitlementsProvider>
        <NotificationProvider>
          <WebSocketProvider>
            <AuthSync />
            <TenantThemeSync />
            <WebVitalsReporter />
            <div className="min-h-screen enterprise-grid noise-overlay flex flex-col">
              <EmailVerifyBanner />
              <GlobalHeader />
              <main className="flex-1">
                {children}
              </main>
              <MarketingFooter />
            </div>
            <Toaster
              richColors
              position="bottom-right"
              duration={1500}
              toastOptions={{
                className: 'border border-white/10 bg-zinc-950 text-zinc-100',
              }}
            />
          </WebSocketProvider>
        </NotificationProvider>
        </EntitlementsProvider>
        </FeatureFlagsProvider>
      </body>
    </html>
  )
}
