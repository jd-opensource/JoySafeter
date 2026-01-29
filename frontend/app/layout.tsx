import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { PublicEnvScript } from 'next-runtime-env'

import { AppShell } from '@/components/app-shell'
import { AuthGuard } from '@/components/auth/auth-guard'
import { Toaster } from '@/components/ui/toaster'
import { I18nProvider } from '@/providers/i18n-provider'
import { NotificationProvider } from '@/providers/notification-provider'
import { QueryProvider } from '@/providers/query-provider'
import { ThemeProvider } from '@/providers/theme-provider'
import '@/styles/globals.css'
import { ZoomPrevention } from '@/providers/zoom-prevention'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#cad1e6ff' },
  ],
}

export const metadata: Metadata = {
  title: 'JoySafeter - Multi-Agent Platform',
  description: 'A multi-agent workflow platform powered by AI',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <PublicEnvScript />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} font-sans antialiased`}
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

