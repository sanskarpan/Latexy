import './globals.css'
import type { Metadata } from 'next'
import { NotificationProvider } from '@/components/NotificationProvider'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { AuthSync } from '@/components/AuthSync'
import GlobalHeader from '@/components/GlobalHeader'
import MarketingFooter from '@/components/marketing/MarketingFooter'
import { Toaster } from 'sonner'
import { FeatureFlagsProvider } from '@/contexts/FeatureFlagsContext'

export const metadata: Metadata = {
  title: 'Latexy | Precision Resume Intelligence',
  description: 'Compile, optimize, and score LaTeX resumes with enterprise-grade speed and ATS precision.',
  keywords: 'LaTeX, ATS, resume optimization, AI, job applications',
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
        <NotificationProvider>
          <WebSocketProvider>
            <AuthSync />
            <div className="min-h-screen enterprise-grid noise-overlay flex flex-col">
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
        </FeatureFlagsProvider>
      </body>
    </html>
  )
}
