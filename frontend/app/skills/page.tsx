'use client'

import { Store, FolderOpen, Wand2 } from 'lucide-react'
import Link from 'next/link'
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
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex h-full flex-col">
        {/* Tab navigation header */}
        <div className="flex-shrink-0 border-b border-gray-200 bg-white px-6 py-3">
          <div className="flex items-center justify-between">
            <TabsList className="h-10 rounded-lg bg-gray-100/80 p-1">
              <TabsTrigger
                value="store"
                className="gap-2 px-4 data-[state=active]:bg-white data-[state=active]:text-emerald-600 data-[state=active]:shadow-sm"
              >
                <Store className="h-4 w-4" />
                {t('skills.marketplace')}
              </TabsTrigger>
              <TabsTrigger
                value="my"
                className="gap-2 px-4 data-[state=active]:bg-white data-[state=active]:text-emerald-600 data-[state=active]:shadow-sm"
              >
                <FolderOpen className="h-4 w-4" />
                {t('skills.mySkills')}
              </TabsTrigger>
            </TabsList>
            <Link href="/skills/creator">
              <button className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700">
                <Wand2 className="h-4 w-4" />
                {t('skills.aiCreate')}
              </button>
            </Link>
          </div>
        </div>

        {/* Tab content */}
        <TabsContent value="store" className="mt-0 flex-1 overflow-hidden">
          <SkillsStore onSkillCopied={handleSkillCopied} />
        </TabsContent>

        <TabsContent value="my" className="mt-0 flex-1 overflow-hidden">
          <SkillsManager />
        </TabsContent>
      </Tabs>
    </div>
  )
}
