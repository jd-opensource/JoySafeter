'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
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
import { useParams } from 'next/navigation'
import React, { useRef, useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { useDeploymentStatus, graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useDeploymentStore } from '@/stores/deploymentStore'

import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'

import { ApiAccessDialog } from './ApiAccessDialog'
import { DeploymentHistoryPanel } from './DeploymentHistoryPanel'

interface BuilderToolbarProps {
  onImport: (e: React.ChangeEvent<HTMLInputElement>) => void
  onExport: () => void
  onRunClick: () => void
  agentId?: string
  nodesCount?: number
}

export function BuilderToolbar({
  onImport,
  onExport,
  onRunClick,
  agentId,
  nodesCount = 0,
}: BuilderToolbarProps) {
  const { workspaceId = '' } = useParams() as { workspaceId: string }
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const {
    isExecuting,
    stopExecution,
    showPanel: showExecutionPanel,
    togglePanel: toggleExecutionPanel,
  } = useExecutionStore()

  // Use React Query hook to get deployment status (automatic caching and deduplication)
  const { data: deploymentStatus } = useDeploymentStatus(agentId)

  // Get UI state and operation methods from Zustand store
  const { isDeploying, deploy } = useDeploymentStore()

  const {
    setDeployedAt,
  } = useBuilderStore()

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showDeploymentHistory, setShowDeploymentHistory] = useState(false)
  const [showApiAccess, setShowApiAccess] = useState(false)

  // Sync deployment status with builderStore
  useEffect(() => {
    if (deploymentStatus) {
      if (deploymentStatus.isDeployed && deploymentStatus.deployedAt) {
        setDeployedAt(deploymentStatus.deployedAt)
      } else {
        setDeployedAt(null)
      }
    }
  }, [deploymentStatus, setDeployedAt])

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

    try {
      const result = await deploy(agentId)

      // Refresh deployment status cache after successful deployment
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(agentId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(agentId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })

      if (result.message.includes('No changes')) {
        toast({
          title: t('workspace.noChanges'),
          description: t('workspace.noChangesDescription', { version: result.version }),
        })
      } else {
        toast({
          title: t('workspace.deploySuccess'),
          description: t('workspace.deploySuccessDescription', { version: result.version }),
          variant: 'success',
        })
      }
    } catch (error) {
      console.error('Deploy failed:', error)
      toast({
        title: t('workspace.deployFailed'),
        description: t('workspace.deployFailedDescription'),
        variant: 'destructive',
      })
    }
  }

  const getDeployTooltip = () => {
    if (nodesCount === 0) {
      return t('workspace.cannotDeployEmpty')
    }
    if (isDeploying) {
      return t('workspace.deploying')
    }
    if (deploymentStatus?.isDeployed) {
      if ((deploymentStatus as any).needsRedeployment) {
        return t('workspace.needsRedeployment')
      }
      return t('workspace.activeDeployment')
    }
    return t('workspace.deployAgent')
  }

  const getDeployText = () => {
    if (isDeploying) {
      return t('workspace.deploying', { defaultValue: 'Publishing' })
    }
    if (deploymentStatus?.isDeployed) {
      if ((deploymentStatus as any).needsRedeployment) {
        return t('workspace.publishUpdate', { defaultValue: 'Publish Update' })
      }
      return t('workspace.activeDeploymentShort', { defaultValue: 'Published' })
    }
    return t('workspace.publish', { defaultValue: 'Publish' })
  }

  const isDeployed = deploymentStatus?.isDeployed || false
  const needsRedeployment = (deploymentStatus as any)?.needsRedeployment || false

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
                        disabled={isDeploying || nodesCount === 0}
                        className={cn(
                          'h-7 gap-1.5 rounded-r-none px-3 text-base font-medium transition-all',
                          isDeployed
                            ? needsRedeployment
                              ? 'border border-primary border-r-white/20 bg-primary text-primary-foreground hover:bg-primary/90'
                              : 'border border-[var(--status-success-border)] border-r-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success-strong)] hover:bg-[var(--status-success-bg)]'
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
                        ? needsRedeployment
                          ? 'border border-l-0 border-primary bg-primary text-primary-foreground hover:bg-primary/90'
                          : 'border border-l-0 border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success-strong)] hover:bg-[var(--status-success-bg)]'
                        : 'border border-l-0 border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)]',
                    )}
                    aria-label={t('workspace.deployOptions', { defaultValue: 'Deploy options' })}
                  >
                    <ChevronDown size={14} />
                  </Button>
                </DropdownMenuTrigger>
              </div>

              <DropdownMenuContent align="end" side="bottom" sideOffset={8}>
                <DropdownMenuItem onClick={handleDeploy} disabled={isDeploying || nodesCount === 0}>
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
