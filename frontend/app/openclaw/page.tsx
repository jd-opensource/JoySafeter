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
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-3 gap-2 transition-all duration-300 relative">
        {!isRightSidebarOpen && (
          <div className="absolute top-4 right-4 z-10">
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 bg-[var(--surface-1)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] shadow-sm border border-[var(--border)] rounded-md backdrop-blur"
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
          'flex flex-col border-l border-[var(--border)] bg-[#fafafa] dark:bg-[var(--surface-1)] transition-all duration-300 ease-in-out shrink-0 relative',
          isRightSidebarOpen ? 'w-[320px] sm:w-[380px]' : 'w-0 overflow-hidden border-l-0 opacity-0'
        )}
      >
        <div className="absolute top-4 right-4 z-10">
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

        <div className="flex-1 overflow-y-auto p-4 sm:p-5 pt-14 sm:pt-14">
          {isRightSidebarOpen && <OpenClawManagement />}
        </div>
      </div>
    </div>
  )
}
