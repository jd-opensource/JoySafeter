'use client'

import {
  Search,
  Plus,
  ShieldCheck,
  Trash2,
  Save,
  FileText,
  Loader2,
  FolderOpen,
  Folder,
  Pencil,
  FileCode,
  Upload,
  AlertCircle,
  CheckCircle,
  Globe,
  Lock,
  ChevronRight,
  Wand2,
  Terminal,
} from 'lucide-react'
import Link from 'next/link'
import React, { useState, useEffect, useCallback, useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { UnifiedDialog, ValidationBox, FileListBox } from '@/components/ui/unified-dialog'
import { useSkillCollaborators } from '@/hooks/queries/skillCollaborators'
import { useCreateSkill, useUpdateSkill } from '@/hooks/queries/skills'
import { useToast } from '@/hooks/use-toast'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import {
  skillService,
  generateSkillMd,
  createSkillFile,
  getFilenameFromPath,
  createFilePath,
  validateFilePath,
  parseSkillMd,
} from '@/services/skillService'
import { SkillFile } from '@/types'
import { getSkillValidationMessage } from '@/lib/utils/skillValidationI18n'

// Import extracted components and hooks
import { CollaboratorsTab } from './components/CollaboratorsTab'
import { SkillEditor } from './components/SkillEditor'
import { SkillFileTree } from './components/SkillFileTree'
import { SkillApiAccessDialog } from './components/SkillApiAccessDialog'
import { VersionHistoryTab } from './components/VersionHistoryTab'
import { useSkillFiles } from './hooks/useSkillFiles'
import { useSkillForm } from './hooks/useSkillForm'
import { useSkillImport } from './hooks/useSkillImport'
import { useSkillManager } from './hooks/useSkillManager'


interface SkillsManagerProps {
  requestedAction?: 'manual' | 'import' | null
  onActionConsumed?: () => void
}

export default function SkillsManager({ requestedAction, onActionConsumed }: SkillsManagerProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  // Mutation hooks for skill operations
  const createSkillMutation = useCreateSkill()
  const updateSkillMutation = useUpdateSkill()

  // Use extracted hooks
  const skillManager = useSkillManager()
  const {
    loading,
    selectedSkill,
    searchQuery,
    setSearchQuery,
    isSaving,
    setIsSaving,
    setSelectedSkill,
    handleSelectSkill,
    handleDelete,
    filteredSkills,
  } = skillManager

  // Tab state for editor area
  const [activeTab, setActiveTab] = useState<'editor' | 'versions' | 'collaborators'>('editor')
  const [showApiAccess, setShowApiAccess] = useState(false)

  // Derive user role from session + collaborators
  const { data: session } = useSession()
  const { data: collabData } = useSkillCollaborators(selectedSkill?.id ?? '')
  const collaborators = collabData?.collaborators ?? []
  const currentUserId = session?.user?.id

  const userRole = useMemo(() => {
    if (!selectedSkill || !currentUserId) return 'viewer'
    if (selectedSkill.owner_id === currentUserId) return 'owner'
    const collab = collaborators.find((c) => c.userId === currentUserId)
    return collab?.role ?? 'viewer'
  }, [selectedSkill, currentUserId, collaborators])

  // Form management - initialize form hook first
  const formHook = useSkillForm({
    initialSkill: selectedSkill,
  })
  const {
    form,
    showAdvancedFields,
    setShowAdvancedFields,
  } = formHook

  // File management (depends on form files)
  const [newFileDirectory, setNewFileDirectory] = useState<string | null>(null)
  const files = form.watch('files') || []
  const fileManagement = useSkillFiles(files)
  const {
    activeFilePath,
    setActiveFilePath,
    fileTree,
    activeFile,
    fileToDelete,
    setFileToDelete,
    fileToRename,
    setFileToRename,
    renameValue,
    setRenameValue,
    fileOperationLoading,
    setFileOperationLoading,
    updateFileContent,
    updateFilesInFormData,
  } = fileManagement

  // Define handleSaveInternal after form and fileManagement are available
  const handleSaveInternal = useCallback(
    async (formData: any) => {
      setIsSaving(true)
      try {
        // Update SKILL.md content with current form data
        const currentFiles = form.getValues('files') || []
        const updatedFiles = updateFilesInFormData(currentFiles, formData, (updates) => {
          if (updates.files) {
            form.setValue('files', updates.files)
          }
        })

        const skillData = {
          name: formData.name,
          description: formData.description || '',
          license: formData.license || '',
          content: formData.content || '',
          compatibility: formData.compatibility,
          metadata: formData.metadata,
          allowed_tools: formData.allowed_tools,
          files: updatedFiles,
          source: formData.source || 'local',
          is_public: formData.is_public || false,
        }

        // Use mutation hooks instead of direct API calls
        const saved = selectedSkill?.id
          ? await updateSkillMutation.mutateAsync({ id: selectedSkill.id, ...skillData })
          : await createSkillMutation.mutateAsync(skillData)

        // React Query will automatically refresh the data after mutation
        setSelectedSkill(saved)
        toast({ title: t('skills.skillSaved') })
      } catch (e) {
        const description = getSkillValidationMessage(e, t)
        toast({
          variant: 'destructive',
          title: t('skills.saveFailed'),
          ...(description && { description }),
        })
      } finally {
        setIsSaving(false)
      }
    },
    [
      form,
      updateFilesInFormData,
      selectedSkill,
      updateSkillMutation,
      createSkillMutation,
      setSelectedSkill,
      toast,
      t,
      setIsSaving,
    ],
  )

  // Create handleSubmit that wraps form validation and save logic
  const handleSubmit = useCallback(
    (e?: React.FormEvent | React.MouseEvent) => {
      if (e) {
        e.preventDefault()
        e.stopPropagation()
      }

      // Check if form is valid before submitting
      if (!form.formState.isValid) {
        // Trigger validation to show errors
        form.trigger()
        // Show toast with validation errors
        const errors = form.formState.errors
        const errorMessages: string[] = []
        if (errors.name) errorMessages.push(t('skills.name') + ': ' + errors.name.message)
        if (errors.description)
          errorMessages.push(t('skills.description') + ': ' + errors.description.message)
        if (errors.compatibility)
          errorMessages.push('Compatibility: ' + errors.compatibility.message)

        toast({
          variant: 'destructive',
          title: t('skills.validationFailed') || 'Validation Failed',
          description:
            errorMessages.length > 0
              ? errorMessages.join(', ')
              : t('skills.pleaseFixErrors') || 'Please fix the errors in the form',
        })
        return
      }

      // Use react-hook-form's handleSubmit to validate and then call save
      form.handleSubmit(handleSaveInternal)(e)
    },
    [handleSaveInternal, form, toast, t],
  )

  // Import functionality
  const importHook = useSkillImport()
  const {
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
  } = importHook

  // Update form hook when selectedSkill changes
  useEffect(() => {
    if (selectedSkill) {
      formHook.form.reset({
        name: selectedSkill.name,
        description: selectedSkill.description,
        content: selectedSkill.content,
        license: selectedSkill.license || '',
        compatibility: selectedSkill.compatibility,
        metadata: selectedSkill.metadata || {},
        allowed_tools: selectedSkill.allowed_tools || [],
        is_public: selectedSkill.is_public || false,
        files: [...(selectedSkill.files || [])],
        source: selectedSkill.source || 'local',
      } as any)
      // Default to SKILL.md if exists
      const defaultFile =
        selectedSkill.files?.find((f) => f.path === 'SKILL.md') || selectedSkill.files?.[0]
      setActiveFilePath(defaultFile?.path || null)
    } else {
      formHook.form.reset()
      setActiveFilePath(null)
    }
  }, [selectedSkill, formHook.form, setActiveFilePath])

  // Skills are now loaded via useMySkills() hook in useSkillManager
  // No need to manually call loadSkills() on mount

  const handleNewSkillManual = useCallback(() => {
    const now = new Date().toISOString()
    const name = 'new-skill'
    const description = 'A new skill description'
    const body = `# ${name}\n\n## Overview\n\nAdd your skill instructions here.\n\n## Usage\n\nDescribe how to use this skill.`

    const skillMdContent = generateSkillMd(name, description, body, { license: 'MIT' })

    const newFiles: SkillFile[] = [
      {
        id: '',
        skill_id: '',
        path: 'SKILL.md',
        file_name: 'SKILL.md',
        file_type: 'markdown',
        content: skillMdContent,
        storage_type: 'database',
        storage_key: null,
        size: skillMdContent.length,
        created_at: now,
        updated_at: now,
        name: 'SKILL.md',
        language: 'markdown',
      },
    ]

    setSelectedSkill(null)
    form.reset({
      name,
      description,
      license: 'MIT',
      content: body,
      files: newFiles,
      source: 'local',
      compatibility: undefined,
      metadata: {},
      allowed_tools: [],
      is_public: false,
    })
    setActiveFilePath('SKILL.md')
  }, [form, setSelectedSkill, setActiveFilePath])

  useEffect(() => {
    if (requestedAction === 'manual') {
      handleNewSkillManual()
      onActionConsumed?.()
    } else if (requestedAction === 'import') {
      setImportModal('local')
      onActionConsumed?.()
    }
  }, [requestedAction, handleNewSkillManual, setImportModal, onActionConsumed])

  const handleAddFile = (directory: string | null = null) => {
    setNewFileDirectory(directory)
    setImportModal('newfile')
  }

  const handleCreateNewFile = (e: React.FormEvent) => {
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
  }

  // Handle file deletion
  const handleDeleteFile = async () => {
    if (!fileToDelete) {
      return
    }

    setFileOperationLoading(true)
    try {
      // If the file has a database ID, delete from backend
      if (fileToDelete.id && selectedSkill?.id) {
        await skillService.deleteFile(fileToDelete.id)

        // Refresh skill from backend
        const updatedSkill = await skillService.getSkill(selectedSkill.id)
        if (updatedSkill) {
          setSelectedSkill(updatedSkill)
          form.setValue('files', updatedSkill.files || [])
        }
      } else {
        // File is only in local state (not yet saved), just remove from form
        const currentFiles = form.getValues('files') || []
        form.setValue(
          'files',
          currentFiles.filter((f: SkillFile) => f.path !== fileToDelete.path),
        )
      }

      // If deleted file was active, clear selection
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
  }

  // Handle file rename
  const handleRenameFile = async () => {
    if (!fileToRename || !renameValue.trim()) {
      return
    }

    // Get directory from old path (everything before the last /)
    const lastSlashIndex = fileToRename.path.lastIndexOf('/')
    const oldDirectory = lastSlashIndex > 0 ? fileToRename.path.substring(0, lastSlashIndex) : null
    const newPath = createFilePath(oldDirectory, renameValue.trim())

    // Validate new path
    const validation = validateFilePath(newPath)
    if (!validation.valid) {
      toast({ variant: 'destructive', title: validation.error || t('skills.invalidPath') })
      return
    }

    setFileOperationLoading(true)
    try {
      // If the file has a database ID, update via backend
      if (fileToRename.id && selectedSkill?.id) {
        await skillService.updateFile(fileToRename.id, {
          path: newPath,
          file_name: renameValue.trim(),
        })

        // Refresh skill from backend
        const updatedSkill = await skillService.getSkill(selectedSkill.id)
        if (updatedSkill) {
          setSelectedSkill(updatedSkill)
          form.setValue('files', updatedSkill.files || [])
        }
      } else {
        // File is only in local state, just update form
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

      // If renamed file was active, update path
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
  }

  // Open rename dialog
  const openRenameDialog = (file: SkillFile) => {
    setFileToRename(file)
    setRenameValue(getFilenameFromPath(file.path))
  }

  const isSkillMd = activeFilePath === 'SKILL.md'
  const formData = form.watch()

  return (
    <div className="flex h-full w-full overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <ResizablePanelGroup direction="horizontal">
        {/* 1. List Sidebar */}
        <ResizablePanel defaultSize={20} minSize={15} maxSize={40} className="flex shrink-0 flex-col bg-[var(--surface-1)]">
        <div className="border-b border-[var(--border-muted)] bg-[var(--surface-2)] p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={14} />
            <Input
              placeholder={t('skills.searchCapabilities')}
              className="h-9 border-[var(--border)] bg-[var(--surface-1)] pl-9 text-xs"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="animate-spin text-[var(--text-subtle)]" />
            </div>
          ) : (
            <div className="space-y-1">
              {filteredSkills.map((skill) => (
                <div
                  key={skill.id}
                  onClick={() => handleSelectSkill(skill)}
                  className={cn(
                    'group min-w-0 cursor-pointer rounded-xl border p-3 transition-all',
                    selectedSkill?.id === skill.id
                      ? 'border-[var(--skill-brand-100)] bg-[var(--surface-elevated)] shadow-sm ring-1 ring-[var(--skill-brand-50)]'
                      : 'border-transparent hover:border-[var(--border)] hover:bg-[var(--surface-elevated)]',
                  )}
                >
                  <div className="mb-1 flex min-w-0 items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <ShieldCheck size={12} className="shrink-0 text-[var(--skill-brand-600)]" />
                      <TooltipProvider delayDuration={300}>
                        <Tooltip>
                          <TooltipTrigger className="min-w-0 truncate text-left text-sm font-semibold text-[var(--text-primary)]">
                            {skill.name}
                          </TooltipTrigger>
                          <TooltipContent side="top">{skill.name}</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      {skill.is_public && (
                        <Badge
                          variant="outline"
                          className="h-3.5 shrink-0 border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] px-1 py-0 text-xxs text-[var(--skill-brand-600)]"
                        >
                          <Globe size={8} className="mr-0.5" />
                          {t('skills.published')}
                        </Badge>
                      )}
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(skill.id)
                      }}
                      className="shrink-0 p-1 text-[var(--text-muted)] opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <p className="line-clamp-2 min-w-0 text-2xs text-[var(--text-tertiary)]">
                    {skill.description}
                  </p>
                  {skill.files && skill.files.length > 0 && (
                    <div className="mt-1.5 flex items-center gap-1 text-micro text-[var(--text-muted)]">
                      <Folder size={10} />
                      <span>{skill.files.length} files</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* 2. File Explorer & Editor */}
        <ResizablePanel defaultSize={80} className="flex flex-col bg-[var(--surface-2)] outline-none">
          <div className="flex flex-1 overflow-hidden">
            {selectedSkill || formData.name ? (
              <ResizablePanelGroup direction="horizontal">
                {/* Hierarchical File Explorer */}
                <ResizablePanel defaultSize={20} minSize={10} maxSize={30} className="flex shrink-0 flex-col border-r border-[var(--border-muted)] bg-[var(--surface-2)]">
              <div className="flex items-center justify-between border-b border-[var(--border-muted)] p-3">
                <span className="text-2xs font-bold uppercase tracking-widest text-[var(--text-muted)]">
                  {t('skills.workspace') || 'Workspace'}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 hover:bg-[var(--surface-3)]"
                  onClick={() => handleAddFile(null)}
                  title="Add file to root"
                >
                  <Plus size={14} />
                </Button>
              </div>
              <SkillFileTree
                fileTree={fileTree}
                activeFilePath={activeFilePath}
                onSelectFile={setActiveFilePath}
                onDeleteFile={setFileToDelete}
                onRenameFile={openRenameDialog}
                onAddFile={handleAddFile}
              />
                </ResizablePanel>

                <ResizableHandle withHandle />

                {/* Editor Area */}
                <ResizablePanel defaultSize={80} className="flex min-w-0 flex-col bg-[var(--surface-2)] outline-none">
                  <div className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-2)] px-4 lg:px-6">
                    <div className="flex items-center gap-4 lg:gap-6">
                      <div className="flex flex-col">
                        <h1 className="text-sm font-bold leading-tight text-[var(--text-primary)] line-clamp-1 max-w-[200px]" title={formData.name}>
                          {formData.name}
                        </h1>
                        <div className="flex items-center gap-1.5 font-mono text-micro text-[var(--text-muted)]">
                          <ChevronRight size={10} /> <span className="truncate max-w-[180px]">{activeFilePath || 'No file selected'}</span>
                        </div>
                      </div>

                      {/* Pill Tab Bar integrated in header */}
                      <div className="hidden lg:flex items-center space-x-1 rounded-lg bg-[var(--surface-3)] p-1">
                        {(['editor', 'versions', 'collaborators'] as const).map((tab) => (
                          <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={cn(
                              'px-3 py-1 text-xs font-medium rounded-md transition-colors',
                              activeTab === tab
                                ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                                : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
                            )}
                          >
                            {tab === 'editor' && t('skills.editor')}
                            {tab === 'versions' && t('skillVersions.title')}
                            {tab === 'collaborators' && t('skillCollaborators.title')}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 lg:gap-4">
                      {/* Access API Button */}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowApiAccess(true)}
                        disabled={!selectedSkill}
                        className="h-8 gap-1.5 px-3 text-xs"
                      >
                        <Terminal size={14} />
                        <span className="hidden lg:inline">{t('skills.accessApi', { defaultValue: 'Access API' })}</span>
                        <span className="lg:hidden">API</span>
                      </Button>

                      {/* Publish Toggle */}
                      <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-2 lg:px-3 py-1.5">
                        {formData.is_public ? (
                          <Globe size={14} className="text-[var(--skill-brand)]" />
                        ) : (
                          <Lock size={14} className="text-[var(--text-muted)]" />
                        )}
                        <span className="hidden lg:inline text-xs text-[var(--text-secondary)]">{t('skills.publishToStore')}</span>
                        <Switch
                          checked={formData.is_public || false}
                          onCheckedChange={(checked) => form.setValue('is_public', checked)}
                          className="data-[state=checked]:bg-[var(--skill-brand)] scale-75 lg:scale-100"
                        />
                      </div>

                      <Button
                        onClick={handleSubmit}
                        disabled={isSaving}
                        className="h-8 gap-1.5 lg:gap-2 bg-[var(--skill-brand-600)] px-3 lg:px-4 text-xs shadow-sm hover:bg-[var(--skill-brand-700)] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                        <span className="hidden lg:inline">{t('skills.saveChanges')}</span>
                        <span className="lg:hidden">Save</span>
                      </Button>
                    </div>
                  </div>

                  {/* Fallback Tab Bar for smaller screens within the pane */}
                  <div className="flex lg:hidden border-b border-[var(--border)] px-2 overflow-x-auto hide-scrollbar">
                    {(['editor', 'versions', 'collaborators'] as const).map((tab) => (
                      <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={cn(
                          'px-3 py-2 text-2xs font-medium transition-colors whitespace-nowrap',
                          activeTab === tab
                            ? 'border-b-2 border-blue-500 text-blue-600'
                            : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
                        )}
                      >
                        {tab === 'editor' && t('skills.editor')}
                        {tab === 'versions' && t('skillVersions.title')}
                        {tab === 'collaborators' && t('skillCollaborators.title')}
                      </button>
                    ))}
                  </div>

              {/* Tab Content */}
              {activeTab === 'editor' && (
                <div className="flex flex-1 flex-col overflow-hidden">
                  <SkillEditor
                    activeFilePath={activeFilePath}
                    activeFile={activeFile}
                    isSkillMd={isSkillMd}
                    form={form}
                    showAdvancedFields={showAdvancedFields}
                    onToggleAdvancedFields={() => setShowAdvancedFields(!showAdvancedFields)}
                    onUpdateFileContent={(filePath, content) => {
                      const currentFiles = form.getValues('files') || []
                      const updatedFiles = currentFiles.map((f: SkillFile) =>
                        f.path === filePath ? { ...f, content } : f,
                      )
                      form.setValue('files', updatedFiles)

                      // Update form fields if SKILL.md
                      if (filePath === 'SKILL.md') {
                        updateFileContent(filePath, content, (updates) => {
                          Object.entries(updates).forEach(([key, value]) => {
                            form.setValue(key as any, value)
                          })
                        })
                      }
                    }}
                  />
                </div>
              )}
              {activeTab === 'versions' && selectedSkill && (
                <VersionHistoryTab skillId={selectedSkill.id} userRole={userRole} />
              )}
              {activeTab === 'collaborators' && selectedSkill && (
                <CollaboratorsTab
                  skillId={selectedSkill.id}
                  ownerId={selectedSkill.owner_id || selectedSkill.created_by_id || ''}
                  userRole={userRole}
                />
              )}
                </ResizablePanel>
              </ResizablePanelGroup>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center bg-[var(--surface-1)] text-[var(--text-muted)]">
                <div className="mb-6 rounded-full border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-8 shadow-xl">
                  <ShieldCheck size={48} className="text-[var(--skill-brand-200)]" />
                </div>
                <h3 className="text-sm font-bold text-[var(--text-primary)]">{t('skills.chooseCreationMethod')}</h3>
                <p className="mt-1 text-xs text-[var(--text-muted)]">{t('skills.populateSkillsLibrary')}</p>
                <div className="mt-8 flex max-w-lg flex-wrap justify-center gap-3">
                  <Link href="/skills/creator">
                    <Button className="gap-2 bg-[var(--skill-brand-600)] text-white shadow-sm hover:bg-[var(--skill-brand-700)]">
                      <Wand2 size={16} /> {t('skills.aiCreate', 'AI Create')}
                    </Button>
                  </Link>
                  <Button variant="outline" onClick={handleNewSkillManual} className="gap-2">
                    <FileCode size={16} /> {t('skills.manual')}
                  </Button>
                  <Button
                    onClick={() => setImportModal('local')}
                    variant="outline"
                    className="gap-2 hover:bg-[var(--surface-2)]"
                  >
                    <FolderOpen size={16} /> {t('skills.importFromLocal')}
                  </Button>
                </div>

                {/* Skill Structure Info */}
                <div className="mt-12 max-w-md rounded-xl border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6 text-left shadow-sm">
                  <h4 className="mb-3 text-xs font-bold text-[var(--text-secondary)]">Skill Structure</h4>
                  <pre className="font-mono text-2xs leading-relaxed text-[var(--text-tertiary)]">
                    {`skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description)
│   └── Markdown instructions
└── Any files/folders (optional)
    └── Organize as you like!`}
                  </pre>
                  <p className="mt-2 text-2xs text-[var(--text-muted)]">
                    You can use any directory structure. Only SKILL.md is required.
                  </p>
                </div>
              </div>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Local Directory Import Modal */}
      <UnifiedDialog
        open={importModal === 'local'}
        onOpenChange={() => resetImport()}
        maxWidth="2xl"
        title={t('skills.importFromLocal')}
        description={t('skills.selectLocalDirectory')}
        icon={<FolderOpen size={18} />}
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => resetImport()}
              className="h-10 border-[var(--border)] px-4 hover:bg-[var(--surface-2)]"
            >
              {t('common.cancel')}
            </Button>
            <Button
              type="button"
              disabled={actionLoading || !localImportValidation?.valid}
              onClick={() =>
                handleImportLocal(async (skillFiles, frontmatter) => {
                  // Use mutation hook for creating skill
                  const skill = await createSkillMutation.mutateAsync({
                    name: frontmatter.name,
                    description: frontmatter.description || '',
                    license: frontmatter.license || '',
                    content:
                      parseSkillMd(skillFiles.find((f) => f.path === 'SKILL.md')?.content || '')
                        .body || '',
                    source_type: 'local',
                    tags: frontmatter.tags || [],
                    is_public: false,
                    files: skillFiles,
                  })
                  // React Query will automatically refresh the data after mutation
                  handleSelectSkill(skill)
                })
              }
              className="h-10 bg-blue-600 px-5 text-white shadow-sm hover:bg-blue-700"
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
            onChange={handleFolderSelect}
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

      {/* New File Modal */}
      <Dialog open={importModal === 'newfile'} onOpenChange={() => setImportModal(null)}>
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
          <form onSubmit={handleCreateNewFile}>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label htmlFor="directory">Directory (optional)</Label>
                <Input
                  id="directory"
                  name="directory"
                  value={newFileDirectory || ''}
                  onChange={(e) => setNewFileDirectory(e.target.value || null)}
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
                  <SelectContent className="z-[10000001]">
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

      {/* Delete File Confirmation Dialog */}
      <Dialog open={!!fileToDelete} onOpenChange={() => setFileToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
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
              onClick={() => setFileToDelete(null)}
              disabled={fileOperationLoading}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteFile}
              disabled={fileOperationLoading}
            >
              {fileOperationLoading ? (
                <Loader2 size={16} className="mr-2 animate-spin" />
              ) : (
                <Trash2 size={16} className="mr-2" />
              )}
              {t('skills.deleteFile')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rename File Dialog */}
      <Dialog
        open={!!fileToRename}
        onOpenChange={() => {
          setFileToRename(null)
          setRenameValue('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Pencil size={20} className="text-blue-500" />
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
              onChange={(e) => setRenameValue(e.target.value)}
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
              onClick={() => {
                setFileToRename(null)
                setRenameValue('')
              }}
              disabled={fileOperationLoading}
            >
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleRenameFile}
              disabled={fileOperationLoading || !renameValue.trim()}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {fileOperationLoading ? (
                <Loader2 size={16} className="mr-2 animate-spin" />
              ) : (
                <Pencil size={16} className="mr-2" />
              )}
              {t('skills.rename')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Skill API Access Dialog — only mount when open to avoid unnecessary queries */}
      {selectedSkill && showApiAccess && (
        <SkillApiAccessDialog
          open={showApiAccess}
          onOpenChange={setShowApiAccess}
          skillId={selectedSkill.id}
        />
      )}
    </div>
  )
}
