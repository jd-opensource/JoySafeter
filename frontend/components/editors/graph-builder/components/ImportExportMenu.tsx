'use client'

import { AlertTriangle, Download, MoreHorizontal, Upload } from 'lucide-react'
import { useRef, useState } from 'react'

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
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

import { useGraphStore } from '../stores/graphStore'

export function ImportExportMenu() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  const doImport = async (file: File) => {
    try {
      await useGraphStore.getState().importGraph(file)
      toast({
        title: t('workspace.graphImported'),
        description: t('workspace.graphImportedSuccess', { name: file.name }),
      })
      setTimeout(() => {
        useGraphStore.getState().rfInstance?.fitView({ padding: 0.2 })
      }, 100)
    } catch (error: unknown) {
      toast({
        variant: 'destructive',
        title: t('workspace.importFailed'),
        description: error instanceof Error ? error.message : t('workspace.importFailedMessage'),
      })
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    if (useGraphStore.getState().nodes.length > 0) {
      setPendingFile(file)
    } else {
      await doImport(file)
    }
  }

  return (
    <>
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".json"
        className="hidden"
      />
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
          <DropdownMenuItem onClick={() => fileInputRef.current?.click()}>
            <Upload size={14} className="mr-2" />
            {t('workspace.importGraph', { defaultValue: 'Import JSON' })}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => useGraphStore.getState().exportGraph()}>
            <Download size={14} className="mr-2" />
            {t('workspace.exportGraph', { defaultValue: 'Export JSON' })}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog
        open={!!pendingFile}
        onOpenChange={(open) => {
          if (!open) setPendingFile(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <div className="mb-2 flex items-center gap-1 text-[var(--status-warning)]">
              <AlertTriangle size={20} />
              <AlertDialogTitle>{t('workspace.overwriteCanvas')}</AlertDialogTitle>
            </div>
            <AlertDialogDescription>{t('workspace.importOverwriteWarning')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingFile(null)}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (pendingFile) await doImport(pendingFile)
                setPendingFile(null)
              }}
              className="bg-primary hover:bg-primary/90"
            >
              {t('workspace.import')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
