'use client'

import { useEffect, useState } from 'react'

import AuthBackground from '@/app/(auth)/components/auth-background'
import { useTranslation } from '@/lib/i18n'
import { soehne } from '@/styles/fonts/soehne/soehne'

// Helper to detect if a color is dark
function isColorDark(hexColor: string): boolean {
  const hex = hexColor.replace('#', '')
  const r = Number.parseInt(hex.substr(0, 2), 16)
  const g = Number.parseInt(hex.substr(2, 2), 16)
  const b = Number.parseInt(hex.substr(4, 2), 16)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance < 0.5
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
    // Check if brand background is dark and add class accordingly
    const rootStyle = getComputedStyle(document.documentElement)
    const brandBackground = rootStyle.getPropertyValue('--brand-background-hex').trim()

    if (brandBackground && isColorDark(brandBackground)) {
      document.body.classList.add('auth-dark-bg')
    } else {
      document.body.classList.remove('auth-dark-bg')
    }
  }, [])
  return (
    <AuthBackground>
      <main className="relative flex min-h-screen flex-col text-foreground">
        <div className="relative z-10 flex flex-1 items-center">
          <div className="hidden flex-col justify-center px-12 lg:flex lg:w-[55%] xl:w-[58%] xl:px-20">
            <div className="w-full max-w-lg space-y-8">
              {/* Brand identity */}
              <div className="flex items-center gap-3">
                <div className="relative flex h-12 w-12 flex-shrink-0 items-center justify-center">
                  <div className="absolute inset-0 rounded-xl brand-gradient opacity-100" />
                  <div className="absolute inset-0 rounded-xl brand-gradient opacity-20 blur-md" />
                  <svg
                    className="relative z-10 h-6 w-6 text-white"
                    viewBox="0 0 24 24"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <defs>
                      <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="var(--gradient-brand-from)" />
                        <stop offset="100%" stopColor="var(--gradient-brand-to)" />
                      </linearGradient>
                    </defs>
                    <g transform="translate(12, 12)">
                      <circle r="4.5" fill="white" opacity="0.95" />
                      <path
                        d="M -1.5,-3 L 0,3 L 1.5,-3 M -1,0 L 1,0"
                        stroke="url(#logoGrad)"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    </g>
                    <circle cx="6" cy="6" r="2" fill="white" opacity="0.8" />
                    <circle cx="18" cy="18" r="2" fill="white" opacity="0.8" />
                    <path
                      d="M 8,6 Q 12,12 16,18"
                      stroke="white"
                      strokeWidth="1.2"
                      opacity="0.6"
                      fill="none"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <div>
                  <span
                    className={`${soehne.className} brand-gradient-text text-2xl font-bold`}
                  >
                    JoySafeter
                  </span>
                  <p className="text-xs font-medium text-[var(--text-tertiary)]">
                    Security Intelligence Platform
                  </p>
                </div>
              </div>

              {/* Main title area */}
              <div className="space-y-5">
                <h1
                  className={`${soehne.className} whitespace-nowrap text-2xl font-bold leading-tight tracking-tight text-[var(--text-primary)] xl:text-3xl`}
                  suppressHydrationWarning
                >
                  {mounted ? t('auth.platformTitle') : 'Your Intelligent Security Command Center'}
                </h1>
                <div className="flex items-center gap-2">
                  <span
                    className="rounded-full bg-[var(--brand-100)] px-3 py-1 text-sm font-semibold text-[var(--brand-700)]"
                    suppressHydrationWarning
                  >
                    {mounted
                      ? t('auth.platformSubtitle')
                      : 'Battle-Tested, Intelligent Orchestration'}
                  </span>
                </div>
              </div>

              {/* Key highlights */}
              <div className="space-y-2.5">
                <div className="group flex items-center gap-4">
                  <div className="relative">
                    <div className="h-[3px] w-10 rounded-full bg-gradient-to-r from-[var(--gradient-brand-from)] to-[var(--gradient-brand-accent)] shadow-sm shadow-[color-mix(in_srgb,var(--brand-400)_50%,transparent)]" />
                    <div className="absolute inset-0 h-[3px] w-10 rounded-full bg-gradient-to-r from-[var(--gradient-brand-from)] to-[var(--gradient-brand-accent)] opacity-60 blur-sm" />
                  </div>
                  <p
                    className={`${soehne.className} text-base font-medium text-[var(--text-secondary)] transition-colors group-hover:text-[var(--text-primary)]`}
                    suppressHydrationWarning
                  >
                    {mounted
                      ? t('auth.platformDescription1')
                      : 'Generate Your First Production-Grade Agent in One Minute'}
                  </p>
                </div>
                <div className="group flex items-center gap-4">
                  <div className="relative">
                    <div className="h-[3px] w-10 rounded-full bg-gradient-to-r from-[var(--gradient-secondary-from)] to-[var(--gradient-secondary-to)] shadow-sm shadow-[color-mix(in_srgb,var(--brand-secondary)_50%,transparent)]" />
                    <div className="absolute inset-0 h-[3px] w-10 rounded-full bg-gradient-to-r from-[var(--gradient-secondary-from)] to-[var(--gradient-secondary-to)] opacity-60 blur-sm" />
                  </div>
                  <p
                    className={`${soehne.className} text-base font-medium text-[var(--text-secondary)] transition-colors group-hover:text-[var(--text-primary)]`}
                    suppressHydrationWarning
                  >
                    {mounted
                      ? t('auth.platformDescription2')
                      : 'Turn Security Capabilities into Building Blocks'}
                  </p>
                </div>
              </div>

              {/* Feature tags - 2x2 grid */}
              <div className="grid grid-cols-2 gap-3">
                <div className="group flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 backdrop-blur-sm transition-all hover:border-[color-mix(in_srgb,var(--brand-secondary)_60%,transparent)] hover:bg-[color-mix(in_srgb,var(--brand-50)_40%,transparent)]">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--brand-secondary)] to-[var(--gradient-secondary-to)] shadow-sm">
                    <svg
                      className="h-4 w-4 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
                      />
                    </svg>
                  </div>
                  <span
                    className="text-sm font-semibold text-[var(--text-secondary)] transition-colors group-hover:text-[var(--brand-secondary)]"
                    suppressHydrationWarning
                  >
                    {mounted ? t('auth.featureIntelligentOrchestration') : 'Auto Orchestration'}
                  </span>
                </div>
                <div className="group flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 backdrop-blur-sm transition-all hover:border-[color-mix(in_srgb,var(--brand-400)_60%,transparent)] hover:bg-[color-mix(in_srgb,var(--brand-50)_40%,transparent)]">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-700)] shadow-sm">
                    <svg
                      className="h-4 w-4 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                      />
                    </svg>
                  </div>
                  <span
                    className="text-sm font-semibold text-[var(--text-secondary)] transition-colors group-hover:text-[var(--brand-700)]"
                    suppressHydrationWarning
                  >
                    {mounted ? t('auth.featureSecure') : 'Security Agent'}
                  </span>
                </div>
                <div className="group flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 backdrop-blur-sm transition-all hover:border-[color-mix(in_srgb,var(--gradient-secondary-from)_60%,transparent)] hover:bg-[color-mix(in_srgb,var(--brand-50)_40%,transparent)]">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--gradient-secondary-from)] to-[var(--brand-secondary)] shadow-sm">
                    <svg
                      className="h-4 w-4 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                      />
                    </svg>
                  </div>
                  <span
                    className="text-sm font-semibold text-[var(--text-secondary)] transition-colors group-hover:text-[var(--gradient-secondary-from)]"
                    suppressHydrationWarning
                  >
                    {mounted ? t('auth.featureMultiAgent') : 'Modular'}
                  </span>
                </div>
                <div className="group flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 backdrop-blur-sm transition-all hover:border-[color-mix(in_srgb,var(--brand-600)_60%,transparent)] hover:bg-[color-mix(in_srgb,var(--brand-50)_40%,transparent)]">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--brand-600)] to-[var(--brand-tertiary)] shadow-sm">
                    <svg
                      className="h-4 w-4 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                      />
                    </svg>
                  </div>
                  <span
                    className="text-sm font-semibold text-[var(--text-secondary)] transition-colors group-hover:text-[var(--brand-600)]"
                    suppressHydrationWarning
                  >
                    {mounted ? t('auth.featureEfficient') : 'Self-Iterating'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex w-full items-center justify-center px-4 py-12 sm:px-8 lg:w-[45%] lg:px-12 xl:w-[40%] xl:px-16">
            <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-10 shadow-2xl backdrop-blur-xl">
              {children}
            </div>
          </div>
        </div>
      </main>
    </AuthBackground>
  )
}
