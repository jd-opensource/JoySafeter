'use client'

import { CheckCircle2, Loader2, Shield, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type {
  QuickstartSecurityDefaults,
  QuickstartRecommendationStatus,
} from '@/hooks/managed/use-quickstart-recommendation'
import type { QuickstartSecurityFlowController } from '@/hooks/managed/use-quickstart-security-flow'
import { useTranslation } from '@/lib/i18n'
import {
  QUICKSTART_STEP,
  type QuickstartResourceStepId,
  type QuickstartStepId,
} from '@/lib/managed/quickstart-flow'
import { normalizeQuickstartAllowedHosts } from '@/lib/managed/quickstart-networking'
import type { QuickstartNetworkingType } from '@/lib/managed/quickstart-recommendation-contract'
import { quickstartResourceEndpoint } from '@/lib/managed/quickstart-resource-contract'
import { cn } from '@/lib/utils'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import type { CredentialGroupId, EnvironmentId } from '@/types/entity-id'
import type { CredentialGroup, Environment } from '@/types/managed'

import {
  QuickstartCompletionDescription,
  QuickstartCompletionTitle,
} from './quickstart-completion-copy'
import {
  QuickstartApiCard,
  QuickstartNumberedChoiceList,
  QuickstartQADisplay,
  QuickstartStepDoneBadge,
} from './quickstart-flow-primitives'
import { QuickstartRecommendationStatusCard } from './quickstart-recommendation-status'

interface QuickstartSecureResources {
  environments: Environment[]
  credentialGroups: CredentialGroup[]
  resolveEnvironment: (id: EnvironmentId) => Environment | null
  resolveCredentialGroup: (id: CredentialGroupId) => CredentialGroup | null
}

interface QuickstartSecureActions {
  confirmEnvironment: () => void
  confirmCredentialGroup: () => void
  createEnvironment: (
    networkType: QuickstartNetworkingType,
    allowedHosts: string[],
  ) => Promise<boolean>
  createCredentialGroup: (
    name: string,
    options: {
      credentials?: Array<{
        name?: string
        mcpServerUrl: string
        tokenValue: string
        authRequirement: 'required' | 'optional' | 'none'
      }>
    },
  ) => Promise<boolean>
  skipEnvironment: () => void
  skipCredentialGroup: () => void
  advance: () => void
}

export interface QuickstartSecurePhaseProps {
  currentStep: QuickstartStepId
  completedSteps: ReadonlySet<number>
  pendingConfirmation: boolean
  isCreating: boolean
  readOnly: boolean
  curls: Partial<Record<QuickstartResourceStepId, string>>
  controller: QuickstartSecurityFlowController
  recommendation: {
    defaults: QuickstartSecurityDefaults
    status: QuickstartRecommendationStatus
    retry: () => void
  }
  resources: QuickstartSecureResources
  actions: QuickstartSecureActions
}

export function QuickstartSecurePhase({
  currentStep,
  completedSteps,
  pendingConfirmation,
  isCreating,
  readOnly,
  curls,
  controller,
  recommendation,
  resources,
  actions,
}: QuickstartSecurePhaseProps) {
  const { t } = useTranslation()
  const environment = controller.environment
  const credentialGroup = controller.credentialGroup
  const defaults = recommendation.defaults
  const suggestedAllowlist = defaults.recommendedHosts.join(', ')

  const handleEnvironmentChoice = (num: number) => {
    if (num <= resources.environments.length) {
      const candidate = resources.environments[num - 1]
      const current = resources.resolveEnvironment(candidate.id)
      if (!current) return
      environment.setPendingId(current.id)
      environment.setAnswers({ choiceLabel: current.name })
      environment.setSubStep('selected')
      return
    }
    environment.setAnswers({ choiceLabel: t('managed.quickstart.envCreateNew') })
    environment.setSubStep('networking')
  }

  const handleNetworkingChoice = (num: number) => {
    const networkingType = num === 1 ? 'limited' : 'unrestricted'
    environment.setNetworkingType(networkingType)
    environment.setAnswers((current) => ({
      ...current,
      networkingLabel: t(
        num === 1 ? 'managed.quickstart.envLimited' : 'managed.quickstart.envUnrestricted',
      ),
    }))
    if (num === 1 && !environment.hosts.trim() && suggestedAllowlist) {
      environment.setHosts(suggestedAllowlist)
    }
    if (num === 2) environment.setHosts('')
    environment.setSubStep('hosts')
  }

  const handleCreateEnvironment = async () => {
    const hosts = normalizeQuickstartAllowedHosts(environment.hosts)
    const created = await actions.createEnvironment(environment.networkingType, hosts)
    if (!created) return
    environment.setSubStep('selected')
    actions.advance()
  }

  const handleCredentialGroupChoice = (num: number) => {
    if (num <= resources.credentialGroups.length) {
      const candidate = resources.credentialGroups[num - 1]
      const current = resources.resolveCredentialGroup(candidate.id)
      if (!current) return
      credentialGroup.setPendingId(current.id)
      credentialGroup.setAnswers({ choiceLabel: current.name })
      credentialGroup.setSubStep('selected')
      return
    }
    credentialGroup.setAnswers({
      choiceLabel: t('managed.quickstart.credentialGroupCreateNew'),
    })
    if (credentialGroup.credentials.length === 0) {
      credentialGroup.setCredentials([
        {
          name: '',
          mcpServerUrl: '',
          authRequirement: 'required',
          tokenValue: '',
        },
      ])
    }
    credentialGroup.setSubStep('name')
  }

  const handleCreateCredentialGroup = async () => {
    const credentials = credentialGroup.credentials.map((credential) => ({
      ...credential,
      name: credential.name.trim(),
      mcpServerUrl: credential.mcpServerUrl.trim(),
      tokenValue: credential.tokenValue.trim(),
    }))
    for (const credential of credentials) {
      const urlError = validateUrlScheme(credential.mcpServerUrl)
      if (urlError) {
        alert(urlError)
        return
      }
    }
    const name = credentialGroup.name.trim()
    const created = await actions.createCredentialGroup(name, { credentials })
    if (!created) return
    credentialGroup.setAnswers((current) => ({ ...current, choiceLabel: name }))
    credentialGroup.setSubStep('selected')
    actions.advance()
  }

  const credentialsIncomplete = credentialGroup.credentials.some(
    (credential) =>
      !credential.mcpServerUrl.trim() ||
      (credential.authRequirement === 'required' && !credential.tokenValue.trim()),
  )
  const createCredentialGroupDisabled =
    isCreating ||
    readOnly ||
    !credentialGroup.name.trim() ||
    (defaults.externalToolsRecommended && credentialGroup.credentials.length === 0) ||
    credentialsIncomplete

  return (
    <>
      {currentStep >= QUICKSTART_STEP.ENVIRONMENT &&
      currentStep <= QUICKSTART_STEP.CREDENTIAL_GROUP ? (
        <QuickstartRecommendationStatusCard
          status={recommendation.status}
          onRetry={recommendation.retry}
        />
      ) : null}

      {currentStep > QUICKSTART_STEP.ENVIRONMENT &&
      completedSteps.has(QUICKSTART_STEP.ENVIRONMENT) &&
      environment.answers.choiceLabel ? (
        <QuickstartStepDoneBadge
          label={`${t('managed.quickstart.stepComplete.envCreated')}: ${environment.answers.choiceLabel}`}
          curl={curls[QUICKSTART_STEP.ENVIRONMENT]}
          endpoint={quickstartResourceEndpoint(QUICKSTART_STEP.ENVIRONMENT)}
        />
      ) : null}

      {currentStep === QUICKSTART_STEP.ENVIRONMENT &&
      (!completedSteps.has(QUICKSTART_STEP.ENVIRONMENT) || environment.subStep === 'selected') &&
      !pendingConfirmation ? (
        <>
          {environment.subStep === 'choose' ? (
            <p className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground">
              {t('managed.quickstart.envIntro')}
            </p>
          ) : null}
          {environment.subStep === 'choose' ? (
            <QuickstartNumberedChoiceList
              question={t('managed.quickstart.envReuseOrCreate')}
              choices={[
                ...resources.environments.map((item, index) => ({
                  num: index + 1,
                  label: item.name,
                })),
                {
                  num: resources.environments.length + 1,
                  label: t('managed.quickstart.envCreateNew'),
                },
              ]}
              onSelect={handleEnvironmentChoice}
              onSkip={actions.skipEnvironment}
            />
          ) : null}

          {environment.subStep === 'selected' ? (
            <>
              <QuickstartQADisplay
                question={t('managed.quickstart.envReuseOrCreate')}
                answer={environment.answers.choiceLabel || ''}
              />
              <div className="flex items-center gap-2 pt-1">
                <Button
                  className="h-10 rounded-xl px-5 text-sm font-semibold"
                  onClick={actions.confirmEnvironment}
                >
                  {t('managed.quickstart.nextConfigureCredentialGroup')}
                </Button>
              </div>
            </>
          ) : null}

          {environment.subStep === 'networking' ? (
            <>
              <QuickstartQADisplay
                question={t('managed.quickstart.envReuseOrCreate')}
                answer={environment.answers.choiceLabel || ''}
              />
              <QuickstartNumberedChoiceList
                question={t('managed.quickstart.envNetworkingQuestion')}
                choices={[
                  { num: 1, label: t('managed.quickstart.envLimited'), arrow: true },
                  { num: 2, label: t('managed.quickstart.envUnrestricted'), arrow: true },
                ]}
                onSelect={handleNetworkingChoice}
                onSkip={actions.skipEnvironment}
              />
            </>
          ) : null}

          {environment.subStep === 'hosts' ? (
            <>
              <QuickstartQADisplay
                question={t('managed.quickstart.envReuseOrCreate')}
                answer={environment.answers.choiceLabel || ''}
              />
              <QuickstartQADisplay
                question={t('managed.quickstart.envNetworkingQuestion')}
                answer={environment.answers.networkingLabel || ''}
              />
              <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                <p className="text-[14px] font-semibold text-foreground">
                  {t('managed.quickstart.envHostsQuestion')}
                </p>
                <div
                  className={cn(
                    'rounded-xl border p-3 text-xs',
                    suggestedAllowlist
                      ? 'border-primary/20 bg-primary/5'
                      : 'border-border bg-muted/30',
                  )}
                >
                  <div className="flex items-start gap-2">
                    <Sparkles
                      className={cn(
                        'mt-0.5 h-3.5 w-3.5 shrink-0',
                        suggestedAllowlist ? 'text-primary' : 'text-muted-foreground',
                      )}
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <div>
                        <p className="font-semibold text-foreground">
                          {t('managed.quickstart.smartDefaults.allowlist.title')}
                        </p>
                        <p className="mt-0.5 leading-5 text-muted-foreground">
                          {suggestedAllowlist
                            ? t(
                                `managed.quickstart.smartDefaults.allowlist.reason.${defaults.hostReason}`,
                              )
                            : t('managed.quickstart.smartDefaults.allowlist.emptyDescription')}
                        </p>
                      </div>
                      {defaults.recommendedHosts.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {defaults.recommendedHosts.map((host) => (
                            <span
                              key={host}
                              className="rounded-full border border-primary/20 bg-background px-2 py-0.5 font-mono text-[11px] text-foreground"
                            >
                              {host}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    {suggestedAllowlist ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 shrink-0 px-2 text-xs"
                        disabled={readOnly}
                        onClick={() => environment.setHosts(suggestedAllowlist)}
                      >
                        {t('managed.quickstart.smartDefaults.allowlist.useSuggested')}
                      </Button>
                    ) : null}
                  </div>
                </div>
                <input
                  type="text"
                  value={environment.hosts}
                  onChange={(event) => environment.setHosts(event.target.value)}
                  placeholder={t('managed.quickstart.envHostsPlaceholder')}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground">
                  {t('managed.quickstart.envHostsHint')}
                </p>
                <div className="flex items-center justify-between">
                  <Button
                    className="h-9 rounded-xl px-4 text-sm"
                    disabled={isCreating || readOnly}
                    onClick={handleCreateEnvironment}
                  >
                    {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {t('managed.quickstart.createEnvironment')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground"
                    onClick={actions.skipEnvironment}
                  >
                    {t('common.skip')}
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {currentStep > QUICKSTART_STEP.CREDENTIAL_GROUP &&
      completedSteps.has(QUICKSTART_STEP.CREDENTIAL_GROUP) &&
      credentialGroup.answers.choiceLabel ? (
        <QuickstartStepDoneBadge
          label={`${t('managed.quickstart.stepComplete.credentialGroupCreated')}: ${credentialGroup.answers.choiceLabel}`}
          curl={curls[QUICKSTART_STEP.CREDENTIAL_GROUP]}
          endpoint={quickstartResourceEndpoint(QUICKSTART_STEP.CREDENTIAL_GROUP)}
        />
      ) : null}

      {currentStep === QUICKSTART_STEP.CREDENTIAL_GROUP &&
      (!completedSteps.has(QUICKSTART_STEP.CREDENTIAL_GROUP) ||
        credentialGroup.subStep === 'selected') &&
      !pendingConfirmation ? (
        <>
          {credentialGroup.subStep === 'choose' ? (
            <div className="space-y-3">
              <p className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground">
                {t('managed.quickstart.credentialGroupIntro')}
              </p>
              <div
                className={cn(
                  'rounded-xl border p-3 text-xs',
                  defaults.externalToolsRecommended
                    ? 'border-primary/20 bg-primary/5'
                    : 'border-border bg-muted/30',
                )}
              >
                <div className="flex items-start gap-2">
                  <Sparkles
                    className={cn(
                      'mt-0.5 h-3.5 w-3.5 shrink-0',
                      defaults.externalToolsRecommended ? 'text-primary' : 'text-muted-foreground',
                    )}
                  />
                  <div className="space-y-1">
                    <p className="font-semibold text-foreground">
                      {t('managed.quickstart.smartDefaults.externalTools.title')}
                    </p>
                    <p className="leading-5 text-muted-foreground">
                      {t(
                        `managed.quickstart.smartDefaults.externalTools.reason.${defaults.externalToolsReason}`,
                      )}
                    </p>
                  </div>
                </div>
              </div>
              <QuickstartNumberedChoiceList
                question={t('managed.quickstart.credentialGroupReuseOrCreate')}
                choices={[
                  ...resources.credentialGroups.map((item, index) => ({
                    num: index + 1,
                    label: item.name,
                  })),
                  {
                    num: resources.credentialGroups.length + 1,
                    label: t('managed.quickstart.credentialGroupCreateNew'),
                  },
                ]}
                onSelect={handleCredentialGroupChoice}
                onSkip={actions.skipCredentialGroup}
              />
            </div>
          ) : null}

          {credentialGroup.subStep === 'selected' ? (
            <>
              <QuickstartQADisplay
                question={t('managed.quickstart.credentialGroupReuseOrCreate')}
                answer={credentialGroup.answers.choiceLabel || ''}
              />
              <div className="flex items-center gap-2 pt-1">
                <Button
                  className="h-10 rounded-xl px-5 text-sm font-semibold"
                  onClick={actions.confirmCredentialGroup}
                >
                  {t('managed.quickstart.nextStartSession')}
                </Button>
              </div>
            </>
          ) : null}

          {credentialGroup.subStep === 'name' ? (
            <>
              <QuickstartQADisplay
                question={t('managed.quickstart.credentialGroupReuseOrCreate')}
                answer={credentialGroup.answers.choiceLabel || ''}
              />
              <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                <p className="text-[14px] font-semibold text-foreground">
                  {t('managed.quickstart.credentialGroupNameQuestion')}
                </p>
                <input
                  type="text"
                  value={credentialGroup.name}
                  onChange={(event) => credentialGroup.setName(event.target.value)}
                  placeholder={t('managed.quickstart.credentialGroupNamePlaceholder')}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                />
                <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs">
                  <div className="flex items-start gap-2">
                    <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                    <div className="space-y-1">
                      <p className="font-semibold text-foreground">
                        {t('managed.quickstart.credentialGroupCredentialTitle')}
                      </p>
                      <p className="leading-5 text-muted-foreground">
                        {t('managed.quickstart.credentialGroupCredentialHint')}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="space-y-2">
                  {credentialGroup.credentials.map((credential, index) => (
                    <div
                      key={`${credential.mcpServerUrl}-${index}`}
                      className="border-border/80 space-y-2 rounded-xl border bg-muted/20 p-3 transition-colors focus-within:border-primary/40 focus-within:bg-primary/[0.03]"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-foreground">
                            {credential.name ||
                              t('managed.quickstart.credentialGroupCredentialNamePlaceholder')}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            {t(
                              `managed.quickstart.credentialGroupAuth.${credential.authRequirement}`,
                            )}
                          </p>
                        </div>
                        {credentialGroup.credentials.length > 1 ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-muted-foreground"
                            onClick={() =>
                              credentialGroup.setCredentials(
                                credentialGroup.credentials.filter(
                                  (_, credentialIndex) => credentialIndex !== index,
                                ),
                              )
                            }
                          >
                            {t('common.remove')}
                          </Button>
                        ) : null}
                      </div>
                      <input
                        type="text"
                        value={credential.mcpServerUrl}
                        onChange={(event) =>
                          credentialGroup.updateCredential(index, {
                            mcpServerUrl: event.target.value,
                          })
                        }
                        placeholder={t('managed.quickstart.credentialGroupMcpServerUrlPlaceholder')}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                      />
                      {credential.authRequirement !== 'none' ? (
                        <div className="grid gap-2 sm:grid-cols-2">
                          <input
                            type="text"
                            value={credential.name}
                            onChange={(event) =>
                              credentialGroup.updateCredential(index, { name: event.target.value })
                            }
                            placeholder={t(
                              'managed.quickstart.credentialGroupCredentialNamePlaceholder',
                            )}
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                          />
                          <input
                            type="password"
                            value={credential.tokenValue}
                            onChange={(event) =>
                              credentialGroup.updateCredential(index, {
                                tokenValue: event.target.value,
                              })
                            }
                            placeholder={t('managed.quickstart.credentialGroupTokenPlaceholder')}
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                          />
                        </div>
                      ) : (
                        <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
                          {t('managed.quickstart.credentialGroupNoTokenRequired')}
                        </p>
                      )}
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 w-full rounded-lg text-xs"
                    onClick={() =>
                      credentialGroup.setCredentials([
                        ...credentialGroup.credentials,
                        {
                          name: '',
                          mcpServerUrl: '',
                          authRequirement: 'required',
                          tokenValue: '',
                        },
                      ])
                    }
                  >
                    {t('managed.quickstart.credentialGroupAddServer')}
                  </Button>
                </div>
                <div className="flex items-center justify-between">
                  <Button
                    className="h-9 rounded-xl px-4 text-sm"
                    disabled={createCredentialGroupDisabled}
                    onClick={handleCreateCredentialGroup}
                  >
                    {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {t('managed.quickstart.createCredentialGroup')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground"
                    onClick={actions.skipCredentialGroup}
                  >
                    {t('common.skip')}
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {(currentStep === QUICKSTART_STEP.ENVIRONMENT ||
        currentStep === QUICKSTART_STEP.CREDENTIAL_GROUP) &&
      completedSteps.has(currentStep) &&
      curls[currentStep] &&
      (currentStep === QUICKSTART_STEP.ENVIRONMENT
        ? environment.subStep !== 'selected'
        : credentialGroup.subStep !== 'selected') ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            <QuickstartCompletionTitle step={currentStep} />
          </div>
          <QuickstartApiCard
            endpoint={quickstartResourceEndpoint(currentStep)}
            curl={curls[currentStep]}
          />
          <QuickstartCompletionDescription
            step={currentStep}
            className="text-[13px] leading-6 text-foreground/80"
          />
          <Button className="h-10 rounded-xl px-4 text-sm" onClick={actions.advance}>
            {t(
              currentStep === QUICKSTART_STEP.ENVIRONMENT
                ? 'managed.quickstart.nextConfigureCredentialGroup'
                : 'managed.quickstart.nextStartSession',
            )}
          </Button>
        </div>
      ) : null}
    </>
  )
}
