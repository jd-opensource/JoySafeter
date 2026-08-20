'use client'

import { Boxes, Check, PlugZap, Puzzle, Wrench } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { normalizeQuickstartAgentBlueprint } from '@/lib/managed/quickstart-agent-blueprint'
import {
  isMcpServerAuthorized,
  type QuickstartAvailableSkill,
} from '@/lib/managed/quickstart-capabilities'
import { cn } from '@/lib/utils'

interface QuickstartCapabilityPlanProps {
  agentConfig?: Record<string, unknown>
  availableSkills: QuickstartAvailableSkill[]
  disabled: boolean
  authorizedMcpServerUrls?: ReadonlySet<string>
  onSkillsChange: (skillIds: string[]) => void
}

const EMPTY_AUTHORIZED_URLS: ReadonlySet<string> = new Set()

function selectedSkillIds(agentConfig?: Record<string, unknown>): string[] {
  if (!Array.isArray(agentConfig?.skills)) return []
  return agentConfig.skills
    .map((item) =>
      item && typeof item === 'object' && !Array.isArray(item)
        ? String((item as Record<string, unknown>).skill_id || '')
        : '',
    )
    .filter(Boolean)
}

function hasConfiguredTools(agentConfig?: Record<string, unknown>): boolean {
  return Array.isArray(agentConfig?.tools) && agentConfig.tools.length > 0
}

function CapabilityStatus({
  tone,
  children,
}: {
  tone: 'ready' | 'warning' | 'muted'
  children: string
}) {
  return (
    <span
      className={cn(
        'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold',
        tone === 'ready' && 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700',
        tone === 'warning' && 'border-amber-500/25 bg-amber-500/10 text-amber-700',
        tone === 'muted' && 'border-border bg-muted text-muted-foreground',
      )}
    >
      {children}
    </span>
  )
}

