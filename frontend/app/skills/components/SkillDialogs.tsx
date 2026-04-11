'use client'

import {
  Plus,
  Trash2,
  Loader2,
  FileText,
  FolderOpen,
  Pencil,
  Upload,
  AlertCircle,
  CheckCircle,
} from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { UnifiedDialog, ValidationBox, FileListBox } from '@/components/ui/unified-dialog'
import { useTranslation } from '@/lib/i18n'
import { SkillFile } from '@/types'

// --- Import Dialog ---

interface ImportDialogProps {
  open: boolean
  onClose: () => void
  actionLoading: boolean
  localImportFiles: File[]
  localImportValidation: { valid: boolean; errors: string[]; warnings: string[] } | null
  rejectedFiles: Array<{ path: string; reason: string }>
  folderInputRef: React.RefObject<HTMLInputElement | null>
  onFolderSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  onImport: () => void
}

export function ImportDialog({
  open,
  onClose,
  actionLoading,
  localImportFiles,
  localImportValidation,
  rejectedFiles,
  folderInputRef,
  onFolderSelect,
  onImport,
}: ImportDialogProps) {
  const { t } = useTranslation()

  return (
    <UnifiedDialog
      open={open}
      onOpenChange={() => onClose()}
      maxWidth="2xl"
      title={t('skills.importFromLocal')}
      description={t('skills.selectLocalDirectory')}
      icon={<FolderOpen size={18} />}
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            onClick={() => onClose()}
            className="h-10 border-[var(--border)] px-4 hover:bg-[var(--surface-2)]"
          >
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={actionLoading || !localImportValidation?.valid}
            onClick={onImport}
            className="h-10 bg-[var(--brand-600)] px-5 text-white shadow-sm hover:bg-[var(--brand-700)]"
          >
            {actionLoading ? (
              <Loader2 size={16} className="mr-2 animate-spin" />
            ) : (
              <Upload size={16} className="mr-2" />
            )}
            {t('skills.importSkill')}
          </Button>
        </>
      }
    >
      {/* Folder picker */}
      <div className="flex items-center gap-3">
        <input
          ref={folderInputRef}
          type="file"
          // @ts-expect-error webkitdirectory is not standard
          webkitdirectory=""
          multiple
          className="hidden"
          onChange={onFolderSelect}
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => folderInputRef.current?.click()}
          className="h-10 gap-2 border-[var(--border)] bg-[var(--surface-elevated)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)]"
        >
          <FolderOpen size={16} />
          {t('skills.selectFolder')}
        </Button>
        {localImportFiles.length > 0 && (
          <span className="text-sm text-[var(--text-tertiary)]">
            {localImportFiles.length} {t('skills.filesSelected')}
          </span>
        )}
      </div>

      {/* Validation results */}
      {localImportValidation && (
        <div className="space-y-3">
          {localImportValidation.errors.length > 0 && (
            <ValidationBox
              type="error"
              icon={<AlertCircle size={16} />}
              title={t('skills.validationErrors.title')}
              items={localImportValidation.errors.map((err) => {
                if (err === 'SKILL.md_BINARY') {
                  return t('skills.skillMdBinary')
                }
                if (err === 'SKILL.md_READ_ERROR') {
                  return t('skills.importFailed') + ': ' + t('skills.binaryFileReadError')
                }
                return err
              })}
            />
          )}
          {rejectedFiles.length > 0 && (
            <ValidationBox
              type="error"
              icon={<AlertCircle size={16} />}
              title={t('skills.binaryFilesRejected')}
              items={rejectedFiles.map((f) => {
                const reason =
                  f.reason === 'binary'
                    ? t('skills.binaryFileReason')
                    : f.reason === 'read_error'
                      ? t('skills.binaryFileReadError')
                      : f.reason
                return `${f.path} - ${reason}`
              })}
            />
          )}
          {localImportValidation.warnings.length > 0 && (
            <ValidationBox
              type="warning"
              icon={<AlertCircle size={16} />}
              title={t('skills.validationWarnings')}
              items={localImportValidation.warnings}
            />
          )}
          {localImportValidation.valid && rejectedFiles.length === 0 && (
            <ValidationBox
              type="success"
              icon={<CheckCircle size={16} />}
              title={t('skills.validationPassed')}
            />
          )}
          {rejectedFiles.length > 0 && (
            <div className="mt-2 rounded bg-[var(--surface-1)] p-2 text-xs text-[var(--text-tertiary)]">
              <strong>{t('common.tip') || 'Tip'}:</strong> {t('skills.binaryFileNotSupported')}
            </div>
          )}
        </div>
      )}

      {/* File preview */}
      {localImportFiles.length > 0 && (
        <FileListBox
          title={t('skills.filesToImport')}
          files={localImportFiles.map((file) => ({
            name: file.webkitRelativePath || file.name,
            size: file.size,
            icon: <FileText size={12} />,
          }))}
          maxShow={20}
          moreText={(count) => `... ${t('skills.andMoreFiles', { count })}`}
        />
      )}
    </UnifiedDialog>
  )
}

