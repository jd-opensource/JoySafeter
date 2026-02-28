'use client'

import { Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { OpenClawManagement } from './components/OpenClawManagement'
import { OpenClawWebUI } from './components/OpenClawWebUI'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'

export default function OpenClawPage() {
  const { t } = useTranslation()

  return (
    <div className="flex h-full flex-col overflow-hidden p-6 gap-2">
      <div className="flex shrink-0 items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
            OpenClaw
          </h1>
        </div>

        <Sheet>
          <SheetTrigger asChild>
            <Button variant="default" className="gap-2 shrink-0 bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-600 dark:text-white dark:hover:bg-blue-700 shadow-sm font-medium h-8 px-3 text-xs border-0 rounded-md">
              <Settings2 className="h-3.5 w-3.5" />
              {t('openclaw.manageInstancesAndDevices')}
            </Button>
          </SheetTrigger>
          <SheetContent className="w-full sm:max-w-md overflow-y-auto">
            <SheetHeader className="mb-6">
              <SheetTitle>{t('openclaw.manageInstancesAndDevices')}</SheetTitle>
            </SheetHeader>
            <OpenClawManagement />
          </SheetContent>
        </Sheet>
      </div>

      <div className="min-h-0 flex-1">
        <OpenClawWebUI />
      </div>
    </div>
  )
}
