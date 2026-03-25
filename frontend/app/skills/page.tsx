'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'

import { Plus, Store, FolderOpen } from 'lucide-react'

import { ActiveSkillCreatorRunCard } from './components/ActiveSkillCreatorRunCard'
import { NewSkillDialog } from './components/NewSkillDialog'
import SkillsManager from './SkillsManager'
import SkillsStore from './SkillsStore'

export default function SkillsPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const [activeTab, setActiveTab] = useState('store')
  const [isNewSkillDialogOpen, setIsNewSkillDialogOpen] = useState(false)
  const [requestedAction, setRequestedAction] = useState<'manual' | 'import' | null>(null)

  // handleSkillCopied is now handled by React Query's invalidateQueries in SkillsStore
  const handleSkillCopied = () => {
    // No-op: React Query will automatically refresh data after mutation
  }

  return (
    <div className="flex h-full w-full flex-col">
      <ActiveSkillCreatorRunCard />

      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex h-full flex-col">
        {/* Tab navigation header */}
        <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-3">
          <div className="flex items-center justify-between">
            <TabsList className="h-10 rounded-lg bg-[var(--surface-3)] p-1">
              <TabsTrigger
                value="store"
                className="gap-2 px-4 data-[state=active]:bg-[var(--surface-elevated)] data-[state=active]:text-primary data-[state=active]:shadow-sm"
              >
                <Store className="h-4 w-4" />
                {t('skills.marketplace')}
              </TabsTrigger>
              <TabsTrigger
                value="my"
                className="gap-2 px-4 data-[state=active]:bg-[var(--surface-elevated)] data-[state=active]:text-primary data-[state=active]:shadow-sm"
              >
                <FolderOpen className="h-4 w-4" />
                {t('skills.mySkills')}
              </TabsTrigger>
            </TabsList>
            <button
              onClick={() => setIsNewSkillDialogOpen(true)}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Plus className="h-4 w-4" />
              {t('skills.newSkill', 'New Skill')}
            </button>
          </div>
        </div>

        {/* Tab content */}
        <TabsContent value="store" className="mt-0 flex-1 overflow-hidden">
          <SkillsStore onSkillCopied={handleSkillCopied} />
        </TabsContent>

        <TabsContent value="my" className="mt-0 flex-1 overflow-hidden">
          <SkillsManager
            requestedAction={requestedAction}
            onActionConsumed={() => setRequestedAction(null)}
          />
        </TabsContent>
      </Tabs>

      <NewSkillDialog
        open={isNewSkillDialogOpen}
        onOpenChange={setIsNewSkillDialogOpen}
        onSelectOption={(option) => {
          if (option === 'ai') {
            router.push('/skills/creator')
          } else {
            setActiveTab('my')
            setRequestedAction(option)
          }
        }}
      />
    </div>
  )
}
