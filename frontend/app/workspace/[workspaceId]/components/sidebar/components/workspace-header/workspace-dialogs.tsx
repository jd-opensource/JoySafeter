'use client'

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
import { useTranslation } from '@/lib/i18n'

interface WorkspaceDialogsProps {
  deleteConfirmOpen: boolean
  setDeleteConfirmOpen: (open: boolean) => void
  workspaceToDelete: { id: string; name: string } | null
  setWorkspaceToDelete: (workspace: { id: string; name: string } | null) => void
  onConfirmDelete: () => void
}

export function WorkspaceDialogs({
  deleteConfirmOpen,
  setDeleteConfirmOpen,
  workspaceToDelete,
  setWorkspaceToDelete,
  onConfirmDelete,
}: WorkspaceDialogsProps) {
  const { t } = useTranslation()

  return (
    <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
      <AlertDialogContent variant="destructive">
        <AlertDialogHeader>
          <AlertDialogTitle>{t('workspace.deleteConfirmTitle')}</AlertDialogTitle>
          <AlertDialogDescription>
            {workspaceToDelete ? (
              <>
                {t('workspace.deleteConfirmMessagePrefix')}{' '}
                <span className="font-semibold text-[var(--status-error)]">{workspaceToDelete.name}</span>
                {t('workspace.deleteConfirmMessageSuffix')}
              </>
            ) : (
              t('workspace.deleteConfirmMessageDefault')
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={() => {
              setDeleteConfirmOpen(false)
              setWorkspaceToDelete(null)
            }}
          >
            {t('workspace.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirmDelete}
            className="bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]"
          >
            {t('workspace.delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