export function QuickstartCapabilityPlan({
  agentConfig,
  availableSkills,
  disabled,
  authorizedMcpServerUrls,
  onSkillsChange,
}: QuickstartCapabilityPlanProps) {
  const { t } = useTranslation()
  const blueprint = normalizeQuickstartAgentBlueprint(agentConfig)
  const selectedIds = selectedSkillIds(agentConfig)
  const selectedSet = new Set(selectedIds)
  const recommendedSkillIds = new Set(
    blueprint.capabilityPlan.skills.map((item) => item.skillId).filter(Boolean),
  )
  const listedSkills = [
    ...blueprint.capabilityPlan.skills,
    ...availableSkills
      .filter((skill) => !recommendedSkillIds.has(skill.id))
      .map((skill) => ({
        name: skill.display_title || skill.name,
        purpose: skill.description,
        whenUsed: '',
        skillId: skill.id,
        serverUrl: '',
      })),
  ].slice(0, 8)
  const toolItems = blueprint.capabilityPlan.tools.length
    ? blueprint.capabilityPlan.tools
    : blueprint.toolPlan.map((purpose) => ({
        name: t('managed.quickstart.capabilities.builtInToolset'),
        purpose,
        whenUsed: '',
        skillId: '',
        serverUrl: '',
      }))

  const toggleSkill = (skillId: string) => {
    const next = selectedSet.has(skillId)
      ? selectedIds.filter((id) => id !== skillId)
      : [...selectedIds, skillId]
    onSkillsChange(next)
  }

  return (
    <section className="rounded-2xl border border-primary/20 bg-primary/[0.035] p-4">
      <div className="flex items-start gap-2">
        <Boxes className="mt-0.5 h-4 w-4 text-primary" />
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {t('managed.quickstart.capabilities.title')}
          </h3>
          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
            {t('managed.quickstart.capabilities.description')}
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-3">
        <div className="rounded-xl border border-border bg-background/80 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Puzzle className="h-3.5 w-3.5 text-primary" />
            {t('managed.quickstart.capabilities.skills')}
          </div>
          <div className="mt-2 space-y-2">
            {listedSkills.length ? (
              listedSkills.map((item) => {
                const matchedSkill = availableSkills.find(
                  (skill) =>
                    skill.id === item.skillId ||
                    skill.name.toLowerCase() === item.name.toLowerCase() ||
                    skill.display_title?.toLowerCase() === item.name.toLowerCase(),
                )
                const isSelected = Boolean(matchedSkill && selectedSet.has(matchedSkill.id))
                return (
                  <div
                    key={`${item.skillId}:${item.name}`}
                    className="rounded-lg bg-muted/35 p-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-foreground">{item.name}</p>
                        {item.purpose ? (
                          <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                            {item.purpose}
                          </p>
                        ) : null}
                      </div>
                      {isSelected ? (
                        <CapabilityStatus tone="ready">
                          {t('managed.quickstart.capabilities.status.ready')}
                        </CapabilityStatus>
                      ) : matchedSkill ? (
                        <CapabilityStatus tone="warning">
                          {t('managed.quickstart.capabilities.status.needsSelection')}
                        </CapabilityStatus>
                      ) : (
                        <CapabilityStatus tone="muted">
                          {t('managed.quickstart.capabilities.status.unavailable')}
                        </CapabilityStatus>
                      )}
                    </div>
                    {matchedSkill ? (
                      <Button
                        type="button"
                        variant={isSelected ? 'ghost' : 'outline'}
                        size="sm"
                        className="mt-2 h-7 px-2 text-[11px]"
                        disabled={disabled}
                        aria-label={t(
                          isSelected
                            ? 'managed.quickstart.capabilities.removeSkill'
                            : 'managed.quickstart.capabilities.addSkill',
                          { name: matchedSkill.display_title || matchedSkill.name },
                        )}
                        onClick={() => toggleSkill(matchedSkill.id)}
                      >
                        {isSelected ? <Check className="mr-1 h-3 w-3" /> : null}
                        {t(
                          isSelected
                            ? 'managed.quickstart.capabilities.remove'
                            : 'managed.quickstart.capabilities.add',
                        )}
                      </Button>
                    ) : (
                      <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
                        {t('managed.quickstart.capabilities.unavailableHint')}
                      </p>
                    )}
                  </div>
                )
              })
            ) : (
              <p className="text-[11px] leading-4 text-muted-foreground">
                {t('managed.quickstart.capabilities.noSkills')}
              </p>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-background/80 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Wrench className="h-3.5 w-3.5 text-primary" />
            {t('managed.quickstart.capabilities.tools')}
          </div>
          <div className="mt-2 space-y-2">
            {toolItems.length ? (
              toolItems.map((item) => (
                <div key={`${item.name}:${item.purpose}`} className="rounded-lg bg-muted/35 p-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-semibold text-foreground">{item.name}</p>
                    <CapabilityStatus tone={hasConfiguredTools(agentConfig) ? 'ready' : 'warning'}>
                      {t(
                        hasConfiguredTools(agentConfig)
                          ? 'managed.quickstart.capabilities.status.ready'
                          : 'managed.quickstart.capabilities.status.notEnabled',
                      )}
                    </CapabilityStatus>
                  </div>
                  {item.purpose ? (
                    <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                      {item.purpose}
                    </p>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-[11px] leading-4 text-muted-foreground">
                {t('managed.quickstart.capabilities.noTools')}
              </p>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-background/80 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <PlugZap className="h-3.5 w-3.5 text-primary" />
            {t('managed.quickstart.capabilities.mcp')}
          </div>
          <div className="mt-2 space-y-2">
            {blueprint.capabilityPlan.mcpServers.length ? (
              blueprint.capabilityPlan.mcpServers.map((item) => {
                const authorized = isMcpServerAuthorized(
                  item.serverUrl,
                  authorizedMcpServerUrls ?? EMPTY_AUTHORIZED_URLS,
                )
                return (
                  <div
                    key={`${item.name}:${item.serverUrl}`}
                    className="rounded-lg bg-muted/35 p-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-semibold text-foreground">{item.name}</p>
                      <CapabilityStatus tone={authorized ? 'ready' : 'warning'}>
                        {t(
                          authorized
                            ? 'managed.quickstart.capabilities.status.ready'
                            : 'managed.quickstart.capabilities.status.needsAuthorization',
                        )}
                      </CapabilityStatus>
                    </div>
                    {item.purpose ? (
                      <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                        {item.purpose}
                      </p>
                    ) : null}
                  </div>
                )
              })
            ) : (
              <p className="text-[11px] leading-4 text-muted-foreground">
                {t('managed.quickstart.capabilities.noMcp')}
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
