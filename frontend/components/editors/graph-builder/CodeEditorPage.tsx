'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Play, Rocket, Save, Square, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { versionKeys } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { CodeEditor } from './components/CodeEditor'
import { useCodeEditorStore } from './stores/codeEditorStore'
import { useExecutionStore } from './stores/execution/executionStore'
import { DebugPanel } from '@/components/observation/components/DebugPanel'
import { RunInputModal } from './components/RunInputModal'
import { usePublishAgent } from '@/hooks/queries/agentPublish'
import { useAgent } from '@/hooks/queries/agents'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorPage({ graphId, workspaceId }: Props) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const isDirty = useCodeEditorStore((s) => s.isDirty)
  const isSaving = useCodeEditorStore((s) => s.isSaving)
  const save = useCodeEditorStore((s) => s.save)
  const graphName = useCodeEditorStore((s) => s.graphName)
  const setGraphName = useCodeEditorStore((s) => s.setGraphName)
  const versionId = useCodeEditorStore((s) => s.versionId)

  const publishAgent = usePublishAgent()
  const { data: agent } = useAgent(graphId, workspaceId)

  const isExecuting = useExecutionStore((s) => s.isExecuting)
  const showExecutionPanel = useExecutionStore((s) => s.showPanel)

  const [isRunModalOpen, setIsRunModalOpen] = useState(false)
  const [runInput, setRunInput] = useState('')

  const handleRunClick = () => {
    if (isExecuting) {
      useExecutionStore.getState().stopExecution()
      return
    }
    setIsRunModalOpen(true)
  }

  const handleStartExecution = () => {
    if (!runInput.trim()) return
    setIsRunModalOpen(false)
    useExecutionStore.getState().startExecution(runInput)
    setRunInput('')
  }

  const handleDeploy = async () => {
    if (publishAgent.isPending || !graphId) return
    if (isDirty) await save()
    publishAgent.mutate(
      { agentId: graphId, workspaceId },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: versionKeys.all(graphId, workspaceId) })
          toast({ title: t('workspace.deploySuccess'), variant: 'success' })
        },
        onError: (error) => {
          toast({
            title: t('workspace.deployFailed'),
            description:
              error instanceof Error ? error.message : t('workspace.deployFailedDescription'),
            variant: 'destructive',
          })
        },
      },
    )
  }

  const isDeploying = publishAgent.isPending
  const isDeployed = Boolean(agent?.active_release_id) || publishAgent.isSuccess

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
        <div className="flex items-center gap-3">
          <input
            className="min-w-0 max-w-xs border-none bg-transparent text-sm font-medium text-[var(--text-primary)] outline-none"
            value={graphName ?? ''}
            onChange={(e) => setGraphName(e.target.value)}
            placeholder={t('workspace.untitledGraph')}
          />
          <button
            className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)] disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => save()}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            {isSaving ? t('workspace.savingEllipsis') : t('workspace.save')}
          </button>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => useExecutionStore.getState().togglePanel(!showExecutionPanel)}
            className="h-7 w-7 rounded-md hover:bg-[var(--surface-2)]"
          >
            {showExecutionPanel ? (
              <ChevronDown size={16} className="text-[var(--text-secondary)]" />
            ) : (
              <ChevronUp size={16} className="text-[var(--text-secondary)]" />
            )}
          </Button>

          <Button
            size="sm"
            onClick={handleDeploy}
            disabled={isDeploying}
            className={cn(
              'h-7 gap-1.5 rounded-md px-3 text-xs font-medium',
              isDeployed
                ? 'border border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success-strong)] hover:bg-[var(--status-success-bg)]'
                : 'border border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)]',
            )}
          >
            {isDeploying ? <Loader2 size={13} className="animate-spin" /> : <Rocket size={13} />}
            {isDeploying
              ? t('workspace.deploying', { defaultValue: 'Publishing' })
              : isDeployed
                ? t('workspace.activeDeploymentShort', { defaultValue: 'Published' })
                : t('workspace.publish', { defaultValue: 'Publish' })}
          </Button>

          <Button
            size="sm"
            onClick={handleRunClick}
            className={cn(
              'h-7 gap-1.5 rounded-md px-3 text-xs font-medium',
              isExecuting
                ? 'bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]'
                : 'bg-primary text-white hover:bg-primary/90',
            )}
          >
            {isExecuting ? (
              <>
                <Square size={13} className="fill-current" />
                {t('workspace.stop')}
              </>
            ) : (
              <>
                <Play size={13} className="fill-current" />
                {t('workspace.run')}
              </>
            )}
          </Button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        <CodeEditor />
      </div>

      <RunInputModal
        isOpen={isRunModalOpen}
        input={runInput}
        onInputChange={setRunInput}
        onStart={handleStartExecution}
        onClose={() => setIsRunModalOpen(false)}
      />

      {showExecutionPanel && (
        <DebugPanel agentId={graphId} agentVersionId={versionId ?? ''} workspaceId={workspaceId} />
      )}
    </div>
  )
}
