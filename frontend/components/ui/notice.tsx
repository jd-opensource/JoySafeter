import { AlertCircle, AlertTriangle, Check, Info } from 'lucide-react'
import type React from 'react'

import { cn } from '@/lib/utils'

export type NoticeVariant = 'info' | 'warning' | 'success' | 'error' | 'default'

interface NoticeProps {
  children: React.ReactNode
  variant?: NoticeVariant
  className?: string
  icon?: React.ReactNode
  title?: string
}

const variantStyles = {
  default: {
    container: 'bg-background border-border',
    text: 'text-foreground',
    title: 'text-foreground font-medium',
    icon: <Info className="mr-2 h-4 w-4 flex-shrink-0 text-muted-foreground" />,
  },
  info: {
    container: 'bg-[var(--brand-50)] border-[var(--brand-200)] dark:bg-[var(--brand-50)] dark:border-[var(--brand-200)]',
    text: 'text-[var(--text-primary)] dark:text-[var(--text-primary)]',
    title: 'text-[var(--text-primary)] dark:text-[var(--text-primary)] font-medium',
    icon: <Info className="mr-2 h-4 w-4 flex-shrink-0 text-[var(--brand-500)]" />,
  },
  warning: {
    container: 'bg-[var(--status-warning-bg)] border-[var(--status-warning-border)] dark:bg-[var(--status-warning-bg)] dark:border-[var(--status-warning-border)]',
    text: 'text-[var(--text-primary)] dark:text-[var(--text-primary)]',
    title: 'text-[var(--text-primary)] dark:text-[var(--text-primary)] font-medium',
    icon: (
      <AlertTriangle className="mr-2 h-4 w-4 flex-shrink-0 text-[var(--status-warning)]" />
    ),
  },
  success: {
    container: 'bg-[var(--status-success-bg)] border-[var(--status-success-border)] dark:bg-[var(--status-success-bg)] dark:border-[var(--status-success-border)]',
    text: 'text-[var(--text-primary)] dark:text-[var(--text-primary)]',
    title: 'text-[var(--text-primary)] dark:text-[var(--text-primary)] font-medium',
    icon: <Check className="mr-2 h-4 w-4 flex-shrink-0 text-[var(--status-success)]" />,
  },
  error: {
    container: 'bg-[var(--status-error-bg)] border-[var(--status-error-border)] dark:bg-[var(--status-error-bg)] dark:border-[var(--status-error-border)]',
    text: 'text-[var(--text-primary)] dark:text-[var(--text-primary)]',
    title: 'text-[var(--text-primary)] dark:text-[var(--text-primary)] font-medium',
    icon: <AlertCircle className="mr-2 h-4 w-4 flex-shrink-0 text-[var(--status-error)]" />,
  },
}

export function Notice({ children, variant = 'info', className, icon, title }: NoticeProps) {
  const styles = variantStyles[variant]

  return (
    <div className={cn('flex rounded-md border p-3', styles.container, className)}>
      <div className="flex items-start">
        {icon !== null && (icon || styles.icon)}
        <div className="flex-1">
          {title && <div className={cn('mb-1', styles.title)}>{title}</div>}
          <div className={cn('text-sm', styles.text)}>{children}</div>
        </div>
      </div>
    </div>
  )
}
