'use client'

import { ArrowRight, BarChart3, Bot, ListChecks } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

export function DashboardEmptyState() {
  const { t } = useTranslation()
  const router = useRouter()

  return (
    <div className="flex h-full flex-col items-center justify-center bg-[var(--bg)] px-6">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
          {t('dashboard.onboarding.title')}
        </h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          {t('dashboard.onboarding.subtitle')}
        </p>

        <Button className="mt-6 gap-1.5" onClick={() => router.push('/agents')}>
          {t('dashboard.onboarding.createAgent')}
        </Button>

        {/* Three-step flow */}
        <div className="mt-10 flex items-center justify-center gap-4">
          <div className="flex flex-col items-center gap-1.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--surface-3)]">
              <Bot className="h-5 w-5 text-[var(--text-muted)]" />
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {t('dashboard.onboarding.step1')}
            </span>
          </div>

          <ArrowRight className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />

          <div className="flex flex-col items-center gap-1.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--surface-3)]">
              <ListChecks className="h-5 w-5 text-[var(--text-muted)]" />
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {t('dashboard.onboarding.step2')}
            </span>
          </div>

          <ArrowRight className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />

          <div className="flex flex-col items-center gap-1.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--surface-3)]">
              <BarChart3 className="h-5 w-5 text-[var(--text-muted)]" />
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {t('dashboard.onboarding.step3')}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
