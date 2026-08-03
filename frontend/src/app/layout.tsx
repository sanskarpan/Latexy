import './globals.css'
import type { Metadata, Viewport } from 'next'
import { fontVariables } from './fonts'
import { NotificationProvider } from '@/components/NotificationProvider'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { AuthSync } from '@/components/AuthSync'
import GlobalHeader from '@/components/GlobalHeader'
import EmailVerifyBanner from '@/components/EmailVerifyBanner'
import MarketingFooter from '@/components/marketing/MarketingFooter'
import TenantThemeSync from '@/components/TenantThemeSync'
import WebVitalsReporter from '@/components/WebVitalsReporter'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import AestheticController from '@/components/theme/AestheticController'
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
  // Mode-aware browser chrome (Typeset grounds — the default marketing surface).
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#FBFAF6' },
    { media: '(prefers-color-scheme: dark)', color: '#141310' },
  ],
}

// Runs before first paint so the theme is set with no flash. Reads the dedicated
// theme cookie (distinct from the auth cookie), else the OS preference. Aesthetic
// defaults to 'typeset'; route-group layouts override it per surface.
const THEME_BOOTSTRAP = `(function(){try{
var m=document.cookie.match(/(?:^|; )latexy-theme=(light|dark)/);
var mode=m?m[1]:(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
var r=document.documentElement;
if(!r.getAttribute('data-aesthetic'))r.setAttribute('data-aesthetic','typeset');
r.setAttribute('data-mode',mode);
}catch(e){}})();`

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" data-aesthetic="typeset" className={fontVariables} suppressHydrationWarning>
      <body className="font-sans antialiased">
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
        <ThemeProvider>
        <AestheticController />
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
        </ThemeProvider>
      </body>
    </html>
  )
}
