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

interface DeleteAgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentToDelete: { id: string; name: string } | null
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteAgentDialog({
  open,
  onOpenChange,
  agentToDelete,
  onConfirm,
  onCancel,
}: DeleteAgentDialogProps) {
  const { t } = useTranslation()

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent variant="destructive">
        <AlertDialogHeader>
          <AlertDialogTitle>{t('workspace.deleteAgentConfirmTitle')}</AlertDialogTitle>
          <AlertDialogDescription>
            {agentToDelete ? (
              <>
                {t('workspace.deleteAgentConfirmMessagePrefix')}{' '}
                <span className="font-semibold text-[var(--status-error)]">{agentToDelete.name}</span>{' '}
                {t('workspace.deleteAgentConfirmMessageSuffix')}
              </>
            ) : (
              t('workspace.deleteAgentConfirmMessageDefault')
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>
            {t('workspace.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-[var(--status-error)] text-white hover:bg-[var(--status-error-hover)]"
          >
            {t('workspace.delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
