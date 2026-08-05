'use client'

import { useTranslation } from '@/lib/i18n'

export function RelativeTime({ date }: { date: string }) {
  const { i18n } = useTranslation()
  const locale = i18n.language?.startsWith('zh') ? 'zh-CN' : 'en-US'
  const formatted = new Date(date).toLocaleString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  return <time dateTime={date}>{formatted}</time>
}
