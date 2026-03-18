import type { Metadata, Viewport } from 'next'
import { PublicEnvScript } from 'next-runtime-env'

import { AppShell } from '@/components/app-shell'
import { AuthGuard } from '@/components/auth/auth-guard'
import { Toaster } from '@/components/ui/toaster'
import { I18nProvider } from '@/providers/i18n-provider'
import { NotificationProvider } from '@/providers/notification-provider'
import { QueryProvider } from '@/providers/query-provider'
import { ThemeProvider } from '@/providers/theme-provider'
import { season } from '@/styles/fonts/season/season'
import { soehne } from '@/styles/fonts/soehne/soehne'
import '@/styles/globals.css'
import { ZoomPrevention } from '@/providers/zoom-prevention'

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f4f1ea' },
    { media: '(prefers-color-scheme: dark)', color: '#f4f1ea' },
  ],
}

export const metadata: Metadata = {
  title: 'JoySafeter | Executive Security Intelligence',
  description: 'Executive-grade multi-agent security operations platform',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh" suppressHydrationWarning>
      <head>
        <PublicEnvScript />
      </head>
      <body
        className={`${soehne.variable} ${season.variable} font-sans antialiased bg-[var(--bg)] text-[var(--text-primary)]`}
        suppressHydrationWarning
      >
        <ThemeProvider>
          <I18nProvider>
            <QueryProvider>
              <AuthGuard>
                <NotificationProvider>
                  <ZoomPrevention />
                  <AppShell>
                    {children}
                  </AppShell>
                  <Toaster />
                </NotificationProvider>
              </AuthGuard>
            </QueryProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
