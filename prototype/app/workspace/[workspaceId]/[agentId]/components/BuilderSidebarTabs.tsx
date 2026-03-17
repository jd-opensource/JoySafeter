'use client'

import { Sparkles, Wrench } from 'lucide-react'
import React from 'react'

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'

import { ComponentsSidebar } from './ComponentsSidebar'
import { CopilotPanel } from './CopilotPanel'

export const BuilderSidebarTabs: React.FC = () => {
  const { t } = useTranslation()

  return (
    <Tabs defaultValue="copilot" className="flex flex-col h-full">
      {/* Tab Headers */}
      <div className="flex-shrink-0 border-b border-gray-200/60 bg-white px-5 pt-0 pb-0">
        <TabsList className="w-full flex space-x-6 h-auto bg-transparent p-0">
          <TabsTrigger
            value="copilot"
            className="relative flex flex-col items-start gap-0 px-0 pb-2 pt-1 text-[13px] font-semibold tracking-tight rounded-none border-b-2 border-transparent
              data-[state=active]:text-gray-900 data-[state=active]:border-blue-500 data-[state=active]:bg-transparent
              data-[state=inactive]:text-gray-500 data-[state=inactive]:hover:text-gray-700
              transition-all duration-200 ease-out bg-transparent shadow-none cursor-pointer
              data-[state=active]:font-semibold data-[state=inactive]:font-medium"
          >
            <span className="flex items-center gap-2.5">
              <Sparkles size={15} strokeWidth={2.5} className="flex-shrink-0" />
              <span className="whitespace-nowrap">{t('workspace.copilot', { defaultValue: 'Copilot' })}</span>
            </span>
            <span className="text-[10px] font-normal text-gray-500 pl-[23px] leading-tight">
              {t('workspace.copilotSubtitle')}
            </span>
          </TabsTrigger>
          <TabsTrigger
            value="components"
            className="relative flex items-center gap-2.5 px-0 pb-2.5 pt-1 text-[13px] font-semibold tracking-tight rounded-none border-b-2 border-transparent
              data-[state=active]:text-gray-900 data-[state=active]:border-blue-500 data-[state=active]:bg-transparent
              data-[state=inactive]:text-gray-500 data-[state=inactive]:hover:text-gray-700
              transition-all duration-200 ease-out bg-transparent shadow-none cursor-pointer
              data-[state=active]:font-semibold data-[state=inactive]:font-medium"
          >
            <Wrench size={15} strokeWidth={2.5} className="flex-shrink-0" />
            <span className="whitespace-nowrap">{t('workspace.components')}</span>
          </TabsTrigger>
        </TabsList>
      </div>

      {/* Tab Contents */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <TabsContent
          value="copilot"
          className="h-full m-0 p-0 focus-visible:outline-none data-[state=active]:block data-[state=inactive]:hidden"
        >
          <div className="h-full">
            <CopilotPanel />
          </div>
        </TabsContent>
        <TabsContent
          value="components"
          className="h-full m-0 p-0 focus-visible:outline-none data-[state=active]:block data-[state=inactive]:hidden"
        >
          <div className="h-full">
            <ComponentsSidebar showHeader={false} />
          </div>
        </TabsContent>
      </div>
    </Tabs>
  )
}
