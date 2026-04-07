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
import { cn } from '@/lib/utils'

interface CreateAgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  newAgentName: string
  setNewAgentName: (name: string) => void
  createAgentMode: 'code' | 'canvas'
  setCreateAgentMode: (mode: 'code' | 'canvas') => void
  onConfirm: () => void
}

export function CreateAgentDialog({
  open,
  onOpenChange,
  newAgentName,
  setNewAgentName,
  createAgentMode,
  setCreateAgentMode,
  onConfirm,
}: CreateAgentDialogProps) {
  const { t } = useTranslation()

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('workspace.createAgent', { defaultValue: 'Create New Agent' })}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('workspace.createAgentDescription', { defaultValue: 'Choose a mode and name for your agent.' })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-2">
          {/* Mode Selection */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setCreateAgentMode('canvas')}
              className={cn(
                'flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all',
                createAgentMode === 'canvas'
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-[var(--border)] hover:border-primary/30'
              )}
            >
              <span className="text-sm font-medium">Canvas</span>
              <span className="text-app-xs leading-tight text-[var(--text-muted)]">
                Drag-and-drop DeepAgents builder
              </span>
            </button>
            <button
              type="button"
              onClick={() => setCreateAgentMode('code')}
              className={cn(
                'flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all',
                createAgentMode === 'code'
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-[var(--border)] hover:border-primary/30'
              )}
            >
              <span className="text-sm font-medium">Code</span>
              <span className="text-app-xs leading-tight text-[var(--text-muted)]">
                Python code to define graph structure
              </span>
            </button>
          </div>

          {/* Name Input */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-secondary)]">
              {t('workspace.agentName', { defaultValue: 'Agent Name' })}
            </label>
            <input
              value={newAgentName}
              onChange={(e) => setNewAgentName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onConfirm()}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary"
              autoFocus
            />
          </div>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel>{t('workspace.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={!newAgentName.trim()}
          >
            {t('workspace.create', { defaultValue: 'Create' })}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
