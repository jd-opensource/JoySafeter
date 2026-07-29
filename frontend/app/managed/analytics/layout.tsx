'use client'

import { useTranslation } from '@/lib/i18n'

export default function AnalyticsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { t } = useTranslation()

  return (
    <div>
      {children}
    </div>
  )
}
