'use client'

import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  Play,
  Search,
  Shield,
} from 'lucide-react'
import { useRef } from 'react'

import { EventDetail, EventFilter, EventList } from '@/components/managed/session'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { QuickstartProveFlowController } from '@/hooks/managed/use-quickstart-prove-flow'
import { useTranslation } from '@/lib/i18n'
import type { QuickstartAcceptanceTest } from '@/lib/managed/quickstart-agent-blueprint'
import type { QuickstartTrialStatus } from '@/lib/managed/quickstart-trial-status'
import { cn } from '@/lib/utils'
import type { Environment } from '@/types/managed'

import { QuickstartCapabilityEvidence } from './quickstart-capability-evidence'

interface QuickstartProvePreviewSession {
  active: boolean
  selectedEnvironmentName: string
  selectedEnvironmentId: string
  environments: Environment[]
  acceptanceTest: QuickstartAcceptanceTest
  message: string
  isSendingMessage: boolean
  isTestRunning: boolean
  canTest: boolean
  readOnly: boolean
}

interface QuickstartProvePreviewActions {
  selectEnvironment: (environmentId: string) => void
  viewSession: () => void
  goBack: () => void
  continue: () => void
  retryTrialStatus: () => void
  changeMessage: (message: string) => void
  sendMessage: () => void
  startTest: () => void
}

