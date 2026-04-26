'use client'

import { useEffect, useState } from 'react'

import { useGraphStore } from '@/components/editors/graph-builder/stores/graphStore'
import { useExecutionStore } from '@/components/editors/graph-builder/stores/execution/executionStore'
import { ExecutionPanelNew as ExecutionPanel } from '@/components/execution/ExecutionPanelNew'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualTestLabStage({ agent, version, workspaceId, navigateToStage }: StageProps) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const agentId = agent.id
  const versionId = version?.id

  const { isExecuting, setCurrentGraphId, startDraftExecution, stopExecution } =
    useExecutionStore()

  useEffect(() => {
    useGraphStore.setState({
      agentId,
      graphId: agentId,
      versionId: versionId ?? null,
      workspaceId,
    })
    setCurrentGraphId(agentId)
  }, [agentId, setCurrentGraphId, versionId, workspaceId])

  const runDraft = async () => {
    const trimmedInput = input.trim()
    if (!trimmedInput || !versionId) return
    await startDraftExecution({
      agentId,
      versionId,
      workspaceId,
      input: trimmedInput,
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
      <div className="shrink-0 border-b border-[var(--border)] px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
              {t('agents.studio.testLab.kicker', { defaultValue: 'Draft validation' })}
            </p>
            <h2 className="mt-1 text-xl font-semibold">
              {t('agents.studio.testLab.title', { defaultValue: 'Test the current draft' })}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('agents.studio.testLab.subtitle', {
                defaultValue:
                  'Run draft behavior before publishing. These tests do not affect the active release.',
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => navigateToStage('build')}>
              {t('agents.studio.testLab.backToCanvas', { defaultValue: 'Back to Build' })}
            </Button>
            <Button variant="outline" onClick={() => navigateToStage('release')}>
              {t('agents.studio.testLab.openRelease', { defaultValue: 'Open Release' })}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[360px_1fr]">
        <aside className="border-r border-[var(--border)] p-4">
          <label className="text-sm font-medium">
            {t('agents.studio.testLab.inputLabel', { defaultValue: 'Test input' })}
          </label>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={8}
            className="mt-2"
            placeholder={t('agents.studio.testLab.inputPlaceholder', {
              defaultValue: 'Enter a sample request for this draft...',
            })}
          />
          <Button
            className="mt-3 w-full"
            onClick={runDraft}
            disabled={!input.trim() || !versionId || isExecuting}
          >
            {isExecuting
              ? t('agents.studio.testLab.running', { defaultValue: 'Running...' })
              : t('agents.studio.testLab.runDraft', { defaultValue: 'Run Draft' })}
          </Button>
          {isExecuting && (
            <Button className="mt-2 w-full" variant="outline" onClick={() => stopExecution()}>
              {t('agents.studio.testLab.stop', { defaultValue: 'Stop' })}
            </Button>
          )}
        </aside>
        <section className="min-h-0 overflow-hidden">
          <ExecutionPanel embedded />
        </section>
      </div>
    </div>
  )
}
