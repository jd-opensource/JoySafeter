'use client'

import { LucideIcon, User } from 'lucide-react'
import { useState } from 'react'

import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { ProfilePage } from './profile-page'

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const MenuItem = ({
  icon: Icon,
  label,
  isActive,
  onClick,
}: {
  icon: LucideIcon
  label: string
  isActive: boolean
  onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={cn(
      'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
      isActive
        ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm ring-1 ring-[var(--border)]'
        : 'text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
    )}
  >
    <Icon
      size={16}
      className={cn(isActive ? 'text-[var(--brand-600)]' : 'text-[var(--text-muted)]')}
    />
    {label}
  </button>
)

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { t } = useTranslation()
  useSession()
  const [activeTab, setActiveTab] = useState('profile')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[600px] max-h-[85vh] max-w-4xl flex-row gap-0 overflow-hidden border-0 bg-[var(--surface-elevated)] p-0 shadow-2xl">
        <DialogTitle className="sr-only">{t('user.settings')}</DialogTitle>
        <DialogDescription className="sr-only">{t('settings.description')}</DialogDescription>

        {/* Sidebar Navigation */}
        <div className="flex w-60 flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-1)] p-4 backdrop-blur-sm">
          <div className="mb-6 px-2">
            <h2 className="text-lg font-bold tracking-tight text-[var(--text-primary)]">
              {t('user.settings')}
            </h2>
          </div>

          <div className="flex-1 space-y-1">
            <div className="mb-2 mt-4 px-3 text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
              {t('settings.account')}
            </div>
            <MenuItem
              icon={User}
              label={t('settings.profile')}
              isActive={activeTab === 'profile'}
              onClick={() => setActiveTab('profile')}
            />
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-[var(--surface-elevated)]">
          {activeTab === 'profile' && <ProfilePage />}
        </div>
      </DialogContent>
    </Dialog>
  )
}
