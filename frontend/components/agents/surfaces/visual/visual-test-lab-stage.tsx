'use client'

import { Button } from '@/components/ui/button'
import { DebugPanel } from '@/components/observation/components/DebugPanel'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualTestLabStage({ agent, version, workspaceId, navigateToStage }: StageProps) {
  const { t } = useTranslation()
  const agentId = agent.id
  const versionId = version?.id ?? ''

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
      <div className="shrink-0 border-b border-[var(--border)] px-6 py-2">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col gap-0.5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.studio.testLab.title', { defaultValue: 'Test the current draft' })}
            </h2>
            <p className="max-w-xl truncate text-xs text-[var(--text-muted)]">
              {t('agents.studio.testLab.subtitle', {
                defaultValue:
                  'Run draft behavior before publishing. These tests do not affect the active release.',
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigateToStage('build')}
              className="h-8 text-xs"
            >
              {t('agents.studio.testLab.backToCanvas', { defaultValue: 'Back to Build' })}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigateToStage('release')}
              className="h-8 text-xs"
            >
              {t('agents.studio.testLab.openRelease', { defaultValue: 'Open Release' })}
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <DebugPanel agentId={agentId} agentVersionId={versionId} workspaceId={workspaceId} />
      </div>
    </div>
  )
}
