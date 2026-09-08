'use client'

import { AlertTriangle, CheckCircle2, Loader2, Shield } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { QuickstartProveFlowController } from '@/hooks/managed/use-quickstart-prove-flow'
import { useTranslation } from '@/lib/i18n'
import { shortEntityId } from '@/lib/managed/entity-id-display'
import { QUICKSTART_STEP, type QuickstartStepId } from '@/lib/managed/quickstart-flow'
import type { QuickstartLaunchAssurance } from '@/lib/managed/quickstart-launch-assurance'
import { quickstartResourceEndpoint } from '@/lib/managed/quickstart-resource-contract'
import { cn } from '@/lib/utils'
import type { AgentId, CredentialGroupId, EnvironmentId } from '@/types/entity-id'

import { QuickstartCompletionDescription } from './quickstart-completion-copy'
import { QuickstartStepDoneBadge } from './quickstart-flow-primitives'

interface QuickstartProvePlan {
  engineId: string | null
  engineName: string
  hasModelConnection: boolean
  modelCredentialName: string
  agentId: AgentId | null
  environmentId: EnvironmentId | null
  credentialGroupId: CredentialGroupId | null
}

export function QuickstartProvePhase({
  currentStep,
  completed,
  curl,
  controller,
  plan,
  assurance,
  readOnly,
  onEdit,
}: {
  currentStep: QuickstartStepId
  completed: boolean
  curl?: string
  controller: QuickstartProveFlowController
  plan: QuickstartProvePlan
  assurance: QuickstartLaunchAssurance
  readOnly: boolean
  onEdit: (step: 1 | 2 | 4 | 5) => void
}) {
  const { t } = useTranslation()
  if (currentStep !== QUICKSTART_STEP.SESSION) return null

  if (completed && curl) {
    return (
      <>
        <QuickstartStepDoneBadge
          label={t('managed.quickstart.stepComplete.sessionStarted')}
          curl={curl}
          endpoint={quickstartResourceEndpoint(QUICKSTART_STEP.SESSION)}
        />
        {controller.trial.status === 'idle' ? (
          <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
            {t('managed.quickstart.sessionLiveHint')}
          </p>
        ) : null}
        {controller.trial.status === 'testing' ? (
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>{t('managed.quickstart.agentRunningHint')}</span>
          </div>
        ) : null}
        {controller.trial.status === 'response_received' ? (
          <QuickstartCompletionDescription
            step={QUICKSTART_STEP.SESSION}
            className="text-[13px] leading-6 text-foreground/80"
          />
        ) : null}
      </>
    )
  }

  if (completed) return null

  const summaryKey = assurance.needsHardening ? 'hardening' : 'ready'

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-foreground">
        {t('managed.quickstart.readyToStart')}
      </p>
      <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
        <div className="flex items-start gap-2">
          <Shield className="mt-0.5 h-4 w-4 text-primary" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">
              {t('managed.quickstart.securityPlan.title')}
            </p>
            <p className="text-xs leading-5 text-muted-foreground">
              {t('managed.quickstart.securityPlan.description')}
            </p>
          </div>
        </div>
        <div
          className={cn(
            'mt-3 rounded-lg border px-3 py-2 text-xs',
            assurance.needsHardening
              ? 'border-amber-200 bg-amber-50 text-amber-800'
              : 'border-emerald-200 bg-emerald-50 text-emerald-800',
          )}
        >
          <div className="flex items-start gap-2">
            {assurance.needsHardening ? (
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            )}
            <div className="space-y-0.5">
              <p className="font-semibold">
                {t(`managed.quickstart.securityPlan.summary.${summaryKey}`)}
              </p>
              <p className="leading-5">
                {t(`managed.quickstart.securityPlan.summary.${summaryKey}Description`)}
              </p>
            </div>
          </div>
        </div>
        <div className="mt-3 space-y-2 text-xs">
          <SecurityPlanRow
            label={t('managed.quickstart.securityPlan.runtime')}
            hint={t('managed.quickstart.securityPlan.hint.runtime')}
            tone={plan.engineId ? 'ready' : 'warning'}
            status={t(
              plan.engineId
                ? 'managed.quickstart.securityPlan.status.ready'
                : 'managed.quickstart.securityPlan.status.required',
            )}
            value={plan.engineName || t('managed.quickstart.securityPlan.notConfigured')}
            action={t('managed.quickstart.securityPlan.action.changeRuntime')}
            disabled={readOnly}
            onEdit={() => onEdit(QUICKSTART_STEP.ENGINE)}
          />
          <SecurityPlanRow
            label={t('managed.quickstart.securityPlan.modelConnection')}
            hint={t('managed.quickstart.securityPlan.hint.modelConnection')}
            tone={plan.hasModelConnection ? 'ready' : 'warning'}
            status={t(
              plan.hasModelConnection
                ? 'managed.quickstart.securityPlan.status.ready'
                : 'managed.quickstart.securityPlan.status.required',
            )}
            value={plan.modelCredentialName || t('managed.quickstart.securityPlan.notConfigured')}
            action={t('managed.quickstart.securityPlan.action.changeModelConnection')}
            disabled={readOnly}
            onEdit={() => onEdit(QUICKSTART_STEP.MODEL_CONNECTION)}
          />
          <SecurityPlanRow
            label={t('managed.quickstart.securityPlan.environment')}
            hint={
              assurance.environment === 'enforced'
                ? t('managed.quickstart.securityPlan.hint.environment')
                : assurance.requiredHosts.length > 0
                  ? t('managed.quickstart.securityPlan.hint.recommendedEnvironment', {
                      hosts: assurance.requiredHosts.join(', '),
                    })
                  : t('managed.quickstart.securityPlan.hint.noEnvironment')
            }
            tone={assurance.environment === 'enforced' ? 'ready' : 'warning'}
            status={t(
              assurance.environment === 'enforced'
                ? 'managed.quickstart.securityPlan.status.enforced'
                : 'managed.quickstart.securityPlan.status.recommended',
            )}
            value={
              plan.environmentId
                ? shortEntityId(plan.environmentId, 'environment')
                : t('managed.quickstart.securityPlan.noEnvironment')
            }
            action={t(
              plan.environmentId
                ? 'managed.quickstart.securityPlan.action.changeEnvironment'
                : 'managed.quickstart.securityPlan.action.configureEnvironment',
            )}
            disabled={readOnly}
            onEdit={() => onEdit(QUICKSTART_STEP.ENVIRONMENT)}
          />
          <SecurityPlanRow
            label={t('managed.quickstart.securityPlan.externalTools')}
            hint={t(
              assurance.externalTools === 'ready'
                ? 'managed.quickstart.securityPlan.hint.externalTools'
                : 'managed.quickstart.securityPlan.hint.missingExternalTools',
            )}
            tone={assurance.externalTools === 'ready' ? 'ready' : 'warning'}
            status={t(
              assurance.externalTools === 'ready'
                ? 'managed.quickstart.securityPlan.status.ready'
                : 'managed.quickstart.securityPlan.status.notAuthorized',
            )}
            value={
              plan.credentialGroupId
                ? shortEntityId(plan.credentialGroupId, 'credentialGroup')
                : assurance.externalTools === 'ready'
                  ? t('managed.quickstart.securityPlan.noAuthorizationRequired')
                  : t('managed.quickstart.securityPlan.notAuthorized')
            }
            action={t(
              plan.credentialGroupId
                ? 'managed.quickstart.securityPlan.action.changeTools'
                : 'managed.quickstart.securityPlan.action.authorizeTools',
            )}
            disabled={readOnly}
            onEdit={() => onEdit(QUICKSTART_STEP.CREDENTIAL_GROUP)}
          />
          <SecurityPlanRow
            label={t('managed.quickstart.securityPlan.audit')}
            hint={t('managed.quickstart.securityPlan.hint.audit')}
            tone="ready"
            status={t('managed.quickstart.securityPlan.status.automatic')}
            value={t('managed.quickstart.securityPlan.auditValue')}
          />
        </div>
      </div>
      <div className="space-y-1 rounded-lg border border-border bg-muted/50 p-3 font-mono text-xs">
        <div>
          <span className="text-muted-foreground">agent:</span>{' '}
          {plan.agentId ? shortEntityId(plan.agentId, 'agent') : '—'}
        </div>
        {plan.environmentId ? (
          <div>
            <span className="text-muted-foreground">environment_id:</span>{' '}
            {shortEntityId(plan.environmentId, 'environment')}
          </div>
        ) : null}
        {plan.credentialGroupId ? (
          <div>
            <span className="text-muted-foreground">credential_group_ids:</span>{' '}
            {`["${shortEntityId(plan.credentialGroupId, 'credentialGroup')}"]`}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function QuickstartProveLaunchFooter({
  needsHardening,
  blocked,
  disabled,
  isCreating,
  onStart,
}: {
  needsHardening: boolean
  blocked: boolean
  disabled: boolean
  isCreating: boolean
  onStart: () => void
}) {
  const { t } = useTranslation()
  const summaryKey = blocked ? 'blocked' : needsHardening ? 'hardening' : 'ready'

  return (
    <div
      data-quickstart-launch-footer
      className="absolute bottom-4 left-5 right-5 rounded-[14px] border border-border bg-background/95 p-3 shadow-md backdrop-blur"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">
            {t(`managed.quickstart.securityPlan.launchHint.${summaryKey}`)}
          </p>
        </div>
        <Button
          className="h-10 shrink-0 rounded-xl px-5 text-sm"
          disabled={disabled}
          onClick={onStart}
        >
          {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          {t('managed.quickstart.startSession')}
        </Button>
      </div>
    </div>
  )
}

function SecurityPlanRow({
  label,
  hint,
  tone,
  status,
  value,
  action,
  disabled,
  onEdit,
}: {
  label: string
  hint: string
  tone: 'ready' | 'warning' | 'muted' | 'primary'
  status: string
  value: string
  action?: string
  disabled?: boolean
  onEdit?: () => void
}) {
  return (
    <div className="rounded-lg bg-background/70 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <span className="block whitespace-nowrap font-medium text-foreground">{label}</span>
          <p className="text-[11px] leading-4 text-muted-foreground">{hint}</p>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <SafetyPlanStatusBadge tone={tone} label={status} />
          <span className="min-w-0 max-w-[180px] truncate text-right font-medium text-foreground">
            {value}
          </span>
          {action && onEdit ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 px-2 text-xs"
              disabled={disabled}
              onClick={onEdit}
            >
              {action}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function SafetyPlanStatusBadge({
  tone,
  label,
}: {
  tone: 'ready' | 'warning' | 'muted' | 'primary'
  label: string
}) {
  const Icon = tone === 'warning' ? AlertTriangle : tone === 'muted' ? Shield : CheckCircle2
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold',
        tone === 'ready' && 'border-emerald-200 bg-emerald-50 text-emerald-700',
        tone === 'warning' && 'border-amber-200 bg-amber-50 text-amber-700',
        tone === 'muted' && 'border-border bg-muted text-muted-foreground',
        tone === 'primary' && 'border-primary/20 bg-primary/10 text-primary',
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}
