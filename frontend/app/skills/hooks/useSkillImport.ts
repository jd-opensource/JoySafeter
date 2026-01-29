import { useState, useRef, useCallback } from 'react'


// File is the browser's native File type (from FileList), not a custom type
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import {
  processLocalDirectoryFiles,
  convertFilesToSkillFiles,
  ValidationResult,
} from '@/services/skillService'
import { getSkillValidationMessage } from '@/utils/skillValidationI18n'

/**
 * Hook for managing skill import functionality
 */
export function useSkillImport() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [importModal, setImportModal] = useState<'local' | 'newfile' | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [localImportFiles, setLocalImportFiles] = useState<File[]>([])
  const [localImportValidation, setLocalImportValidation] = useState<ValidationResult | null>(null)
  const [rejectedFiles, setRejectedFiles] = useState<Array<{ path: string; reason: string }>>([])
  const folderInputRef = useRef<HTMLInputElement>(null)

  const handleFolderSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files
    if (!fileList || fileList.length === 0) {
      setLocalImportFiles([])
      setLocalImportValidation(null)
      return
    }

    const { files, validation } = await processLocalDirectoryFiles(fileList)
    setLocalImportFiles(files)
    setLocalImportValidation(validation)
    setRejectedFiles(validation.rejectedFiles || [])
  }, [])

  const handleImportLocal = useCallback(async (
    onImportSuccess: (skillFiles: any[], parsedFrontmatter: any) => Promise<void>
  ) => {
    if (!localImportValidation?.valid || localImportFiles.length === 0) {
      return
    }

    setActionLoading(true)
    try {
      // Convert files to SkillFile format
      const { skillFiles, rejectedFiles: rejected } = await convertFilesToSkillFiles(localImportFiles)

      // Store rejected files for display
      setRejectedFiles(rejected)

      // Check for rejected binary files
      if (rejected.length > 0) {
        // Still continue if we have valid files, but show warning
        if (skillFiles.length === 0) {
          toast({
            variant: 'destructive',
            title: t('skills.importFailed'),
            description: t('skills.allFilesBinary'),
          })
          setActionLoading(false)
          return
        }
      }

      // Find SKILL.md and parse its content
      const skillMdFile = skillFiles.find(f => f.path === 'SKILL.md')
      if (!skillMdFile?.content) {
        throw new Error('SKILL.md content is required')
      }

      const { parseSkillMd } = await import('@/services/skillService')
      const parsed = parseSkillMd(skillMdFile.content)

      await onImportSuccess(skillFiles, parsed.frontmatter)
      
      // Reset import state
      setImportModal(null)
      toast({ title: t('skills.localImportSuccess') })
    } catch (e) {
      console.error('Import failed:', e)
      const description = getSkillValidationMessage(e, t)
      toast({
        variant: 'destructive',
        title: t('skills.importFailed'),
        ...(description && { description }),
      })
    } finally {
      setActionLoading(false)
    }
  }, [localImportValidation, localImportFiles, toast, t])

  const resetImport = useCallback(() => {
    setImportModal(null)
    setLocalImportFiles([])
    setLocalImportValidation(null)
    setRejectedFiles([])
    if (folderInputRef.current) {
      folderInputRef.current.value = ''
    }
  }, [])

  return {
    importModal,
    setImportModal,
    actionLoading,
    localImportFiles,
    localImportValidation,
    rejectedFiles,
    folderInputRef,
    handleFolderSelect,
    handleImportLocal,
    resetImport,
  }
}
