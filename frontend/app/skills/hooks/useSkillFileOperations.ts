import { useState, useCallback } from 'react'
import { UseFormReturn } from 'react-hook-form'

import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import {
  skillService,
  createSkillFile,
  createFilePath,
  validateFilePath,
  getFilenameFromPath,
} from '@/services/skillService'
import { Skill, SkillFile } from '@/types'

import { SkillFormData } from '../schemas/skillFormSchema'

interface UseSkillFileOperationsParams {
  form: UseFormReturn<SkillFormData>
  selectedSkill: Skill | null
  setSelectedSkill: (skill: Skill | null) => void
  activeFilePath: string | null
  setActiveFilePath: (path: string | null) => void
  fileToDelete: SkillFile | null
  setFileToDelete: (file: SkillFile | null) => void
  fileToRename: SkillFile | null
  setFileToRename: (file: SkillFile | null) => void
  renameValue: string
  setRenameValue: (value: string) => void
  fileOperationLoading: boolean
  setFileOperationLoading: (loading: boolean) => void
  setImportModal: (modal: 'local' | 'newfile' | null) => void
}

export function useSkillFileOperations({
  form,
  selectedSkill,
  setSelectedSkill,
  activeFilePath,
  setActiveFilePath,
  fileToDelete,
  setFileToDelete,
  fileToRename,
  setFileToRename,
  renameValue,
  setRenameValue,
  fileOperationLoading,
  setFileOperationLoading,
  setImportModal,
}: UseSkillFileOperationsParams) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [newFileDirectory, setNewFileDirectory] = useState<string | null>(null)

  const handleAddFile = useCallback(
    (directory: string | null = null) => {
      setNewFileDirectory(directory)
      setImportModal('newfile')
    },
    [setImportModal],
  )

  const handleCreateNewFile = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const formEl = e.target as HTMLFormElement
      const filename = (formEl.elements.namedItem('filename') as HTMLInputElement).value
      const fileType = (formEl.elements.namedItem('filetype') as HTMLInputElement).value || 'text'

      if (!filename.trim()) {
        toast({ variant: 'destructive', title: 'Filename is required' })
        return
      }

      const newFile = createSkillFile(newFileDirectory, filename, fileType, '')
      const currentFiles = form.getValues('files') || []
      form.setValue('files', [...currentFiles, newFile as SkillFile])

      setActiveFilePath(newFile.path || null)
      setImportModal(null)
    },
    [form, newFileDirectory, setActiveFilePath, setImportModal, toast],
  )

  const handleDeleteFile = useCallback(async () => {
    if (!fileToDelete) {
      return
    }

    setFileOperationLoading(true)
    try {
      if (fileToDelete.id && selectedSkill?.id) {
        await skillService.deleteFile(fileToDelete.id)

        const updatedSkill = await skillService.getSkill(selectedSkill.id)
        if (updatedSkill) {
          setSelectedSkill(updatedSkill)
          form.setValue('files', updatedSkill.files || [])
        }
      } else {
        const currentFiles = form.getValues('files') || []
        form.setValue(
          'files',
          currentFiles.filter((f: SkillFile) => f.path !== fileToDelete.path),
        )
      }

      if (activeFilePath === fileToDelete.path) {
        setActiveFilePath(null)
      }

      toast({ title: t('skills.fileDeleted') })
    } catch (e) {
      console.error('Failed to delete file:', e)
      toast({ variant: 'destructive', title: t('skills.fileDeleteFailed') })
    } finally {
      setFileOperationLoading(false)
      setFileToDelete(null)
    }
  }, [
    fileToDelete,
    selectedSkill,
    form,
    activeFilePath,
    setActiveFilePath,
    setFileOperationLoading,
    setFileToDelete,
    setSelectedSkill,
    toast,
    t,
  ])

  const handleRenameFile = useCallback(async () => {
    if (!fileToRename || !renameValue.trim()) {
      return
    }

    const lastSlashIndex = fileToRename.path.lastIndexOf('/')
    const oldDirectory = lastSlashIndex > 0 ? fileToRename.path.substring(0, lastSlashIndex) : null
    const newPath = createFilePath(oldDirectory, renameValue.trim())

    const validation = validateFilePath(newPath)
    if (!validation.valid) {
      toast({ variant: 'destructive', title: validation.error || t('skills.invalidPath') })
      return
    }

    setFileOperationLoading(true)
    try {
      if (fileToRename.id && selectedSkill?.id) {
        await skillService.updateFile(fileToRename.id, {
          path: newPath,
          file_name: renameValue.trim(),
        })

        const updatedSkill = await skillService.getSkill(selectedSkill.id)
        if (updatedSkill) {
          setSelectedSkill(updatedSkill)
          form.setValue('files', updatedSkill.files || [])
        }
      } else {
        const currentFiles = form.getValues('files') || []
        form.setValue(
          'files',
          currentFiles.map((f: SkillFile) =>
            f.path === fileToRename.path
              ? { ...f, path: newPath, file_name: renameValue.trim(), name: renameValue.trim() }
              : f,
          ),
        )
      }

      if (activeFilePath === fileToRename.path) {
        setActiveFilePath(newPath)
      }

      toast({ title: t('skills.fileRenamed') })
    } catch (e) {
      console.error('Failed to rename file:', e)
      toast({ variant: 'destructive', title: t('skills.fileRenameFailed') })
    } finally {
      setFileOperationLoading(false)
      setFileToRename(null)
      setRenameValue('')
    }
  }, [
    fileToRename,
    renameValue,
    selectedSkill,
    form,
    activeFilePath,
    setActiveFilePath,
    setFileOperationLoading,
    setFileToRename,
    setRenameValue,
    setSelectedSkill,
    toast,
    t,
  ])

  const openRenameDialog = useCallback(
    (file: SkillFile) => {
      setFileToRename(file)
      setRenameValue(getFilenameFromPath(file.path))
    },
    [setFileToRename, setRenameValue],
  )

  return {
    newFileDirectory,
    setNewFileDirectory,
    handleAddFile,
    handleCreateNewFile,
    handleDeleteFile,
    handleRenameFile,
    openRenameDialog,
  }
}
