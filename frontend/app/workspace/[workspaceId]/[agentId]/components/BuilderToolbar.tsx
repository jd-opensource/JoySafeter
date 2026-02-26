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
  ShieldCheck,
  FileJson,
  Database,
} from 'lucide-react'
import React, { useRef, useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useDeploymentStatus, graphKeys } from '@/hooks/queries/graphs'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { useDeploymentStore } from '@/stores/deploymentStore'

import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'

import { DeploymentHistoryPanel } from './DeploymentHistoryPanel'

interface BuilderToolbarProps {
  onImport: (e: React.ChangeEvent<HTMLInputElement>) => void
  onExport: () => void
  onRunClick: () => void
  agentId?: string
  nodesCount?: number
}

export const BuilderToolbar: React.FC<BuilderToolbarProps> = ({
  onImport,
  onExport,
  onRunClick,
  agentId,
  nodesCount = 0,
}) => {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { isExecuting, stopExecution, showPanel: showExecutionPanel, togglePanel: toggleExecutionPanel } = useExecutionStore()

  // Use React Query hook to get deployment status (automatic caching and deduplication)
  const { data: deploymentStatus } = useDeploymentStatus(agentId)

  // Get UI state and operation methods from Zustand store
  const { isDeploying, deploy } = useDeploymentStore()

  const {
    setDeployedAt,
    toggleGraphStatePanel,
    toggleSchemaExport,
    toggleValidationSummary,
    validateGraph,
    isValidating,
    showAdvancedSettings,
    toggleAdvancedSettings
  } = useBuilderStore()

  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showDeploymentHistory, setShowDeploymentHistory] = useState(false)

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

    // Pre-deployment validation (Async from backend)
    const isValid = await validateGraph()

    if (!isValid) {
      toast({
        title: t('workspace.validationFailed', { defaultValue: 'Validation Failed' }),
        description: t('workspace.checkValidationPanel', { defaultValue: 'Please check the validation panel for errors.' }),
        variant: 'destructive',
      })
      // Open validation panel to show errors
      toggleValidationSummary(true)
      return
    }

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
      return t('workspace.deploying')
    }
    if (deploymentStatus?.isDeployed) {
      if ((deploymentStatus as any).needsRedeployment) {
        return t('workspace.redeploy')
      }
      return t('workspace.active')
    }
    return t('workspace.deploy')
  }

  const isDeployed = deploymentStatus?.isDeployed || false
  const needsRedeployment = (deploymentStatus as any)?.needsRedeployment || false

  return (
    <>
      <TooltipProvider delayDuration={300}>
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-200/60">
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
                  className="h-7 w-7 hover:bg-gray-100/80 rounded-md"
                >
                  <MoreHorizontal size={16} className="text-gray-600" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="bottom" sideOffset={8}>
                <DropdownMenuItem onClick={() => toggleAdvancedSettings()} className="font-medium text-blue-600">
                  {showAdvancedSettings ? 'Hide Advanced Mode' : 'Show Advanced Mode'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {showAdvancedSettings && (
                  <>
                    <DropdownMenuItem onClick={() => toggleGraphStatePanel(true)}>
                      <Database size={14} className="mr-2" /> Graph State Schema
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => toggleSchemaExport(true)}>
                      <FileJson size={14} className="mr-2" /> Schema
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                )}
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

            {/* Validation Button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => toggleValidationSummary(true)}
                  className="h-7 w-7 hover:bg-gray-100/80 rounded-md"
                >
                  <ShieldCheck size={16} className="text-gray-600" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">{t('workspace.validateGraph')}</TooltipContent>
            </Tooltip>

            {/* Toggle Execution Panel */}
            {!showExecutionPanel && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => toggleExecutionPanel(true)}
                    className="h-7 w-7 hover:bg-gray-100/80 rounded-md"
                  >
                    <ChevronDown size={16} className="text-gray-600" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">{t('workspace.showExecutionPanel')}</TooltipContent>
              </Tooltip>
            )}
          </div>

          {/* Right: Action Buttons */}
          <div className="flex items-center gap-2">
            {/* Deploy Button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    size="sm"
                    onClick={handleDeploy}
                    disabled={isDeploying || nodesCount === 0}
                    className={cn(
                      'h-7 px-3 gap-1.5 text-[13px] font-medium rounded-md transition-all',
                      isDeployed
                        ? needsRedeployment
                          ? 'bg-orange-50 hover:bg-orange-100 text-orange-700 border border-orange-200'
                          : 'bg-green-50 hover:bg-green-100 text-green-700 border border-green-200'
                        : 'bg-white hover:bg-gray-50 text-gray-700 border border-gray-200 shadow-sm hover:shadow'
                    )}
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

            {/* Run Button */}
            <Button
              size="sm"
              onClick={toggleRun}
              className={cn(
                'h-7 px-3 gap-1.5 text-[13px] font-medium rounded-md shadow-sm hover:shadow transition-all',
                isExecuting
                  ? 'bg-red-500 hover:bg-red-600 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
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
    </>
  )
}
