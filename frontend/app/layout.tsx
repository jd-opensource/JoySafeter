import type { Metadata, Viewport } from 'next'
import { headers } from 'next/headers'
import { PublicEnvScript } from 'next-runtime-env'

import { AppShell } from '@/components/app-shell'
import { AuthGuard } from '@/components/auth/auth-guard'
import { Toaster } from '@/components/ui/toaster'
import { I18nProvider } from '@/providers/i18n-provider'
import { NotificationProvider } from '@/providers/notification-provider'
import { PermissionsProvider } from '@/providers/permissions-provider'
import { ProjectProvider } from '@/providers/project-provider'
import { QueryProvider } from '@/providers/query-provider'
import { ThemeProvider } from '@/providers/theme-provider'
import { ZoomPrevention } from '@/providers/zoom-prevention'
import '@/styles/globals.css'

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

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const nonce = (await headers()).get('x-nonce') ?? undefined

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <PublicEnvScript nonce={nonce} />
      </head>
      <body className="font-sans antialiased" suppressHydrationWarning>
        <ThemeProvider nonce={nonce}>
          <I18nProvider>
            <QueryProvider>
              <AuthGuard>
                <ProjectProvider>
                  <PermissionsProvider>
                    <NotificationProvider>
                      <ZoomPrevention />
                      <AppShell>{children}</AppShell>
                      <Toaster />
                    </NotificationProvider>
                  </PermissionsProvider>
                </ProjectProvider>
              </AuthGuard>
            </QueryProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
