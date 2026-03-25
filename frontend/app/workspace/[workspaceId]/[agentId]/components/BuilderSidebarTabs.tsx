'use client'

import { Sparkles, Wrench } from 'lucide-react'

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'

import { ComponentsSidebar } from './ComponentsSidebar'
import { CopilotPanel } from './CopilotPanel'

export function BuilderSidebarTabs() {
  const { t } = useTranslation()

  return (
    <Tabs defaultValue="copilot" className="flex h-full flex-col">
      {/* Tab Headers */}
      <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface-2)] px-5 pb-0 pt-0">
        <TabsList className="flex h-auto w-full space-x-6 bg-transparent p-0">
          <TabsTrigger
            value="copilot"
            className="relative flex cursor-pointer flex-col items-start gap-0 rounded-none border-b-2 border-transparent bg-transparent px-0 pb-2 pt-1 text-[13px] font-semibold tracking-tight shadow-none transition-all duration-200 ease-out data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=inactive]:font-medium data-[state=active]:text-[var(--text-primary)] data-[state=inactive]:text-[var(--text-tertiary)] data-[state=inactive]:hover:text-[var(--text-secondary)]"
          >
            <span className="flex items-center gap-2.5">
              <Sparkles size={15} strokeWidth={2.5} className="flex-shrink-0" />
              <span className="whitespace-nowrap">
                {t('workspace.copilot', { defaultValue: 'Copilot' })}
              </span>
            </span>
            <span className="pl-[23px] text-[10px] font-normal leading-tight text-[var(--text-tertiary)]">
              {t('workspace.copilotSubtitle')}
            </span>
          </TabsTrigger>
          <TabsTrigger
            value="components"
            className="relative flex cursor-pointer items-center gap-2.5 rounded-none border-b-2 border-transparent bg-transparent px-0 pb-2.5 pt-1 text-[13px] font-semibold tracking-tight shadow-none transition-all duration-200 ease-out data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=inactive]:font-medium data-[state=active]:text-[var(--text-primary)] data-[state=inactive]:text-[var(--text-tertiary)] data-[state=inactive]:hover:text-[var(--text-secondary)]"
          >
            <Wrench size={15} strokeWidth={2.5} className="flex-shrink-0" />
            <span className="whitespace-nowrap">{t('workspace.components')}</span>
          </TabsTrigger>
        </TabsList>
      </div>

      {/* Tab Contents */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <TabsContent
          value="copilot"
          className="m-0 h-full p-0 focus-visible:outline-none data-[state=active]:block data-[state=inactive]:hidden"
        >
          <div className="h-full">
            <CopilotPanel />
          </div>
        </TabsContent>
        <TabsContent
          value="components"
          className="m-0 h-full p-0 focus-visible:outline-none data-[state=active]:block data-[state=inactive]:hidden"
        >
          <div className="h-full">
            <ComponentsSidebar showHeader={false} />
          </div>
        </TabsContent>
      </div>
    </Tabs>
  )
}
