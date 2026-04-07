'use client'

import {
  History,
  Loader2,
} from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

import { useDeploymentHistory } from '../hooks/useDeploymentHistory'

import { DeploymentPreview } from './DeploymentPreview'
import { DeploymentVersionsList } from './DeploymentVersionsList'

interface DeploymentHistoryPanelProps {
  graphId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  nodesCount?: number
}

export function DeploymentHistoryPanel({
  graphId,
  open,
  onOpenChange,
  nodesCount: _nodesCount = 0,
}: DeploymentHistoryPanelProps) {
  const {
    t,
    deploymentStatus,
    versions,
    totalVersions,
    totalPages,
    isLoadingVersions,
    previewMode,
    setPreviewMode,
    selectedVersion,
    selectedVersionInfo,
    showToggle,
    isLoadingPreview,
    previewState,
    editingVersion,
    editName,
    setEditName,
    isSaving,
    isUndeploying,
    currentPage,
    handleSelectVersion,
    handlePageChange,
    handleRevertClick,
    handleDeleteClick,
    handleStartEdit,
    handleCancelEdit,
    handleSaveName,
    formatDate,
    revertConfirmOpen,
    setRevertConfirmOpen,
    versionToRevert,
    setVersionToRevert,
    isReverting,
    handleConfirmRevert,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    versionToDelete,
    setVersionToDelete,
    isDeleting,
    handleConfirmDelete,
    undeployConfirmOpen,
    setUndeployConfirmOpen,
    handleConfirmUndeploy,
  } = useDeploymentHistory(graphId, open, onOpenChange)

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-2xl sm:max-w-[800px]">
          <DialogHeader className="shrink-0 border-b border-[var(--border-muted)] px-4 py-3.5">
            <DialogTitle className="flex items-center gap-2">
              <History size={20} />
              {t('workspace.deploymentHistory')}
            </DialogTitle>
          </DialogHeader>

          <div className="custom-scrollbar flex-1 overflow-y-auto px-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              {/* Left: Preview area */}
              <DeploymentPreview
                previewMode={previewMode}
                selectedVersion={selectedVersion}
                selectedVersionName={selectedVersionInfo?.name || (selectedVersion ? `v${selectedVersion}` : undefined)}
                showToggle={showToggle}
                isLoadingPreview={isLoadingPreview}
                previewState={previewState}
                onSetPreviewMode={setPreviewMode}
                t={t}
              />

              {/* Right: Version list */}
              <DeploymentVersionsList
                versions={versions}
                isLoadingVersions={isLoadingVersions}
                selectedVersion={selectedVersion}
                editingVersion={editingVersion}
                editName={editName}
                isSaving={isSaving}
                deploymentStatus={deploymentStatus}
                isUndeploying={isUndeploying}
                totalPages={totalPages}
                totalVersions={totalVersions}
                currentPage={currentPage}
                onSelectVersion={handleSelectVersion}
                onRevertClick={handleRevertClick}
                onStartEdit={handleStartEdit}
                onCancelEdit={handleCancelEdit}
                onSaveName={handleSaveName}
                onEditNameChange={setEditName}
                onDeleteClick={handleDeleteClick}
                onUndeployClick={() => setUndeployConfirmOpen(true)}
                onPageChange={handlePageChange}
                formatDate={formatDate}
                t={t}
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Revert confirmation dialog */}
      <AlertDialog open={revertConfirmOpen} onOpenChange={setRevertConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.revertConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {versionToRevert !== null ? (
                <>
                  {t('workspace.revertConfirmMessagePrefix')}{' '}
                  <span className="font-semibold text-[var(--status-error)]">
                    {versions.find((v) => v.version === versionToRevert)?.name ||
                      `v${versionToRevert}`}
                  </span>{' '}
                  {t('workspace.revertConfirmMessageSuffix')}
                </>
              ) : (
                t('workspace.revertConfirmMessageDefault')
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                setRevertConfirmOpen(false)
                setVersionToRevert(null)
              }}
              disabled={isReverting}
            >
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRevert}
              disabled={isReverting}
              className="bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]"
            >
              {isReverting ? (
                <>
                  <Loader2 size={14} className="mr-1 animate-spin" />
                  {t('workspace.reverting')}
                </>
              ) : (
                t('workspace.confirmRevert')
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete version confirmation dialog */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.deleteVersionConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {versionToDelete !== null ? (
                <>
                  {t('workspace.deleteVersionConfirmMessagePrefix')}{' '}
                  <span className="font-semibold text-[var(--status-error)]">
                    {versions.find((v) => v.version === versionToDelete)?.name ||
                      `v${versionToDelete}`}
                  </span>{' '}
                  {t('workspace.deleteVersionConfirmMessageSuffix')}
                </>
              ) : (
                t('workspace.deleteVersionConfirmMessageDefault')
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                setDeleteConfirmOpen(false)
                setVersionToDelete(null)
              }}
              disabled={isDeleting}
            >
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              disabled={isDeleting}
              className="bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]"
            >
              {isDeleting ? (
                <>
                  <Loader2 size={14} className="mr-1 animate-spin" />
                  {t('workspace.deleting')}
                </>
              ) : (
                t('workspace.confirmDelete')
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Undeploy graph confirmation dialog */}
      <AlertDialog open={undeployConfirmOpen} onOpenChange={setUndeployConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.undeployConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('workspace.undeployConfirmMessage')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => setUndeployConfirmOpen(false)}
              disabled={isUndeploying}
            >
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmUndeploy}
              disabled={isUndeploying}
              className="bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]"
            >
              {isUndeploying ? (
                <>
                  <Loader2 size={14} className="mr-1 animate-spin" />
                  {t('workspace.undeploying')}
                </>
              ) : (
                t('workspace.confirmUndeploy')
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
