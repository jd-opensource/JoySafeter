'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Upload,
  Download,
  Play,
  Square,
  MoreHorizontal,
  ChevronDown,
  Rocket,
  Loader2,
  History,
  Terminal,
} from 'lucide-react'
import React, { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { versionKeys } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import { deploymentAdapter } from '../services/deploymentAdapter'
import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/execution/executionStore'

import { ApiAccessDialog } from './ApiAccessDialog'
import { AddNodePalette } from './AddNodePalette'
import { DeploymentHistoryPanel } from './DeploymentHistoryPanel'

interface BuilderToolbarProps {
  onImport: (e: React.ChangeEvent<HTMLInputElement>) => void
  onExport: () => void
  onRunClick: () => void
  agentId?: string
  nodesCount?: number
  onAddNode?: (node: { type: string; label: string }) => void
}

export function BuilderToolbar({
  onImport,
  onExport,
  onRunClick,
  agentId,
  nodesCount = 0,
  onAddNode,
}: BuilderToolbarProps) {
  const { workspaceId } = useCurrentWorkspace()
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { canAdmin, canEdit } = useUserPermissionsContext()
  const {
    isExecuting,
    stopExecution,
    showPanel: showExecutionPanel,
    togglePanel: toggleExecutionPanel,
  } = useExecutionStore()

  const deployedAt = useBuilderStore((s) => s.deployedAt)
  const setDeployedAt = useBuilderStore((s) => s.setDeployedAt)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showDeploymentHistory, setShowDeploymentHistory] = useState(false)
  const [showApiAccess, setShowApiAccess] = useState(false)
  const [isDeploying, setIsDeploying] = useState(false)

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const toggleRun = () => {
    if (isExecuting) {
      stopExecution()
      return
    }
    onRunClick()
  }

  const handleDeploy = async () => {
    if (isDeploying || !agentId || nodesCount === 0) return

    const { versionId } = useBuilderStore.getState()
    if (!versionId) {
      toast({ title: 'No version to deploy', variant: 'destructive' })
      return
    }

    setIsDeploying(true)
    try {
      const deployment = await deploymentAdapter.deploy(agentId, versionId, workspaceId)
      queryClient.invalidateQueries({ queryKey: versionKeys.all(agentId, workspaceId) })
      setDeployedAt(deployment.published_at || new Date().toISOString())
      toast({
        title: t('workspace.deploySuccess'),
        description: t('workspace.deploySuccessDescription', { version: 'latest' }),
        variant: 'success',
      })
    } catch (error) {
      console.error('Deploy failed:', error)
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

  const getDeployTooltip = () => {
    if (nodesCount === 0) {
      return t('workspace.cannotDeployEmpty')
    }
    if (isDeploying) {
      return t('workspace.deploying')
    }
    if (isDeployed) {
      return t('workspace.activeDeployment')
    }
    return t('workspace.deployAgent')
  }

  const getDeployText = () => {
    if (isDeploying) {
      return t('workspace.deploying', { defaultValue: 'Publishing' })
    }
    if (isDeployed) {
      return t('workspace.activeDeploymentShort', { defaultValue: 'Published' })
    }
    return t('workspace.publish', { defaultValue: 'Publish' })
  }

  return (
    <>
      <TooltipProvider delayDuration={300}>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-1">
          {/* Left: Menu and Controls */}
          <div className="flex items-center gap-1">
            <input
              type="file"
              ref={fileInputRef}
              onChange={onImport}
              accept=".json"
              className="hidden"
            />
            {/* More Menu */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 rounded-md hover:bg-[var(--surface-2)]"
                  aria-label={t('workspace.moreOptions', { defaultValue: 'More options' })}
                >
                  <MoreHorizontal size={16} className="text-[var(--text-secondary)]" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="bottom" sideOffset={8}>
                <DropdownMenuItem onClick={handleImportClick}>
                  <Upload size={14} className="mr-2" /> {t('workspace.importGraph')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={onExport}>
                  <Download size={14} className="mr-2" /> {t('workspace.exportGraph')}
                </DropdownMenuItem>
                {agentId && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => setShowDeploymentHistory(true)}>
                      <History size={14} className="mr-2" /> {t('workspace.deploymentHistory')}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Toggle Execution Panel */}
            {!showExecutionPanel && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => toggleExecutionPanel(true)}
                    className="h-7 w-7 rounded-md hover:bg-[var(--surface-2)]"
                  >
                    <ChevronDown size={16} className="text-[var(--text-secondary)]" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">{t('workspace.showExecutionPanel')}</TooltipContent>
              </Tooltip>
            )}
          </div>

          {/* Right: Action Buttons */}
          <div className="flex items-center gap-2">
            {onAddNode && (
              <Popover>
                <PopoverTrigger asChild>
                  <Button size="sm" variant="outline" className="h-7 gap-1.5 px-2.5">
                    <Plus size={13} />
                    <span>{t('agents.studio.addNode.button', { defaultValue: 'Add' })}</span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-auto p-0">
                  <AddNodePalette onSelect={onAddNode} />
                </PopoverContent>
              </Popover>
            )}

            {/* Deploy Dropdown */}
            <DropdownMenu>
              <div className="group flex rounded-md shadow-sm transition-all hover:shadow">
                {/* Main Deploy Action Button */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        size="sm"
                        onClick={handleDeploy}
                        disabled={isDeploying || nodesCount === 0 || !canAdmin}
                        className={cn(
                          'h-7 gap-1.5 rounded-r-none px-3 text-base font-medium transition-all',
                          isDeployed
                            ? 'border border-[var(--status-success-border)] border-r-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success-strong)] hover:bg-[var(--status-success-bg)]'
                            : 'border border-[var(--border)] border-r-black/10 bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)]',
                        )}
                        style={{ borderRightWidth: '1px' }}
                      >
                        {isDeploying ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Rocket size={13} strokeWidth={2} />
                        )}
                        <span>{getDeployText()}</span>
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">{getDeployTooltip()}</TooltipContent>
                </Tooltip>

                {/* Dropdown Trigger */}
                <DropdownMenuTrigger asChild>
                  <Button
                    size="sm"
                    className={cn(
                      'h-7 rounded-l-none px-1 transition-all',
                      isDeployed
                        ? 'border border-l-0 border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success-strong)] hover:bg-[var(--status-success-bg)]'
                        : 'border border-l-0 border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)]',
                    )}
                    aria-label={t('workspace.deployOptions', { defaultValue: 'Deploy options' })}
                  >
                    <ChevronDown size={14} />
                  </Button>
                </DropdownMenuTrigger>
              </div>

              <DropdownMenuContent align="end" side="bottom" sideOffset={8}>
                <DropdownMenuItem onClick={handleDeploy} disabled={isDeploying || nodesCount === 0 || !canAdmin}>
                  <Rocket size={14} className="mr-2" />
                  {getDeployText()}
                </DropdownMenuItem>
                {agentId && (
                  <DropdownMenuItem onClick={() => setShowApiAccess(true)}>
                    <Terminal size={14} className="mr-2" />
                    {t('workspace.accessApi', { defaultValue: 'Access API' })}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Run Button */}
            <Button
              size="sm"
              onClick={toggleRun}
              disabled={!canEdit}
              className={cn(
                'h-7 gap-1.5 rounded-md px-3 text-base font-medium shadow-sm transition-all hover:shadow',
                isExecuting
                  ? 'bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]'
                  : 'bg-primary text-white hover:bg-primary/90',
              )}
            >
              {isExecuting ? (
                <>
                  <Square size={13} className="fill-current" />
                  <span>{t('workspace.stop')}</span>
                </>
              ) : (
                <>
                  <Play size={13} className="fill-current" />
                  <span>{t('workspace.run')}</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </TooltipProvider>

      {/* Deployment History Panel */}
      {agentId && (
        <DeploymentHistoryPanel
          graphId={agentId}
          open={showDeploymentHistory}
          onOpenChange={setShowDeploymentHistory}
          nodesCount={nodesCount}
        />
      )}

      {/* API Access Dialog */}
      {agentId && (
        <ApiAccessDialog
          open={showApiAccess}
          onOpenChange={setShowApiAccess}
          agentId={agentId}
          workspaceId={workspaceId}
        />
      )}
    </>
  )
}
