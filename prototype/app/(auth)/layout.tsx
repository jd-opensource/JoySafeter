'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import AuthBackground from '@/app/(auth)/components/auth-background'

const features = [
  {
    label: 'Auto Orchestration',
    labelKey: 'auth.featureIntelligentOrchestration',
    gradient: 'from-violet-500 to-indigo-500',
    glow: 'rgba(139,92,246,0.3)',
    svg: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
    ),
  },
  {
    label: 'Security Agent',
    labelKey: 'auth.featureSecure',
    gradient: 'from-sky-500 to-cyan-500',
    glow: 'rgba(14,165,233,0.3)',
    svg: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    ),
  },
  {
    label: 'Modular Design',
    labelKey: 'auth.featureMultiAgent',
    gradient: 'from-emerald-500 to-teal-500',
    glow: 'rgba(52,211,153,0.3)',
    svg: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
    ),
  },
  {
    label: 'Self-Iterating',
    labelKey: 'auth.featureEfficient',
    gradient: 'from-rose-500 to-pink-500',
    glow: 'rgba(244,63,94,0.3)',
    svg: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    ),
  },
]

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const [mounted, setMounted] = useState(false)
  useEffect(() => { queueMicrotask(() => setMounted(true)) }, [])

  return (
    <AuthBackground>
      <main className="relative flex min-h-[100dvh] flex-col text-white">
        <div className="relative z-30 flex flex-1 items-center">

          {/* Left: Brand + Features */}
          <div className="hidden lg:flex lg:w-[55%] xl:w-[58%] flex-col justify-center px-12 xl:px-20">
            <div className="w-full max-w-lg space-y-10">

              {/* Logo */}
              <div className="flex items-center gap-3">
                <div className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-2xl bg-white/5 ring-1 ring-white/10 p-0.5">
                  <div className="flex h-full w-full items-center justify-center rounded-[14px] bg-gradient-to-br from-violet-500 to-indigo-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]">
                    <svg className="h-5 w-5 text-white" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="4" fill="white" opacity="0.95" />
                      <path d="M12 4L12 8M12 16L12 20M4 12L8 12M16 12L20 12" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
                      <circle cx="6" cy="6" r="1.5" fill="white" opacity="0.5" />
                      <circle cx="18" cy="18" r="1.5" fill="white" opacity="0.5" />
                    </svg>
                  </div>
                  <div className="absolute inset-0 rounded-2xl bg-violet-500/25 blur-md -z-10" />
                </div>
                <div>
                  <span className="text-xl font-bold tracking-tight brand-text">JoySafeter</span>
                  <p className="text-xs text-white/35 font-medium">Security Intelligence Platform</p>
                </div>
              </div>

              {/* Headline */}
              <div className="space-y-4">
                <div className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-violet-400 animate-pulse" />
                  <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-violet-300" suppressHydrationWarning>
                    {mounted ? t('auth.platformSubtitle') : 'Battle-Tested Intelligence'}
                  </span>
                </div>

                <h1 className="text-[26px] xl:text-[30px] font-bold leading-tight tracking-tight text-white/90" suppressHydrationWarning>
                  {mounted ? t('auth.platformTitle') : 'Your Intelligent Security\nCommand Center'}
                </h1>

                {/* Accent lines */}
                <div className="space-y-2.5">
                  {[
                    { text: mounted ? t('auth.platformDescription1') : 'Generate Production-Grade Agents in Minutes', gradient: 'from-violet-500 to-indigo-500' },
                    { text: mounted ? t('auth.platformDescription2') : 'Turn Security Capabilities into Building Blocks', gradient: 'from-cyan-500 to-sky-500' },
                  ].map(({ text, gradient }) => (
                    <div key={text} className="flex items-center gap-4">
                      <div className={`h-[2px] w-8 rounded-full bg-gradient-to-r ${gradient} flex-shrink-0`} />
                      <p className="text-[14px] text-white/55 font-medium" suppressHydrationWarning>{text}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Feature grid */}
              <div className="grid grid-cols-2 gap-3">
                {features.map(({ label, labelKey, gradient, glow, svg }) => (
                  <div
                    key={label}
                    className="group flex items-center gap-3 rounded-2xl bg-white/[0.04] border border-white/[0.07] px-4 py-3 transition-all duration-300 hover:border-white/15 hover:bg-white/[0.07]"
                    style={{ '--glow': glow } as React.CSSProperties}
                  >
                    <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${gradient} shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]`}>
                      <svg className="h-4 w-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">{svg}</svg>
                    </div>
                    <span className="text-[13px] font-semibold text-white/60 group-hover:text-white/80 transition-colors" suppressHydrationWarning>
                      {mounted ? t(labelKey) : label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Auth form */}
          <div className="w-full lg:w-[45%] xl:w-[40%] flex items-center justify-center px-4 sm:px-8 lg:px-12 xl:px-16 py-12">
            <div className="w-full max-w-md rounded-2xl bg-white/[0.05] border border-violet-500/20 px-8 py-10 backdrop-blur-xl shadow-[0_0_60px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.08)]">
              {children}
            </div>
          </div>

        </div>
      </main>
    </AuthBackground>
  )
}
