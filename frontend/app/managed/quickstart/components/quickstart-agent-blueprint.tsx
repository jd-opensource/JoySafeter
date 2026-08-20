'use client'

import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileOutput,
  Flag,
  ListChecks,
  Route,
  ShieldCheck,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { QuickstartGenerationStatus } from '@/hooks/managed/use-quickstart-chat'
import { useTranslation } from '@/lib/i18n'
import {
  normalizeQuickstartAgentBlueprint,
  type QuickstartAgentBlueprint,
} from '@/lib/managed/quickstart-agent-blueprint'
import type { QuickstartAvailableSkill } from '@/lib/managed/quickstart-capabilities'

import { QuickstartCapabilityPlan } from './quickstart-capability-plan'

interface QuickstartAgentBlueprintReviewProps {
  agentConfig?: Record<string, unknown>
  generationStatus: QuickstartGenerationStatus
  onShowAdvanced: () => void
  availableSkills?: QuickstartAvailableSkill[]
  disabled?: boolean
  authorizedMcpServerUrls?: ReadonlySet<string>
  isGenericStarter?: boolean
  onSkillsChange?: (skillIds: string[]) => void
}

function hasObjectBlueprint(agentConfig?: Record<string, unknown>): boolean {
  return Boolean(
    agentConfig?.blueprint &&
    typeof agentConfig.blueprint === 'object' &&
    !Array.isArray(agentConfig.blueprint),
  )
}

function BlueprintList({ items }: { items: string[] }) {
  return (
    <ul className="mt-2 space-y-1.5 text-sm leading-5 text-foreground/90">
      {items.map((item) => (
        <li key={item} className="flex gap-2">
          <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

const sections: Array<{
  key: keyof Pick<
    QuickstartAgentBlueprint,
    | 'responsibilities'
    | 'workflow'
    | 'boundaries'
    | 'escalationConditions'
    | 'outputContract'
    | 'successCriteria'
  >
  titleKey: string
  icon: typeof ListChecks
}> = [
  {
    key: 'responsibilities',
    titleKey: 'managed.quickstart.blueprint.responsibilities',
    icon: ListChecks,
  },
  { key: 'workflow', titleKey: 'managed.quickstart.blueprint.workflow', icon: Route },
  { key: 'boundaries', titleKey: 'managed.quickstart.blueprint.boundaries', icon: ShieldCheck },
  {
    key: 'escalationConditions',
    titleKey: 'managed.quickstart.blueprint.escalationConditions',
    icon: AlertTriangle,
  },
  {
    key: 'outputContract',
    titleKey: 'managed.quickstart.blueprint.outputContract',
    icon: FileOutput,
  },
  {
    key: 'successCriteria',
    titleKey: 'managed.quickstart.blueprint.successCriteria',
    icon: CheckCircle2,
  },
]

export function QuickstartAgentBlueprintReview({
  agentConfig,
  generationStatus,
  onShowAdvanced,
  availableSkills = [],
  disabled = false,
  authorizedMcpServerUrls,
  isGenericStarter = false,
  onSkillsChange = () => undefined,
}: QuickstartAgentBlueprintReviewProps) {
  const { t } = useTranslation()
  const blueprint = normalizeQuickstartAgentBlueprint(agentConfig)
  const hasBlueprint = hasObjectBlueprint(agentConfig)
  const isGenerating = generationStatus === 'generating'

  if (!hasBlueprint) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-8 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <ClipboardCheck className="h-6 w-6" />
        </div>
        <h3 className="mt-4 text-base font-semibold text-foreground">
          {t(
            isGenerating
              ? 'managed.quickstart.blueprint.generatingTitle'
              : 'managed.quickstart.blueprint.emptyTitle',
          )}
        </h3>
        <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
          {t(
            isGenerating
              ? 'managed.quickstart.blueprint.generatingDescription'
              : 'managed.quickstart.blueprint.emptyDescription',
          )}
        </p>
        <Button variant="outline" size="sm" className="mt-4" onClick={onShowAdvanced}>
          {t('managed.quickstart.blueprint.viewAdvanced')}
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto px-4 py-4">
      <div className="mx-auto max-w-3xl space-y-4 pb-8">
        {isGenericStarter ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.07] p-3 text-xs leading-5 text-amber-800">
            <p className="font-semibold">{t('managed.quickstart.blueprint.genericStarterTitle')}</p>
            <p className="mt-0.5 text-amber-800/90">
              {t('managed.quickstart.blueprint.genericStarterDescription')}
            </p>
          </div>
        ) : null}
        <section className="rounded-2xl border border-primary/20 bg-primary/[0.04] p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
            <Flag className="h-3.5 w-3.5" />
            {t('managed.quickstart.blueprint.mission')}
          </div>
          <p className="mt-2 text-[15px] leading-6 text-foreground">
            {blueprint.mission || t('managed.quickstart.blueprint.pending')}
          </p>
        </section>

        <QuickstartCapabilityPlan
          agentConfig={agentConfig}
          availableSkills={availableSkills}
          disabled={disabled}
          authorizedMcpServerUrls={authorizedMcpServerUrls}
          onSkillsChange={onSkillsChange}
        />

        <div className="grid gap-3 xl:grid-cols-2">
          {sections.map(({ key, titleKey, icon: Icon }) => (
            <section key={key} className="rounded-2xl border border-border bg-card p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Icon className="h-4 w-4 text-primary" />
                {t(titleKey)}
              </div>
              {blueprint[key].length ? (
                <BlueprintList items={blueprint[key]} />
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">
                  {t('managed.quickstart.blueprint.pending')}
                </p>
              )}
            </section>
          ))}
        </div>

        <section className="rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.05] p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <ClipboardCheck className="h-4 w-4 text-emerald-600" />
            {t('managed.quickstart.blueprint.acceptanceTest')}
          </div>
          <p className="mt-2 rounded-xl border border-emerald-500/15 bg-background/80 px-3 py-2.5 text-sm leading-5 text-foreground">
            {blueprint.acceptanceTest.message || t('managed.quickstart.blueprint.pending')}
          </p>
          {blueprint.acceptanceTest.checks.length ? (
            <BlueprintList items={blueprint.acceptanceTest.checks} />
          ) : null}
        </section>

        {isGenerating ? (
          <p className="text-center text-xs text-muted-foreground">
            {t('managed.quickstart.blueprint.buildingRemaining')}
          </p>
        ) : null}
      </div>
    </div>
  )
}
