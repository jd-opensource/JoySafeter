'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  Loader2,
  Play,
  Rocket,
  Save,
  Square,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/hooks/use-toast'
import { useAgent } from '@/hooks/queries/agents'
import { versionKeys } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { CodeEditor } from './components/CodeEditor'
import { useCodeEditorStore } from './stores/codeEditorStore'
import { useExecutionStore } from './stores/execution/executionStore'
import { ExecutionPanelNew as ExecutionPanel } from './components/execution/ExecutionPanelNew'
import { RunInputModal } from './components/RunInputModal'
import { deploymentAdapter } from './services/deploymentAdapter'
import { useBuilderStore } from './stores/builderStore'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorPage({ graphId, workspaceId }: Props) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const editorRef = useRef(null)

  const isDirty = useCodeEditorStore((s) => s.isDirty)
  const isSaving = useCodeEditorStore((s) => s.isSaving)
  const save = useCodeEditorStore((s) => s.save)
  const graphName = useCodeEditorStore((s) => s.graphName)
  const setGraphName = useCodeEditorStore((s) => s.setGraphName)

  const { data: agent } = useAgent(graphId, workspaceId)
  const deployedAt = useBuilderStore((s) => s.deployedAt)
  const setDeployedAt = useBuilderStore((s) => s.setDeployedAt)

  const {
    isExecuting,
    stopExecution,
    startExecution,
    showPanel: showExecutionPanel,
    togglePanel: toggleExecutionPanel,
  } = useExecutionStore()

  const [isRunModalOpen, setIsRunModalOpen] = useState(false)
  const [runInput, setRunInput] = useState('')
  const [isDeploying, setIsDeploying] = useState(false)

  const handleRunClick = () => {
    if (isExecuting) {
      stopExecution()
      return
    }
    setIsRunModalOpen(true)
  }

  const handleStartExecution = () => {
    if (!runInput.trim()) return
    setIsRunModalOpen(false)
    startExecution(runInput)
    setRunInput('')
  }

  const handleDeploy = async () => {
    if (isDeploying || !graphId) return
    const { versionId } = useBuilderStore.getState()
    if (!versionId) {
      toast({ title: t('workspace.noVersionToDeploy', { defaultValue: 'No version to deploy' }), variant: 'destructive' })
      return
    }
    if (isDirty) await save()
    setIsDeploying(true)
    try {
      const deployment = await deploymentAdapter.deploy(graphId, versionId, workspaceId, 'code')
      queryClient.invalidateQueries({ queryKey: versionKeys.all(graphId, workspaceId) })
      setDeployedAt(deployment.published_at || new Date().toISOString())
      toast({ title: t('workspace.deploySuccess'), variant: 'success' })
    } catch (error) {
      toast({
        title: t('workspace.deployFailed'),
        description: error instanceof Error ? error.message : t('workspace.deployFailedDescription'),
        variant: 'destructive',
      })
    } finally {
      setIsDeploying(false)
    }
  }

  const isDeployed = Boolean(deployedAt)

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
        {/* Left: name + save */}
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

        {/* Right: toggle panel + deploy + run */}
        <div className="flex items-center gap-2">
          {/* Toggle execution panel */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => toggleExecutionPanel(!showExecutionPanel)}
            className="h-7 w-7 rounded-md hover:bg-[var(--surface-2)]"
          >
            {showExecutionPanel ? (
              <ChevronDown size={16} className="text-[var(--text-secondary)]" />
            ) : (
              <ChevronUp size={16} className="text-[var(--text-secondary)]" />
            )}
          </Button>

          {/* Deploy */}
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

          {/* Run / Stop */}
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

      {/* Editor area */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <CodeEditor ref={editorRef} />
      </div>

      {/* Run Input Modal */}
      <RunInputModal
        isOpen={isRunModalOpen}
        input={runInput}
        onInputChange={setRunInput}
        onStart={handleStartExecution}
        onClose={() => setIsRunModalOpen(false)}
      />

      {/* Execution Panel - Bottom Dock (same as graph builder) */}
      {showExecutionPanel && <ExecutionPanel />}
    </div>
  )
}
