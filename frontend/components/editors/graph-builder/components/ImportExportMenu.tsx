'use client'

import { Download, MoreHorizontal, Upload } from 'lucide-react'
import { useRef } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTranslation } from '@/lib/i18n'

interface ImportExportMenuProps {
  onImport?: (e: React.ChangeEvent<HTMLInputElement>) => void
  onExport?: () => void
}

export function ImportExportMenu({ onImport, onExport }: ImportExportMenuProps) {
  const { t } = useTranslation()
  const fileInputRef = useRef<HTMLInputElement>(null)

  return (
    <>
      <input
        type="file"
        ref={fileInputRef}
        onChange={onImport}
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
          <DropdownMenuItem onClick={() => fileInputRef.current?.click()} disabled={!onImport}>
            <Upload size={14} className="mr-2" />
            {t('workspace.importGraph', { defaultValue: 'Import JSON' })}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={onExport} disabled={!onExport}>
            <Download size={14} className="mr-2" />
            {t('workspace.exportGraph', { defaultValue: 'Export JSON' })}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}
