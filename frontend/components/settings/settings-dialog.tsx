'use client'

import { Settings, User, Brain, Box } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'

import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

import { useSession } from '@/lib/auth/auth-client'

import { ModelsPage } from './models-page'
import { ProfilePage } from './profile-page'
import { SandboxesPage } from './sandboxes-page'

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
  icon: any
  label: string
  isActive: boolean
  onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={cn(
      'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
      isActive
        ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
        : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900',
    )}
  >
    <Icon size={16} className={cn(isActive ? 'text-blue-600' : 'text-gray-400')} />
    {label}
  </button>
)

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { t } = useTranslation()
  const { data: session } = useSession()
  const user = session?.user
  const [activeTab, setActiveTab] = useState('profile')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[700px] max-w-5xl flex-row gap-0 overflow-hidden border-0 bg-white p-0 shadow-2xl">
        <DialogTitle className="sr-only">{t('settings.title')}</DialogTitle>
        <DialogDescription className="sr-only">{t('settings.description')}</DialogDescription>

        {/* Sidebar Navigation */}
        <div className="flex w-60 flex-shrink-0 flex-col border-r border-gray-200 bg-gray-50/80 p-4 backdrop-blur-sm">
          <div className="mb-6 px-2">
            <h2 className="text-lg font-bold tracking-tight text-gray-900">
              {t('settings.title')}
            </h2>
          </div>

          <div className="flex-1 space-y-1">
            <div className="mb-2 mt-4 px-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              {t('settings.account')}
            </div>
            <MenuItem
              icon={User}
              label={t('settings.profile')}
              isActive={activeTab === 'profile'}
              onClick={() => setActiveTab('profile')}
            />

            <div className="mb-2 mt-6 px-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              {t('settings.workspace')}
            </div>
            <MenuItem
              icon={Brain}
              label={t('settings.models')}
              isActive={activeTab === 'models'}
              onClick={() => setActiveTab('models')}
            />

            <MenuItem
              icon={Box}
              label={t('settings.sandboxes.title')}
              isActive={activeTab === 'sandboxes'}
              onClick={() => setActiveTab('sandboxes')}
            />
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white">
          {activeTab === 'models' && (
            <div className="flex-1 overflow-hidden p-6">
              <ModelsPage />
            </div>
          )}
          {activeTab === 'profile' && <ProfilePage />}
          {activeTab === 'sandboxes' && (
            <div className="flex-1 overflow-hidden p-6">
              <SandboxesPage />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
