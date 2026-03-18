'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import AuthBackground from '@/app/(auth)/components/auth-background'

const features = [
  {
    label: 'Auto Orchestration',
    labelKey: 'auth.featureIntelligentOrchestration',
    accent: 'Operational',
    svg: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
      />
    ),
  },
  {
    label: 'Security Agent',
    labelKey: 'auth.featureSecure',
    accent: 'Risk',
    svg: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
      />
    ),
  },
  {
    label: 'Modular Design',
    labelKey: 'auth.featureMultiAgent',
    accent: 'Systems',
    svg: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
      />
    ),
  },
  {
    label: 'Self-Iterating',
    labelKey: 'auth.featureEfficient',
    accent: 'Scale',
    svg: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
      />
    ),
  },
]

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
  }, [])

  return (
    <AuthBackground>
      <main className="relative flex min-h-[100dvh] flex-col text-[var(--text-primary)]">
        <div className="relative z-30 flex flex-1 items-center">
          <div className="hidden lg:flex lg:w-[56%] xl:w-[58%] flex-col justify-center px-12 xl:px-20">
            <div className="w-full max-w-2xl space-y-10">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-[16px] border border-[var(--border-strong)] bg-[linear-gradient(180deg,var(--brand-400),var(--brand-600))] shadow-[0_16px_24px_rgba(36,56,77,0.16)]">
                  <svg className="h-5 w-5 text-[var(--text-inverse)]" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="4" fill="currentColor" opacity="0.94" />
                    <path d="M12 4L12 8M12 16L12 20M4 12L8 12M16 12L20 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
                    <circle cx="6" cy="6" r="1.5" fill="currentColor" opacity="0.5" />
                    <circle cx="18" cy="18" r="1.5" fill="currentColor" opacity="0.5" />
                  </svg>
                </div>
                <div>
                  <span className="text-xl font-semibold tracking-tight text-[var(--text-primary)]">JoySafeter</span>
                  <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                    Executive Security Intelligence Platform
                  </p>
                </div>
              </div>

              <div className="space-y-5">
                <div className="executive-kicker" suppressHydrationWarning>
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-500)]" />
                  <span>{mounted ? t('auth.platformSubtitle') : 'Boardroom-grade orchestration'}</span>
                </div>

                <div className="space-y-4">
                  <h1 className="font-display text-[clamp(2.8rem,4.8vw,4.9rem)] leading-[0.93] tracking-[-0.05em] text-[var(--text-primary)]" suppressHydrationWarning>
                    {mounted ? t('auth.platformTitle') : 'Security operations built for executive trust.'}
                  </h1>
                  <p className="max-w-xl text-[16px] leading-7 text-[var(--text-secondary)]" suppressHydrationWarning>
                    {mounted ? t('auth.platformDescription1') : 'Coordinate agents, intelligence, and evaluation workflows from one disciplined operating surface designed for enterprise leaders.'}
                  </p>
                  <div className="executive-rule" />
                  <p className="max-w-lg text-[14px] leading-6 text-[var(--text-secondary)]" suppressHydrationWarning>
                    {mounted ? t('auth.platformDescription2') : 'Move from isolated capabilities to an integrated command layer for security execution, governance, and measurable progress.'}
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                  <div className="surface-panel px-6 py-6">
                    <div className="section-label">Executive Summary</div>
                    <div className="mt-5 grid gap-5 sm:grid-cols-3">
                      {[
                        ['Coverage', '12', 'Active operating domains'],
                        ['Control', '24/7', 'Continuous orchestration cadence'],
                        ['Readiness', '99.3%', 'Operational platform availability'],
                      ].map(([label, value, copy]) => (
                        <div key={label} className="space-y-2">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">{label}</div>
                          <div className="metric-value text-[2rem]">{value}</div>
                          <p className="text-[12px] leading-5 text-[var(--text-secondary)]">{copy}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="surface-panel-flat px-5 py-5">
                    <div className="section-label">What This Platform Enables</div>
                    <div className="mt-4 space-y-3">
                      {features.map(({ label, labelKey, accent, svg }) => (
                        <div key={label} className="flex items-start gap-3 rounded-[14px] border border-[var(--divider)] bg-[rgba(255,255,255,0.5)] px-4 py-3">
                          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--brand-500)]">
                            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">{svg}</svg>
                          </div>
                          <div className="space-y-1">
                            <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">{accent}</div>
                            <div className="text-[13px] font-semibold text-[var(--text-primary)]" suppressHydrationWarning>
                              {mounted ? t(labelKey) : label}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="w-full lg:w-[44%] xl:w-[40%] flex items-center justify-center px-4 sm:px-8 lg:px-12 xl:px-16 py-12">
            <div className="surface-panel relative w-full max-w-md overflow-hidden px-8 py-9">
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--brand-indigo)] to-transparent" />
              {children}
            </div>
          </div>
        </div>
      </main>
    </AuthBackground>
  )
}