// --- New File Dialog ---

interface NewFileDialogProps {
  open: boolean
  onClose: () => void
  newFileDirectory: string | null
  onDirectoryChange: (dir: string | null) => void
  onCreateFile: (e: React.FormEvent) => void
}

export function NewFileDialog({
  open,
  onClose,
  newFileDirectory,
  onDirectoryChange,
  onCreateFile,
}: NewFileDialogProps) {
  return (
    <Dialog open={open} onOpenChange={() => onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus size={20} className="text-[var(--skill-brand)]" />
            Add New File
          </DialogTitle>
          <DialogDescription>
            {newFileDirectory ? (
              <>
                Create a new file in{' '}
                <code className="rounded bg-[var(--surface-3)] px-1">{newFileDirectory}/</code>
              </>
            ) : (
              <>Create a new file at root level</>
            )}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onCreateFile}>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="directory">Directory (optional)</Label>
              <Input
                id="directory"
                name="directory"
                value={newFileDirectory || ''}
                onChange={(e) => onDirectoryChange(e.target.value || null)}
                placeholder="e.g., src, lib/utils (leave empty for root)"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="filename">Filename</Label>
              <Input
                id="filename"
                name="filename"
                placeholder="e.g., main.py, config.json, README.md"
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="filetype">File Type</Label>
              <Select name="filetype" defaultValue="text">
                <SelectTrigger>
                  <SelectValue placeholder="Select file type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="python">Python</SelectItem>
                  <SelectItem value="javascript">JavaScript</SelectItem>
                  <SelectItem value="typescript">TypeScript</SelectItem>
                  <SelectItem value="markdown">Markdown</SelectItem>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="yaml">YAML</SelectItem>
                  <SelectItem value="bash">Bash/Shell</SelectItem>
                  <SelectItem value="text">Plain Text</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" className="w-full bg-[var(--skill-brand-600)] hover:bg-[var(--skill-brand-700)]">
              <Plus size={16} className="mr-2" />
              Create File
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// --- Delete File Dialog ---

interface DeleteFileDialogProps {
  fileToDelete: SkillFile | null
  onClose: () => void
  onConfirm: () => void
  loading: boolean
}

export function DeleteFileDialog({
  fileToDelete,
  onClose,
  onConfirm,
  loading,
}: DeleteFileDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog open={!!fileToDelete} onOpenChange={() => onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-[var(--status-error)]">
            <Trash2 size={20} />
            {t('skills.confirmDeleteFile')}
          </DialogTitle>
          <DialogDescription>
            {t('skills.deleteFileWarning', { filename: fileToDelete?.path || '' })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={loading}
          >
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? (
              <Loader2 size={16} className="mr-2 animate-spin" />
            ) : (
              <Trash2 size={16} className="mr-2" />
            )}
            {t('skills.deleteFile')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Rename File Dialog ---

interface RenameFileDialogProps {
  fileToRename: SkillFile | null
  renameValue: string
  onRenameValueChange: (value: string) => void
  onClose: () => void
  onConfirm: () => void
  loading: boolean
}

export function RenameFileDialog({
  fileToRename,
  renameValue,
  onRenameValueChange,
  onClose,
  onConfirm,
  loading,
}: RenameFileDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog
      open={!!fileToRename}
      onOpenChange={() => onClose()}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil size={20} className="text-[var(--brand-500)]" />
            {t('skills.renameFile')}
          </DialogTitle>
          <DialogDescription>
            {t('skills.renameFileDescription', { filename: fileToRename?.path || '' })}
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Label htmlFor="newFilename">{t('skills.newFilename')}</Label>
          <Input
            id="newFilename"
            value={renameValue}
            onChange={(e) => onRenameValueChange(e.target.value)}
            placeholder={t('skills.enterNewFilename')}
            className="mt-2"
          />
          {fileToRename && fileToRename.path.includes('/') && (
            <p className="mt-2 text-xs text-[var(--text-tertiary)]">
              {t('skills.fileWillBeLocated')}:{' '}
              <code className="rounded bg-[var(--surface-3)] px-1">
                {fileToRename.path.substring(0, fileToRename.path.lastIndexOf('/'))}/
                {renameValue || '...'}
              </code>
            </p>
          )}
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={loading}
          >
            {t('common.cancel')}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={loading || !renameValue.trim()}
            className="bg-[var(--brand-600)] hover:bg-[var(--brand-700)]"
          >
            {loading ? (
              <Loader2 size={16} className="mr-2 animate-spin" />
            ) : (
              <Pencil size={16} className="mr-2" />
            )}
            {t('skills.rename')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
