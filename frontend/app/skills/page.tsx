'use client'

import { Store, FolderOpen } from 'lucide-react'
import { useState } from 'react'

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'

import SkillsManager from './SkillsManager'
import SkillsStore from './SkillsStore'

export default function SkillsPage() {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('store')

  // handleSkillCopied is now handled by React Query's invalidateQueries in SkillsStore
  const handleSkillCopied = () => {
    // No-op: React Query will automatically refresh data after mutation
  }

  return (
    <div className="flex h-full w-full flex-col">
      <Tabs 
        value={activeTab} 
        onValueChange={setActiveTab}
        className="flex flex-col h-full"
      >
        {/* Tab navigation header */}
        <div className="flex-shrink-0 border-b border-gray-200 bg-white px-6 py-3">
          <TabsList className="h-10 bg-gray-100/80 p-1 rounded-lg">
            <TabsTrigger 
              value="store" 
              className="gap-2 px-4 data-[state=active]:bg-white data-[state=active]:text-emerald-600 data-[state=active]:shadow-sm"
            >
              <Store className="w-4 h-4" />
              {t('skills.marketplace')}
            </TabsTrigger>
            <TabsTrigger 
              value="my" 
              className="gap-2 px-4 data-[state=active]:bg-white data-[state=active]:text-emerald-600 data-[state=active]:shadow-sm"
            >
              <FolderOpen className="w-4 h-4" />
              {t('skills.mySkills')}
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Tab content */}
        <TabsContent value="store" className="flex-1 mt-0 overflow-hidden">
          <SkillsStore onSkillCopied={handleSkillCopied} />
        </TabsContent>

        <TabsContent value="my" className="flex-1 mt-0 overflow-hidden">
          <SkillsManager />
        </TabsContent>
      </Tabs>
    </div>
  )
}
