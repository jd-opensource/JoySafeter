'use client'

import { PanelRight } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { OpenClawManagement } from './components/OpenClawManagement'
import { OpenClawWebUI } from './components/OpenClawWebUI'

export default function OpenClawPage() {
  const { t } = useTranslation()
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(true)

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Main Content Area */}
      <div className="relative flex min-w-0 flex-1 flex-col gap-2 overflow-hidden p-3 transition-all duration-300">
        {!isRightSidebarOpen && (
          <div className="absolute right-4 top-4 z-10">
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 rounded-md border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-secondary)] shadow-sm backdrop-blur hover:text-[var(--text-primary)]"
              onClick={() => setIsRightSidebarOpen(true)}
              title={t('openclaw.manageInstancesAndDevices')}
            >
              <PanelRight className="h-4 w-4" />
            </Button>
          </div>
        )}

        <div className="min-h-0 flex-1">
          <OpenClawWebUI />
        </div>
      </div>

      {/* Right Sidebar */}
      <div
        className={cn(
          'relative flex shrink-0 flex-col border-l border-[var(--border)] bg-[var(--surface-2)] transition-all duration-300 ease-in-out dark:bg-[var(--surface-1)]',
          isRightSidebarOpen
            ? 'w-[320px] sm:w-[380px]'
            : 'w-0 overflow-hidden border-l-0 opacity-0',
        )}
      >
        <div className="absolute right-4 top-4 z-10">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]"
            onClick={() => setIsRightSidebarOpen(false)}
            title="Collapse Sidebar"
          >
            <PanelRight className="h-5 w-5" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 pt-14 sm:p-5 sm:pt-14">
          {isRightSidebarOpen && <OpenClawManagement />}
        </div>
      </div>
    </div>
  )
}