export function QuickstartProvePreview({
  controller,
  session,
  actions,
}: {
  controller: QuickstartProveFlowController
  session: QuickstartProvePreviewSession
  actions: QuickstartProvePreviewActions
}) {
  const { t } = useTranslation()
  const preview = controller.preview
  const trial = controller.trial
  const sessionStart = preview.events[0]?.created_at || preview.events[0]?.id || ''
  const eventEvidenceRef = useRef<HTMLDivElement>(null)

  const reviewTranscript = () => {
    preview.showTranscript()
    eventEvidenceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const reviewDebug = () => {
    preview.showDebug()
    eventEvidenceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex h-[calc(100vh-240px)] min-h-0 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        {session.active ? (
          <div className="min-w-0 text-xs text-muted-foreground">
            {session.selectedEnvironmentName ? (
              <>
                {t('managed.quickstart.environment')}
                <span className="ml-1 font-medium text-foreground">
                  {session.selectedEnvironmentName}
                </span>
              </>
            ) : (
              t('managed.quickstart.sessionLiveHint')
            )}
          </div>
        ) : (
          <Select
            value={session.selectedEnvironmentId || undefined}
            onValueChange={actions.selectEnvironment}
          >
            <SelectTrigger className="w-[220px] max-w-[40vw]">
              <SelectValue placeholder={t('managed.quickstart.selectEnv')} />
            </SelectTrigger>
            <SelectContent>
              {session.environments.map((environment) => (
                <SelectItem key={environment.id} value={environment.id}>
                  {environment.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {session.active ? (
          <button
            className="whitespace-nowrap text-xs text-primary hover:underline"
            onClick={actions.viewSession}
          >
            {t('managed.quickstart.viewSession')} &uarr;
          </button>
        ) : null}
      </div>

      {session.active ? (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <TrialRunBanner
              status={trial.status}
              onGoBack={actions.goBack}
              onContinue={actions.continue}
              onRetry={actions.retryTrialStatus}
              onViewSession={actions.viewSession}
            />
            <QuickstartCapabilityEvidence evidence={trial.capabilityEvidence} />
            {session.acceptanceTest.message || session.acceptanceTest.checks.length > 0 ? (
              <div className="border-b border-border bg-muted/20 px-4 py-3">
                <div className="flex items-start gap-2">
                  <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-foreground">
                      {t('managed.quickstart.trialRun.acceptanceEvidence.title')}
                    </p>
                    <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                      {t('managed.quickstart.trialRun.acceptanceEvidence.description')}
                    </p>
                    {session.acceptanceTest.message ? (
                      <div className="mt-2 rounded-lg border border-border bg-background px-3 py-2">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {t('managed.quickstart.trialRun.acceptanceEvidence.testMessage')}
                        </p>
                        <p className="mt-1 text-sm text-foreground">
                          {session.acceptanceTest.message}
                        </p>
                      </div>
                    ) : null}
                    <div className="mt-3 rounded-lg border border-border bg-background px-3 py-2">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t('managed.quickstart.trialRun.acceptanceEvidence.observableTitle')}
                      </p>
                      <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                        {t('managed.quickstart.trialRun.acceptanceEvidence.observableDescription')}
                      </p>
                      <div className="mt-2 space-y-1.5">
                        {trial.observableChecks.map((check) => (
                          <div
                            key={check.id}
                            className="flex items-center justify-between gap-2 text-xs"
                          >
                            <div className="flex items-center gap-2">
                              {check.status === 'passed' ? (
                                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                              ) : check.status === 'failed' ? (
                                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600" />
                              ) : (
                                <span className="h-2 w-2 shrink-0 rounded-full border border-muted-foreground/50" />
                              )}
                              <span className="text-foreground/90">
                                {t(
                                  `managed.quickstart.trialRun.acceptanceEvidence.check.${check.id}`,
                                )}
                              </span>
                            </div>
                            <span
                              className={cn(
                                'text-[11px] font-medium',
                                check.status === 'passed' && 'text-emerald-600',
                                check.status === 'failed' && 'text-amber-600',
                                check.status === 'not_observed' && 'text-muted-foreground',
                              )}
                            >
                              {t(
                                check.status === 'passed'
                                  ? 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.passed'
                                  : check.status === 'failed'
                                    ? 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.failed'
                                    : 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.notObserved',
                              )}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                    {session.acceptanceTest.checks.length > 0 ? (
                      <div className="mt-3">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {t('managed.quickstart.trialRun.acceptanceEvidence.manualTitle')}
                        </p>
                        <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                          {t('managed.quickstart.trialRun.acceptanceEvidence.manualDescription')}
                        </p>
                        <div className="mt-2 space-y-1.5">
                          {session.acceptanceTest.checks.map((check) => (
                            <div
                              key={check}
                              className="flex items-start gap-2 text-xs text-foreground/90"
                            >
                              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full border border-primary/60" />
                              <span>{check}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" onClick={reviewTranscript}>
                        {t('managed.quickstart.trialRun.acceptanceEvidence.reviewTranscript')}
                      </Button>
                      <Button variant="outline" size="sm" onClick={reviewDebug}>
                        {t('managed.quickstart.trialRun.acceptanceEvidence.reviewDebug')}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
            <div className="flex items-center gap-3 border-b border-border px-4 py-2">
              <button
                onClick={preview.showTranscript}
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-semibold transition-colors',
                  preview.tab === 'transcript'
                    ? 'bg-foreground text-background'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t('managed.sessions.tab.transcript')}
              </button>
              <button
                onClick={preview.showDebug}
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-semibold transition-colors',
                  preview.tab === 'debug'
                    ? 'bg-foreground text-background'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t('managed.sessions.tab.debug')}
              </button>
              <EventFilter
                selected={
                  preview.filter.size > 0 ? preview.filter : new Set(preview.availableTypes)
                }
                onChange={preview.setFilter}
                availableTypes={preview.availableTypes}
              />
              <button
                type="button"
                className="text-muted-foreground transition-colors hover:text-foreground"
                onClick={preview.toggleSearch}
              >
                <Search className="h-3.5 w-3.5" />
              </button>
            </div>
            {preview.showSearch ? (
              <div className="border-b border-border px-4 py-1.5">
                <input
                  type="text"
                  value={preview.search}
                  onChange={(event) => preview.setSearch(event.target.value)}
                  placeholder={t('managed.quickstart.searchEvents')}
                  className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                  autoFocus
                />
              </div>
            ) : null}
            <div
              ref={eventEvidenceRef}
              data-testid="quickstart-event-evidence"
              className="min-h-[240px] scroll-mt-2"
            >
              {preview.selectedEvent ? (
                <EventDetail
                  event={preview.selectedEvent}
                  mode={preview.tab}
                  sessionStart={sessionStart}
                  onClose={preview.clearSelectedEvent}
                />
              ) : preview.events.length === 0 ? (
                <div className="flex min-h-[240px] items-center justify-center py-12">
                  <p className="text-sm text-muted-foreground">
                    {t('managed.quickstart.noEventsYet')}
                  </p>
                </div>
              ) : (
                <EventList
                  events={preview.events}
                  sessionStart={sessionStart}
                  selectedId={null}
                  onSelect={preview.selectEvent}
                  mode={preview.tab}
                />
              )}
            </div>
          </div>
          <div className="border-t border-border px-4 py-3">
            <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
              <input
                type="text"
                value={session.message}
                onInput={(event) => actions.changeMessage(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    actions.sendMessage()
                  }
                }}
                disabled={session.isSendingMessage || session.readOnly}
                placeholder={
                  trial.isSessionRunning
                    ? t('managed.quickstart.agentProcessing')
                    : t('managed.quickstart.sendMessage')
                }
                className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
              {trial.isSessionRunning ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : (
                <button
                  onClick={actions.sendMessage}
                  disabled={session.isSendingMessage || session.readOnly || !session.message.trim()}
                  className={cn(
                    'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                    session.isSendingMessage || session.readOnly || !session.message.trim()
                      ? 'cursor-not-allowed bg-muted-foreground/30 text-white shadow-none'
                      : 'bg-primary hover:bg-primary/90',
                  )}
                >
                  &uarr;
                </button>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <p className="max-w-[320px] text-sm text-muted-foreground">
            {t('managed.quickstart.selectEnvPrompt')}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={!session.canTest || session.isTestRunning || session.readOnly}
            onClick={actions.startTest}
          >
            {session.isTestRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {t('managed.quickstart.testRun')}
          </Button>
        </div>
      )}
    </div>
  )
}

function TrialRunBanner({
  status,
  onGoBack,
  onContinue,
  onRetry,
  onViewSession,
}: {
  status: QuickstartTrialStatus
  onGoBack: () => void
  onContinue: () => void
  onRetry: () => void
  onViewSession: () => void
}) {
  const { t } = useTranslation()
  if (status === 'idle') return null

  return (
    <div
      className={cn(
        'flex items-center gap-3 border-b border-border px-4 py-2.5 text-sm',
        status === 'testing' && 'bg-blue-50 dark:bg-blue-950/20',
        status === 'response_received' && 'bg-sky-50 dark:bg-sky-950/20',
        (status === 'error' || status === 'access_rejected') && 'bg-amber-50 dark:bg-amber-950/20',
        status === 'runtime_unavailable' && 'bg-red-50 dark:bg-red-950/20',
      )}
    >
      {status === 'testing' ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
          <span className="text-blue-700 dark:text-blue-400">
            {t('managed.quickstart.trialRun.testing')}
          </span>
        </>
      ) : null}
      {status === 'response_received' ? (
        <>
          <ClipboardCheck className="h-4 w-4 text-sky-600" />
          <span className="text-sky-700 dark:text-sky-300">
            {t('managed.quickstart.trialRun.responseReceived')}
          </span>
        </>
      ) : null}
      {status === 'error' ? (
        <>
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <span className="text-amber-700 dark:text-amber-400">
            {t('managed.quickstart.trialRun.error')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onGoBack}>
              {t('managed.quickstart.trialRun.goBack')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onContinue}>
              {t('managed.quickstart.trialRun.continue')}
            </Button>
          </div>
        </>
      ) : null}
      {status === 'access_rejected' ? (
        <>
          <Shield className="h-4 w-4 text-amber-600" />
          <span className="text-amber-800 dark:text-amber-300">
            {t('managed.quickstart.trialRun.accessRejected')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onGoBack}>
              {t('managed.quickstart.trialRun.reviewControls')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onViewSession}>
              {t('managed.quickstart.trialRun.viewSession')}
            </Button>
          </div>
        </>
      ) : null}
      {status === 'runtime_unavailable' ? (
        <>
          <AlertTriangle className="h-4 w-4 text-red-500" />
          <span className="text-red-700 dark:text-red-400">
            {t('managed.quickstart.trialRun.runtimeUnavailable')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onRetry}>
              {t('managed.quickstart.trialRun.checkAgain')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onViewSession}>
              {t('managed.quickstart.trialRun.viewSession')}
            </Button>
          </div>
        </>
      ) : null}
    </div>
  )
}
