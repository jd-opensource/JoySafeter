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
        <div className="flex-shrink-0 border-b border-white/[0.06] px-6 py-3">
          <TabsList className="h-10 bg-white/[0.05] border border-white/[0.06] p-1 rounded-xl">
            <TabsTrigger
              value="store"
              className="gap-2 px-4 text-white/50 data-[state=active]:bg-white/[0.08] data-[state=active]:text-violet-300 data-[state=active]:shadow-none"
            >
              <Store className="w-4 h-4" />
              {t('skills.marketplace')}
            </TabsTrigger>
            <TabsTrigger
              value="my"
              className="gap-2 px-4 text-white/50 data-[state=active]:bg-white/[0.08] data-[state=active]:text-violet-300 data-[state=active]:shadow-none"
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
