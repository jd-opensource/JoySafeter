'use client'

import React from 'react'
import {
  History,
  RotateCcw,
  Edit2,
  Check,
  X,
  Loader2,
  Clock,
  User,
  Eye,
  Rocket,
  Trash2,
  XCircle,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import type { GraphDeploymentVersion, GraphDeploymentStatus } from '@/services/graphDeploymentService'

function formatDeploymentDate(dateString: string): string {
  const date = new Date(dateString)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

interface DeploymentVersionsListProps {
  versions: GraphDeploymentVersion[]
  isLoadingVersions: boolean
  selectedVersion: number | null
  editingVersion: number | null
  editName: string
  isSaving: boolean
  deploymentStatus: GraphDeploymentStatus | undefined
  isUndeploying: boolean
  totalPages: number
  totalVersions: number
  currentPage: number
  onSelectVersion: (version: number) => void
  onRevertClick: (version: number) => void
  onStartEdit: (version: GraphDeploymentVersion) => void
  onCancelEdit: () => void
  onSaveName: () => void
  onEditNameChange: (name: string) => void
  onDeleteClick: (version: number) => void
  onUndeployClick: () => void
  onPageChange: (page: number) => void
}

export const DeploymentVersionsList = React.memo(function DeploymentVersionsList({
  versions,
  isLoadingVersions,
  selectedVersion,
  editingVersion,
  editName,
  isSaving,
  deploymentStatus,
  isUndeploying,
  totalPages,
  totalVersions,
  currentPage,
  onSelectVersion,
  onRevertClick,
  onStartEdit,
  onCancelEdit,
  onSaveName,
  onEditNameChange,
  onDeleteClick,
  onUndeployClick,
  onPageChange,
}: DeploymentVersionsListProps) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      {/* Current deployment status */}
      {deploymentStatus && (
        <div className="rounded-lg border bg-[var(--surface-2)] p-2 text-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Rocket
                size={14}
                className={
                  deploymentStatus.isDeployed ? 'text-[var(--status-success)]' : 'text-[var(--text-muted)]'
                }
              />
              <span className="font-medium">
                {deploymentStatus.isDeployed
                  ? t('workspace.deployed')
                  : t('workspace.notDeployed')}
              </span>
              {deploymentStatus.deployment && (
                <span className="text-xs text-[var(--text-tertiary)]">
                  v{deploymentStatus.deployment.version}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {deploymentStatus.needsRedeployment && deploymentStatus.isDeployed && (
                <span className="rounded bg-[var(--status-warning-bg)] px-2 py-0.5 text-xs text-[var(--status-warning)]">
                  {t('workspace.needsRedeployment')}
                </span>
              )}
              {deploymentStatus.isDeployed && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs text-[var(--status-error)] hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error-hover)]"
                  onClick={onUndeployClick}
                  disabled={isUndeploying}
                >
                  {isUndeploying ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <XCircle size={12} className="mr-1" />
                  )}
                  {t('workspace.undeploy')}
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Version list */}
      <div className="max-h-[240px] space-y-1.5 overflow-y-auto">
        {isLoadingVersions ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={24} className="animate-spin text-[var(--text-muted)]" />
          </div>
        ) : versions.length === 0 ? (
          <div className="py-8 text-center text-[var(--text-tertiary)]">
            <History size={32} className="mx-auto mb-2 opacity-50" />
            <p className="text-xs">{t('workspace.noDeployments')}</p>
          </div>
        ) : (
          versions.map((version) => (
            <div
              key={version.id}
              className={cn(
                'cursor-pointer rounded-lg border-2 p-2 transition-all',
                version.isActive
                  ? 'border-[var(--status-success)] bg-[var(--status-success-bg)] shadow-sm shadow-[var(--status-success-border)]'
                  : 'border-[var(--border)] bg-[var(--surface-elevated)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)]',
                selectedVersion === version.version &&
                  'ring-2 ring-primary ring-offset-1',
              )}
              onClick={() => onSelectVersion(version.version)}
            >
              <div className="flex items-start justify-between gap-2">
                {/* Version info */}
                <div className="min-w-0 flex-1">
                  <div className="mb-0.5 flex items-center gap-1.5">
                    <span className="text-xs font-medium">v{version.version}</span>
                    {version.isActive && (
                      <span className="rounded-full bg-[var(--status-success-border)] px-1.5 py-0.5 text-2xs font-medium text-[var(--status-success-strong)]">
                        {t('workspace.active')}
                      </span>
                    )}
                    {selectedVersion === version.version && (
                      <Eye size={12} className="text-[var(--brand-500)]" />
                    )}
                  </div>

                  {/* Name editing */}
                  {editingVersion === version.version ? (
                    <div
                      className="mb-1 flex items-center gap-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Input
                        value={editName}
                        onChange={(e) => onEditNameChange(e.target.value)}
                        placeholder={t('workspace.versionName')}
                        className="h-6 text-xs"
                        autoFocus
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 w-6 p-0"
                        onClick={onSaveName}
                        disabled={isSaving}
                        aria-label={t('workspace.saveName', { defaultValue: 'Save name' })}
                      >
                        {isSaving ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Check size={12} />
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 w-6 p-0"
                        onClick={onCancelEdit}
                        disabled={isSaving}
                        aria-label={t('workspace.cancelEdit', { defaultValue: 'Cancel edit' })}
                      >
                        <X size={12} />
                      </Button>
                    </div>
                  ) : (
                    version.name && (
                      <p className="mb-0.5 truncate text-xs text-[var(--text-secondary)]">
                        {version.name}
                      </p>
                    )
                  )}

                  {/* Time and username */}
                  <div className="flex items-center gap-2 text-2xs text-[var(--text-secondary)]">
                    <div className="flex items-center gap-0.5">
                      <Clock size={10} />
                      <span>{formatDeploymentDate(version.createdAt)}</span>
                    </div>
                    {(version.createdByName || version.createdBy) && (
                      <div className="flex items-center gap-0.5">
                        <User size={10} />
                        <span className="max-w-[80px] truncate">
                          {version.createdByName || version.createdBy}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Action buttons */}
                <div
                  className="flex items-center gap-0.5"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0"
                    onClick={() => onRevertClick(version.version)}
                    title={t('workspace.revertToThisVersion')}
                  >
                    <RotateCcw size={12} />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0"
                    onClick={() => onStartEdit(version)}
                    title={t('workspace.rename')}
                  >
                    <Edit2 size={12} />
                  </Button>
                  {!version.isActive && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 w-6 p-0 text-[var(--text-muted)] hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error)]"
                      onClick={() => onDeleteClick(version.version)}
                      title={t('workspace.deleteVersion')}
                    >
                      <Trash2 size={12} />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Pagination controls */}
      {totalPages > 1 && (
        <Pagination
          page={currentPage}
          totalPages={totalPages}
          total={totalVersions}
          pageSize={Math.ceil(totalVersions / totalPages)}
          isLoading={isLoadingVersions}
          onPageChange={onPageChange}
          className="border-t border-[var(--border-muted)] pt-2"
        />
      )}
    </div>
  )
})
