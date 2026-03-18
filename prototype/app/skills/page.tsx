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
    <div className="executive-page">
      <div className="executive-page-content flex h-full w-full flex-col">
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="flex flex-col h-full"
      >
        <div className="mb-4 space-y-3">
          <div className="executive-kicker">Skills and tooling</div>
          <div>
            <h1 className="font-display text-[2.4rem] leading-none text-[var(--text-primary)]">{t('skills.marketplace')}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--text-secondary)]">
              Review marketplace capabilities, curate internal skills, and standardize execution knowledge across teams.
            </p>
          </div>
        </div>

        <div className="surface-panel flex-shrink-0 px-4 py-4">
          <TabsList className="h-11 rounded-[14px]">
            <TabsTrigger
              value="store"
              className="gap-2 px-4"
            >
              <Store className="w-4 h-4" />
              {t('skills.marketplace')}
            </TabsTrigger>
            <TabsTrigger
              value="my"
              className="gap-2 px-4"
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
    </div>
  )
}
