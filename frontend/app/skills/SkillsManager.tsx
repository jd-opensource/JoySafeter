'use client'

import { Plus } from 'lucide-react'
import React, { useState, useEffect, useCallback, useMemo } from 'react'

import { Button } from '@/components/ui/button'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { useSkillCollaborators } from '@/hooks/queries/skillCollaborators'
import { useCreateSkill, useUpdateSkill } from '@/hooks/queries/skills'
import { useToast } from '@/hooks/use-toast'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import {
  generateSkillMd,
  parseSkillMd,
} from '@/services/skillService'
import { SkillFile } from '@/types'
import { getSkillValidationMessage } from '@/lib/utils/skillValidationI18n'

import { CollaboratorsTab } from './components/CollaboratorsTab'
import { EditorHeader } from './components/EditorHeader'
import { EmptyState } from './components/EmptyState'
import { SkillEditor } from './components/SkillEditor'
import { SkillFileTree } from './components/SkillFileTree'
import { SkillApiAccessDialog } from './components/SkillApiAccessDialog'
import { SkillListSidebar } from './components/SkillListSidebar'
import {
  ImportDialog,
  NewFileDialog,
  DeleteFileDialog,
  RenameFileDialog,
} from './components/SkillDialogs'
import { VersionHistoryTab } from './components/VersionHistoryTab'
import { useSkillFiles } from './hooks/useSkillFiles'
import { useSkillFileOperations } from './hooks/useSkillFileOperations'
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

  const createSkillMutation = useCreateSkill()
  const updateSkillMutation = useUpdateSkill()
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

  // Tab state
  const [activeTab, setActiveTab] = useState<'editor' | 'versions' | 'collaborators'>('editor')
  const [showApiAccess, setShowApiAccess] = useState(false)

  // Derive user role
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

  const formHook = useSkillForm({ initialSkill: selectedSkill })
  const { form, showAdvancedFields, setShowAdvancedFields } = formHook

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

  // File operations (delete, rename, create)
  const fileOps = useSkillFileOperations({
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
  })

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

  const isSkillMd = activeFilePath === 'SKILL.md'
  const formData = form.watch()

  return (
    <div className="flex h-full w-full overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <ResizablePanelGroup direction="horizontal">
        {/* 1. List Sidebar */}
        <ResizablePanel defaultSize={20} minSize={15} maxSize={40} className="flex shrink-0 flex-col bg-[var(--surface-1)]">
          <SkillListSidebar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            loading={loading}
            filteredSkills={filteredSkills}
            selectedSkillId={selectedSkill?.id}
            onSelectSkill={handleSelectSkill}
            onDeleteSkill={handleDelete}
          />
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
                      onClick={() => fileOps.handleAddFile(null)}
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
                    onRenameFile={fileOps.openRenameDialog}
                    onAddFile={fileOps.handleAddFile}
                  />
                </ResizablePanel>

                <ResizableHandle withHandle />

                {/* Editor Area */}
                <ResizablePanel defaultSize={80} className="flex min-w-0 flex-col bg-[var(--surface-2)] outline-none">
                  <EditorHeader
                    skillName={formData.name}
                    activeFilePath={activeFilePath}
                    activeTab={activeTab}
                    onTabChange={setActiveTab}
                    isPublic={formData.is_public || false}
                    onPublicChange={(checked) => form.setValue('is_public', checked)}
                    isSaving={isSaving}
                    onSave={handleSubmit}
                    hasSelectedSkill={!!selectedSkill}
                    onShowApiAccess={() => setShowApiAccess(true)}
                  />

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
              <EmptyState
                onNewSkillManual={handleNewSkillManual}
                onImportLocal={() => setImportModal('local')}
              />
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Dialogs */}
      <ImportDialog
        open={importModal === 'local'}
        onClose={resetImport}
        actionLoading={actionLoading}
        localImportFiles={localImportFiles}
        localImportValidation={localImportValidation}
        rejectedFiles={rejectedFiles}
        folderInputRef={folderInputRef}
        onFolderSelect={handleFolderSelect}
        onImport={() =>
          handleImportLocal(async (skillFiles, frontmatter) => {
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
            handleSelectSkill(skill)
          })
        }
      />

      <NewFileDialog
        open={importModal === 'newfile'}
        onClose={() => setImportModal(null)}
        newFileDirectory={fileOps.newFileDirectory}
        onDirectoryChange={fileOps.setNewFileDirectory}
        onCreateFile={fileOps.handleCreateNewFile}
      />

      <DeleteFileDialog
        fileToDelete={fileToDelete}
        onClose={() => setFileToDelete(null)}
        onConfirm={fileOps.handleDeleteFile}
        loading={fileOperationLoading}
      />

      <RenameFileDialog
        fileToRename={fileToRename}
        renameValue={renameValue}
        onRenameValueChange={setRenameValue}
        onClose={() => {
          setFileToRename(null)
          setRenameValue('')
        }}
        onConfirm={fileOps.handleRenameFile}
        loading={fileOperationLoading}
      />

      {/* Skill API Access Dialog -- only mount when open to avoid unnecessary queries */}
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
