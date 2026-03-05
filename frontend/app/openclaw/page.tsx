'use client'

import { PanelRight, Settings2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { OpenClawManagement } from './components/OpenClawManagement'
import { OpenClawWebUI } from './components/OpenClawWebUI'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'

export default function OpenClawPage() {
  const { t } = useTranslation()
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(true)

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-6 gap-2 transition-all duration-300">
        <div className="flex shrink-0 items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
              OpenClaw
            </h1>
          </div>

          {!isRightSidebarOpen && (
            <Button
              variant="default"
              className="gap-2 shrink-0 bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-600 dark:text-white dark:hover:bg-blue-700 shadow-sm font-medium h-8 px-3 text-xs border-0 rounded-md"
              onClick={() => setIsRightSidebarOpen(true)}
            >
              <PanelRight className="h-3.5 w-3.5" />
              {t('openclaw.manageInstancesAndDevices')}
            </Button>
          )}
        </div>

        <div className="min-h-0 flex-1">
          <OpenClawWebUI />
        </div>
      </div>

      {/* Right Sidebar */}
      <div
        className={cn(
          'flex flex-col border-l border-[var(--border)] bg-[#fafafa] dark:bg-[var(--surface-1)] transition-all duration-300 ease-in-out shrink-0',
          isRightSidebarOpen ? 'w-[320px] sm:w-[380px]' : 'w-0 overflow-hidden border-l-0 opacity-0'
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-5 py-4 h-[72px]">
          <h2 className="text-lg font-bold tracking-tight text-[var(--text-primary)]">
            OpenClaw
          </h2>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)]"
            onClick={() => setIsRightSidebarOpen(false)}
            title="Collapse Sidebar"
          >
            <PanelRight className="h-5 w-5" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-5">
          {isRightSidebarOpen && <OpenClawManagement />}
        </div>
      </div>
    </div>
  )
}
