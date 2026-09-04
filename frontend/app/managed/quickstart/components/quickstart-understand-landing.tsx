'use client'

import {
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Database,
  FileText,
  Globe,
  MessageSquare,
  Search,
  Shield,
  Sparkles,
  Users,
} from 'lucide-react'
import type { RefObject } from 'react'

import { Button } from '@/components/ui/button'
import type {
  QuickstartEngineDefault,
  QuickstartRecommendationStatus,
} from '@/hooks/managed/use-quickstart-recommendation'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { QuickstartRecommendationStatusCard } from './quickstart-recommendation-status'

export const QUICKSTART_TEMPLATE_IDS = [
  'blank',
  'researcher',
  'extractor',
  'monitor',
  'support',
  'incident',
  'feedback',
  'retro',
  'escalator',
  'analyst',
] as const

const TEMPLATE_ICONS: Record<string, typeof FileText> = {
  blank: FileText,
  researcher: Globe,
  extractor: Database,
  monitor: Shield,
  support: MessageSquare,
  incident: AlertTriangle,
  feedback: BarChart3,
  retro: Users,
  escalator: ArrowUpRight,
  analyst: Sparkles,
}

const TEMPLATE_META: Record<string, { categoryKey: string; badgeKey: string }> = {
  blank: {
    categoryKey: 'managed.quickstart.templateCategory.basic',
    badgeKey: 'managed.quickstart.templateBadge.basic',
  },
  researcher: {
    categoryKey: 'managed.quickstart.templateCategory.research',
    badgeKey: 'managed.quickstart.templateBadge.web',
  },
  extractor: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.data',
  },
  monitor: {
    categoryKey: 'managed.quickstart.templateCategory.ops',
    badgeKey: 'managed.quickstart.templateBadge.alert',
  },
  support: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.chat',
  },
  incident: {
    categoryKey: 'managed.quickstart.templateCategory.ops',
    badgeKey: 'managed.quickstart.templateBadge.workflow',
  },
  feedback: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.insight',
  },
  retro: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.meeting',
  },
  escalator: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.workflow',
  },
  analyst: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.report',
  },
}

const SECURITY_HIGHLIGHTS = [
  {
    icon: Shield,
    titleKey: 'managed.quickstart.safety.sandbox.title',
    descriptionKey: 'managed.quickstart.safety.sandbox.description',
  },
  {
    icon: Database,
    titleKey: 'managed.quickstart.safety.credentials.title',
    descriptionKey: 'managed.quickstart.safety.credentials.description',
  },
  {
    icon: CheckCircle2,
    titleKey: 'managed.quickstart.safety.permissions.title',
    descriptionKey: 'managed.quickstart.safety.permissions.description',
  },
  {
    icon: FileText,
    titleKey: 'managed.quickstart.safety.audit.title',
    descriptionKey: 'managed.quickstart.safety.audit.description',
  },
]

interface UnderstandEngineOption extends QuickstartEngineDefault {
  engine: { id: string; display_name: string }
}

function TemplateCard({
  templateId,
  onClick,
  disabled,
}: {
  templateId: string
  onClick: () => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const Icon = TEMPLATE_ICONS[templateId] || FileText
  const meta = TEMPLATE_META[templateId]

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'group relative flex min-h-[104px] items-start gap-3 rounded-2xl border border-border bg-background p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/30 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-ring',
        disabled && 'cursor-not-allowed opacity-60 hover:bg-background',
      )}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted transition-colors group-hover:bg-primary/10">
        <Icon className="h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate text-[14px] font-semibold text-foreground">
            {t(`quickstart.template.${templateId}.name`)}
          </div>
          {meta ? (
            <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              {t(meta.badgeKey)}
            </span>
          ) : null}
        </div>
        <div className="mt-0.5 text-[13px] leading-5 text-muted-foreground">
          {t(`quickstart.template.${templateId}.description`)}
        </div>
        <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-muted/40 px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
          <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{t('managed.quickstart.templateSecurityHint')}</span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
          <span className="text-muted-foreground">
            {meta ? t(meta.categoryKey) : t('managed.quickstart.templateCategory.basic')}
          </span>
          <span className="font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
            {t('managed.quickstart.useTemplate')}
          </span>
        </div>
      </div>
    </button>
  )
}

export function QuickstartUnderstandLanding({
  inputRef,
  inputValue,
  onInputChange,
  onSend,
  inputDisabled,
  sendDisabled,
  inputPlaceholderKey,
  showEngineRecommendation,
  recommendationStatus,
  onRetryRecommendation,
  engineOptions,
  recommendedEngineName,
  onConfirmEngine,
  templateSearch,
  onTemplateSearchChange,
  filteredTemplateIds,
  templatesDisabled,
  onTemplateClick,
}: {
  inputRef: RefObject<HTMLInputElement | null>
  inputValue: string
  onInputChange: (value: string) => void
  onSend: () => void
  inputDisabled: boolean
  sendDisabled: boolean
  inputPlaceholderKey: string
  showEngineRecommendation: boolean
  recommendationStatus: QuickstartRecommendationStatus
  onRetryRecommendation: () => void
  engineOptions: UnderstandEngineOption[]
  recommendedEngineName?: string
  onConfirmEngine: (engineId: string) => void
  templateSearch: string
  onTemplateSearchChange: (value: string) => void
  filteredTemplateIds: readonly string[]
  templatesDisabled: boolean
  onTemplateClick: (templateId: string) => void
}) {
  const { t } = useTranslation()

  return (
    <div className="grid min-h-[calc(100vh-160px)] gap-6 lg:h-[calc(100vh-160px)] lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <section className="flex flex-col rounded-2xl border border-border bg-card p-6 lg:min-h-0">
        <div className="flex flex-1 flex-col justify-center">
          <h2 className="whitespace-pre-line text-[32px] font-bold leading-tight tracking-tight text-foreground">
            {t('managed.quickstart.whatToBuild')}
          </h2>
          <p className="mt-3 max-w-[340px] text-[15px] leading-relaxed text-muted-foreground">
            {t('managed.quickstart.subtitle')}
          </p>
          <div className="mt-6 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
            <Shield className="h-3.5 w-3.5" />
            {t('managed.quickstart.secureByDefault')}
          </div>
          <p className="mt-1 max-w-[340px] text-[12px] leading-4 text-muted-foreground">
            {t('managed.quickstart.secureByDefaultHint')}
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {SECURITY_HIGHLIGHTS.map((item) => {
              const Icon = item.icon
              return (
                <div
                  key={item.titleKey}
                  className="border-border/80 rounded-xl border bg-background/70 p-3 shadow-sm"
                >
                  <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    {t(item.titleKey)}
                  </div>
                  <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
                    {t(item.descriptionKey)}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-background px-3 py-2.5">
          <div className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(event) => onInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  onSend()
                }
              }}
              disabled={inputDisabled}
              placeholder={t(inputPlaceholderKey)}
              className="h-8 flex-1 border-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50"
            />
            <button
              type="button"
              onClick={onSend}
              disabled={sendDisabled}
              className={cn(
                'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                sendDisabled
                  ? 'cursor-not-allowed bg-muted-foreground/30 text-white shadow-none'
                  : 'bg-primary hover:bg-primary/90',
              )}
              aria-label={t('managed.quickstart.sendMessage')}
            >
              &uarr;
            </button>
          </div>
          {showEngineRecommendation ? (
            <div className="mt-3 rounded-xl border border-primary/20 bg-primary/5 p-3">
              <p className="text-xs font-semibold text-foreground">
                {t('managed.quickstart.engineRecommendation.title')}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('managed.quickstart.engineRecommendation.description')}
              </p>
              <div className="mt-3">
                <QuickstartRecommendationStatusCard
                  status={recommendationStatus}
                  onRetry={onRetryRecommendation}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {engineOptions.map((option) => (
                  <Button
                    key={option.engine.id}
                    type="button"
                    size="sm"
                    variant={option.recommended ? 'default' : 'outline'}
                    disabled={option.readiness === 'unavailable'}
                    onClick={() => onConfirmEngine(option.engine.id)}
                  >
                    {option.recommended
                      ? t('managed.quickstart.engineRecommendation.useRecommended', {
                          engine: recommendedEngineName || option.engine.display_name,
                        })
                      : option.engine.display_name}
                    <span className="ml-1 text-[10px] opacity-75">
                      <span>
                        {t(
                          option.readiness === 'ready'
                            ? 'managed.quickstart.engineRecommendation.readyNow'
                            : option.readiness === 'setup_required'
                              ? 'managed.quickstart.engineRecommendation.setupRequired'
                              : 'managed.quickstart.engineRecommendation.unavailable',
                        )}
                      </span>
                      {option.readiness === 'ready' ? (
                        <>
                          {' · '}
                          <span>
                            {t('managed.quickstart.engineRecommendation.connectionCount', {
                              count: option.compatibleConnectionCount,
                            })}
                          </span>
                        </>
                      ) : null}
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="overflow-auto rounded-2xl border border-border bg-card p-6 shadow-sm lg:min-h-0 lg:overflow-y-auto">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="text-[17px] font-semibold text-foreground">
              {t('managed.quickstart.browseTemplates')}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('managed.quickstart.templateBrowseHint')}
            </p>
          </div>
          <div className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
            {t('managed.quickstart.templateCount', { count: filteredTemplateIds.length })}
          </div>
        </div>
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={templateSearch}
            onChange={(event) => onTemplateSearchChange(event.target.value)}
            placeholder={t('managed.quickstart.searchTemplates')}
            className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
          />
        </div>
        <div className="grid gap-3 xl:grid-cols-2">
          {filteredTemplateIds.map((templateId) => (
            <TemplateCard
              key={templateId}
              templateId={templateId}
              disabled={templatesDisabled}
              onClick={() => onTemplateClick(templateId)}
            />
          ))}
        </div>
        {filteredTemplateIds.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-muted/20 px-4 py-12 text-center">
            <Search className="mb-3 h-6 w-6 text-muted-foreground" />
            <div className="text-sm font-medium text-foreground">
              {t('managed.quickstart.noTemplatesMatch')}
            </div>
            <button
              type="button"
              onClick={() => onTemplateSearchChange('')}
              className="mt-2 text-xs font-medium text-primary hover:underline"
            >
              {t('managed.quickstart.clearTemplateSearch')}
            </button>
          </div>
        ) : null}
      </section>
    </div>
  )
}
