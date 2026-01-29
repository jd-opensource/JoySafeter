'use client'

import {
    Search, Plus, ShieldCheck, Trash2, Save, FileText,
    Loader2, FolderOpen, Folder, Pencil,
    FileCode, Upload, AlertCircle, CheckCircle,
    Globe, Lock, ChevronRight
} from 'lucide-react';
import React, { useState, useEffect, useRef, useCallback } from 'react';

import { Badge } from "@/components/ui/badge";
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter
} from "@/components/ui/dialog";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator
} from "@/components/ui/dropdown-menu";
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { UnifiedDialog, ValidationBox, FileListBox } from "@/components/ui/unified-dialog";
import { useToast } from '@/hooks/use-toast';
import {
    skillService,
    generateSkillMd,
    createSkillFile,
    getFilenameFromPath,
    createFilePath,
    validateFilePath,
    parseSkillMd,
} from '@/services/skillService';
import {
    Skill,
    SkillFile,
} from '@/types';
import { cn } from '@/lib/core/utils/cn';
import { useTranslation } from '@/lib/i18n';
import { getSkillValidationMessage } from '@/utils/skillValidationI18n';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

// Import extracted components and hooks
import { SkillEditor } from './components/SkillEditor';
import { SkillFileTree } from './components/SkillFileTree';
import { useSkillFiles } from './hooks/useSkillFiles';
import { useSkillForm } from './hooks/useSkillForm';
import { useSkillImport } from './hooks/useSkillImport';
import { useSkillManager } from './hooks/useSkillManager';

import { useCreateSkill, useUpdateSkill } from '@/hooks/queries/skills';

export default function SkillsManager() {
    const { t } = useTranslation();
    const { toast } = useToast();

    // Mutation hooks for skill operations
    const createSkillMutation = useCreateSkill();
    const updateSkillMutation = useUpdateSkill();

    // Use extracted hooks
    const skillManager = useSkillManager();
    const {
        skills,
        loading,
        selectedSkill,
        searchQuery,
        setSearchQuery,
        isSaving,
        setIsSaving,
        setSelectedSkill,
        loadSkills,
        handleSelectSkill,
        handleDelete,
        filteredSkills,
    } = skillManager;

    // Form management - initialize form hook first
    const formHook = useSkillForm({
        initialSkill: selectedSkill,
    });
    const {
        form,
        showAdvancedFields,
        setShowAdvancedFields,
        handleSubmit: formHandleSubmit,
    } = formHook;

    // File management (depends on form files)
    const [newFileDirectory, setNewFileDirectory] = useState<string | null>(null);
    const files = form.watch('files') || [];
    const fileManagement = useSkillFiles(files);
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
    } = fileManagement;

    // Define handleSaveInternal after form and fileManagement are available
    const handleSaveInternal = useCallback(async (formData: any) => {
        setIsSaving(true);
        try {
            // Update SKILL.md content with current form data
            const currentFiles = form.getValues('files') || [];
            const updatedFiles = updateFilesInFormData(currentFiles, formData, (updates) => {
                if (updates.files) {
                    form.setValue('files', updates.files);
                }
            });

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
            };

            // Use mutation hooks instead of direct API calls
            const saved = selectedSkill?.id
                ? await updateSkillMutation.mutateAsync({ id: selectedSkill.id, ...skillData })
                : await createSkillMutation.mutateAsync(skillData);

            // React Query will automatically refresh the data after mutation
            setSelectedSkill(saved);
            toast({ title: t('skills.skillSaved') });
        } catch (e) {
            const description = getSkillValidationMessage(e, t);
            toast({
                variant: 'destructive',
                title: t('skills.saveFailed'),
                ...(description && { description }),
            });
        } finally {
            setIsSaving(false);
        }
    }, [form, updateFilesInFormData, selectedSkill, updateSkillMutation, createSkillMutation, setSelectedSkill, toast, t, setIsSaving]);

    // Create handleSubmit that wraps form validation and save logic
    const handleSubmit = useCallback((e?: React.FormEvent | React.MouseEvent) => {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Check if form is valid before submitting
        if (!form.formState.isValid) {
            // Trigger validation to show errors
            form.trigger();
            // Show toast with validation errors
            const errors = form.formState.errors;
            const errorMessages: string[] = [];
            if (errors.name) errorMessages.push(t('skills.name') + ': ' + errors.name.message);
            if (errors.description) errorMessages.push(t('skills.description') + ': ' + errors.description.message);
            if (errors.compatibility) errorMessages.push('Compatibility: ' + errors.compatibility.message);

            toast({
                variant: 'destructive',
                title: t('skills.validationFailed') || 'Validation Failed',
                description: errorMessages.length > 0
                    ? errorMessages.join(', ')
                    : t('skills.pleaseFixErrors') || 'Please fix the errors in the form',
            });
            return;
        }

        // Use react-hook-form's handleSubmit to validate and then call save
        form.handleSubmit(handleSaveInternal)(e);
    }, [handleSaveInternal, form, toast, t]);

    // Import functionality
    const importHook = useSkillImport();
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
    } = importHook;

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
            } as any);
            // Default to SKILL.md if exists
            const defaultFile = selectedSkill.files?.find(f => f.path === 'SKILL.md') || selectedSkill.files?.[0];
            setActiveFilePath(defaultFile?.path || null);
        } else {
            formHook.form.reset();
            setActiveFilePath(null);
        }
    }, [selectedSkill, formHook.form, setActiveFilePath]);

    // Skills are now loaded via useMySkills() hook in useSkillManager
    // No need to manually call loadSkills() on mount

    const handleNewSkillManual = () => {
        const now = new Date().toISOString();
        const name = 'new-skill';
        const description = 'A new skill description';
        const body = `# ${name}\n\n## Overview\n\nAdd your skill instructions here.\n\n## Usage\n\nDescribe how to use this skill.`;

        const skillMdContent = generateSkillMd(name, description, body, { license: 'MIT' });

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
            }
        ];

        setSelectedSkill(null);
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
        });
        setActiveFilePath('SKILL.md');
    };


    const handleAddFile = (directory: string | null = null) => {
        setNewFileDirectory(directory);
        setImportModal('newfile');
    };

    const handleCreateNewFile = (e: React.FormEvent) => {
        e.preventDefault();
        const formEl = e.target as HTMLFormElement;
        const filename = (formEl.elements.namedItem('filename') as HTMLInputElement).value;
        const fileType = (formEl.elements.namedItem('filetype') as HTMLInputElement).value || 'text';

        if (!filename.trim()) {
            toast({ variant: 'destructive', title: 'Filename is required' });
            return;
        }

        const newFile = createSkillFile(newFileDirectory, filename, fileType, '');
        const currentFiles = form.getValues('files') || [];
        form.setValue('files', [...currentFiles, newFile as SkillFile]);

        setActiveFilePath(newFile.path || null);
        setImportModal(null);
    };

    // Handle file deletion
    const handleDeleteFile = async () => {
        if (!fileToDelete) {
            return;
        }

        setFileOperationLoading(true);
        try {
            // If the file has a database ID, delete from backend
            if (fileToDelete.id && selectedSkill?.id) {
                await skillService.deleteFile(fileToDelete.id);

                // Refresh skill from backend
                const updatedSkill = await skillService.getSkill(selectedSkill.id);
                if (updatedSkill) {
                    setSelectedSkill(updatedSkill);
                    form.setValue('files', updatedSkill.files || []);
                }
            } else {
                // File is only in local state (not yet saved), just remove from form
                const currentFiles = form.getValues('files') || [];
                form.setValue('files', currentFiles.filter((f: SkillFile) => f.path !== fileToDelete.path));
            }

            // If deleted file was active, clear selection
            if (activeFilePath === fileToDelete.path) {
                setActiveFilePath(null);
            }

            toast({ title: t('skills.fileDeleted') });
        } catch (e) {
            console.error('Failed to delete file:', e);
            toast({ variant: 'destructive', title: t('skills.fileDeleteFailed') });
        } finally {
            setFileOperationLoading(false);
            setFileToDelete(null);
        }
    };

    // Handle file rename
    const handleRenameFile = async () => {
        if (!fileToRename || !renameValue.trim()) {
            return;
        }

        // Get directory from old path (everything before the last /)
        const lastSlashIndex = fileToRename.path.lastIndexOf('/');
        const oldDirectory = lastSlashIndex > 0 ? fileToRename.path.substring(0, lastSlashIndex) : null;
        const newPath = createFilePath(oldDirectory, renameValue.trim());

        // Validate new path
        const validation = validateFilePath(newPath);
        if (!validation.valid) {
            toast({ variant: 'destructive', title: validation.error || t('skills.invalidPath') });
            return;
        }

        setFileOperationLoading(true);
        try {
            // If the file has a database ID, update via backend
            if (fileToRename.id && selectedSkill?.id) {
                await skillService.updateFile(fileToRename.id, {
                    path: newPath,
                    file_name: renameValue.trim(),
                });

                // Refresh skill from backend
                const updatedSkill = await skillService.getSkill(selectedSkill.id);
                if (updatedSkill) {
                    setSelectedSkill(updatedSkill);
                    form.setValue('files', updatedSkill.files || []);
                }
            } else {
                // File is only in local state, just update form
                const currentFiles = form.getValues('files') || [];
                form.setValue('files', currentFiles.map((f: SkillFile) =>
                    f.path === fileToRename.path
                        ? { ...f, path: newPath, file_name: renameValue.trim(), name: renameValue.trim() }
                        : f
                ));
            }

            // If renamed file was active, update path
            if (activeFilePath === fileToRename.path) {
                setActiveFilePath(newPath);
            }

            toast({ title: t('skills.fileRenamed') });
        } catch (e) {
            console.error('Failed to rename file:', e);
            toast({ variant: 'destructive', title: t('skills.fileRenameFailed') });
        } finally {
            setFileOperationLoading(false);
            setFileToRename(null);
            setRenameValue('');
        }
    };

    // Open rename dialog
    const openRenameDialog = (file: SkillFile) => {
        setFileToRename(file);
        setRenameValue(getFilenameFromPath(file.path));
    };

    const isSkillMd = activeFilePath === 'SKILL.md';
    const formData = form.watch();

    return (
        <div className="flex h-full w-full bg-white overflow-hidden text-gray-900">
            {/* 1. List Sidebar */}
            <div className="w-52 border-r border-gray-100 flex flex-col bg-gray-50/50 shrink-0">
                <div className="p-4 border-b border-gray-100 bg-white">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            <ShieldCheck className="text-emerald-500" size={20} />
                            {t('skills.title')}
                        </h2>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-8 w-8 text-emerald-600 hover:bg-emerald-50 rounded-full">
                                    <Plus size={18} />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-56 p-1">
                                <DropdownMenuItem onClick={handleNewSkillManual} className="gap-2 cursor-pointer py-2">
                                    <FileCode size={16} className="text-gray-400" /> {t('skills.manualEntry')}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onClick={() => setImportModal('local')} className="gap-2 cursor-pointer py-2">
                                    <FolderOpen size={16} className="text-blue-500" /> {t('skills.importFromLocal')}
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
                        <Input
                            placeholder={t('skills.searchCapabilities')}
                            className="pl-9 h-9 text-xs bg-gray-50/50 border-gray-200"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 custom-scrollbar">
                    {loading ? (
                        <div className="flex justify-center p-8"><Loader2 className="animate-spin text-gray-300" /></div>
                    ) : (
                        <div className="space-y-1">
                            {filteredSkills.map(skill => (
                                <div
                                    key={skill.id}
                                    onClick={() => handleSelectSkill(skill)}
                                    className={cn(
                                        "p-3 rounded-xl cursor-pointer transition-all border group min-w-0",
                                        selectedSkill?.id === skill.id
                                            ? "bg-white border-emerald-100 shadow-sm ring-1 ring-emerald-50"
                                            : "border-transparent hover:bg-white hover:border-gray-200"
                                    )}
                                >
                                    <div className="flex justify-between items-start mb-1 gap-2 min-w-0">
                                        <div className="flex items-center gap-2 min-w-0 flex-1">
                                            <ShieldCheck size={12} className="text-emerald-400 shrink-0" />
                                            <TooltipProvider delayDuration={300}>
                                                <Tooltip>
                                                    <TooltipTrigger className="text-sm font-semibold text-gray-800 truncate min-w-0 text-left">
                                                        {skill.name}
                                                    </TooltipTrigger>
                                                    <TooltipContent side="top">
                                                        {skill.name}
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                            {skill.is_public && (
                                                <Badge variant="outline" className="text-[8px] px-1 py-0 h-3.5 bg-emerald-50 text-emerald-600 border-emerald-200 shrink-0">
                                                    <Globe size={8} className="mr-0.5" />
                                                    {t('skills.published')}
                                                </Badge>
                                            )}
                                        </div>
                                        <button
                                            onClick={(e) => { e.stopPropagation(); handleDelete(skill.id); }}
                                            className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-opacity shrink-0"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                    <p className="text-[10px] text-gray-500 line-clamp-2 min-w-0">{skill.description}</p>
                                    {skill.files && skill.files.length > 0 && (
                                        <div className="flex items-center gap-1 mt-1.5 text-[9px] text-gray-400">
                                            <Folder size={10} />
                                            <span>{skill.files.length} files</span>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* 2. File Explorer & Editor */}
            <div className="flex-1 flex overflow-hidden">
                {(selectedSkill || formData.name) ? (
                    <>
                        {/* Hierarchical File Explorer */}
                        <div className="w-48 border-r border-gray-100 flex flex-col bg-white shrink-0">
                            <div className="p-3 border-b border-gray-100 flex items-center justify-between">
                                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{t('skills.workspace') || 'Workspace'}</span>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 hover:bg-gray-100"
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
                        </div>

                        {/* Editor Area */}
                        <div className="flex-1 flex flex-col bg-white min-w-0">
                            <div className="h-14 border-b border-gray-100 px-6 flex items-center justify-between bg-white shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="flex flex-col">
                                        <h1 className="text-sm font-bold text-gray-900 leading-tight">{formData.name}</h1>
                                        <div className="flex items-center gap-1.5 text-[9px] text-gray-400 font-mono">
                                            <ChevronRight size={10} /> {activeFilePath || 'No file selected'}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4">
                                    {/* Publish Toggle */}
                                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-200">
                                        {formData.is_public ? (
                                            <Globe size={14} className="text-emerald-500" />
                                        ) : (
                                            <Lock size={14} className="text-gray-400" />
                                        )}
                                        <span className="text-xs text-gray-600">
                                            {t('skills.publishToStore')}
                                        </span>
                                        <Switch
                                            checked={formData.is_public || false}
                                            onCheckedChange={(checked) => form.setValue('is_public', checked)}
                                            className="data-[state=checked]:bg-emerald-500"
                                        />
                                    </div>

                                    <Button
                                        onClick={handleSubmit}
                                        disabled={isSaving}
                                        className="bg-emerald-600 hover:bg-emerald-700 h-8 gap-2 shadow-sm text-xs px-4 disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                                        {t('skills.saveChanges')}
                                    </Button>
                                </div>
                            </div>

                            <div className="flex-1 overflow-hidden flex flex-col">
                                <SkillEditor
                                    activeFilePath={activeFilePath}
                                    activeFile={activeFile}
                                    isSkillMd={isSkillMd}
                                    form={form}
                                    showAdvancedFields={showAdvancedFields}
                                    onToggleAdvancedFields={() => setShowAdvancedFields(!showAdvancedFields)}
                                    onUpdateFileContent={(filePath, content) => {
                                        const currentFiles = form.getValues('files') || [];
                                        const updatedFiles = currentFiles.map((f: SkillFile) =>
                                            f.path === filePath ? { ...f, content } : f
                                        );
                                        form.setValue('files', updatedFiles);

                                        // Update form fields if SKILL.md
                                        if (filePath === 'SKILL.md') {
                                            updateFileContent(filePath, content, (updates) => {
                                                Object.entries(updates).forEach(([key, value]) => {
                                                    form.setValue(key as any, value);
                                                });
                                            });
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-gray-400 bg-gray-50/20">
                        <div className="p-8 rounded-full bg-white border border-gray-100 shadow-xl mb-6">
                            <ShieldCheck size={48} className="text-emerald-200" />
                        </div>
                        <h3 className="text-sm font-bold text-gray-900">{t('skills.chooseCreationMethod')}</h3>
                        <p className="text-xs text-gray-400 mt-1">{t('skills.populateSkillsLibrary')}</p>
                        <div className="flex flex-wrap justify-center gap-3 mt-8 max-w-lg">
                            <Button variant="outline" onClick={handleNewSkillManual} className="gap-2">
                                <FileCode size={16} /> {t('skills.manual')}
                            </Button>
                            <Button onClick={() => setImportModal('local')} className="gap-2 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-100">
                                <FolderOpen size={16} /> {t('skills.importFromLocal')}
                            </Button>
                        </div>

                        {/* Skill Structure Info */}
                        <div className="mt-12 max-w-md text-left bg-white rounded-xl p-6 border border-gray-100 shadow-sm">
                            <h4 className="text-xs font-bold text-gray-700 mb-3">Skill Structure</h4>
                            <pre className="text-[10px] text-gray-500 font-mono leading-relaxed">
{`skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description)
│   └── Markdown instructions
└── Any files/folders (optional)
    └── Organize as you like!`}
                            </pre>
                            <p className="text-[10px] text-gray-400 mt-2">
                                You can use any directory structure. Only SKILL.md is required.
                            </p>
                        </div>
                    </div>
                )}
            </div>

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
                            className="h-10 px-4 border-gray-200 hover:bg-gray-50"
                        >
                            {t('common.cancel')}
                        </Button>
                        <Button
                            type="button"
                            disabled={actionLoading || !localImportValidation?.valid}
                            onClick={() => handleImportLocal(async (skillFiles, frontmatter) => {
                                // Use mutation hook for creating skill
                                const skill = await createSkillMutation.mutateAsync({
                                    name: frontmatter.name,
                                    description: frontmatter.description || '',
                                    license: frontmatter.license || '',
                                    content: parseSkillMd(skillFiles.find(f => f.path === 'SKILL.md')?.content || '').body || '',
                                    source_type: 'local',
                                    tags: frontmatter.tags || [],
                                    is_public: false,
                                    files: skillFiles,
                                });
                                // React Query will automatically refresh the data after mutation
                                handleSelectSkill(skill);
                            })}
                            className="h-10 px-5 bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
                        >
                            {actionLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : <Upload size={16} className="mr-2" />}
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
                        className="gap-2 h-10 bg-white border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                    >
                        <FolderOpen size={16} />
                        {t('skills.selectFolder')}
                    </Button>
                    {localImportFiles.length > 0 && (
                        <span className="text-sm text-gray-500">
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
                                items={localImportValidation.errors.map(err => {
                                    if (err === 'SKILL.md_BINARY') {
                                        return t('skills.skillMdBinary');
                                    }
                                    if (err === 'SKILL.md_READ_ERROR') {
                                        return t('skills.importFailed') + ': ' + t('skills.binaryFileReadError');
                                    }
                                    return err;
                                })}
                            />
                        )}
                        {rejectedFiles.length > 0 && (
                            <ValidationBox
                                type="error"
                                icon={<AlertCircle size={16} />}
                                title={t('skills.binaryFilesRejected')}
                                items={rejectedFiles.map(f => {
                                    const reason = f.reason === 'binary'
                                        ? t('skills.binaryFileReason')
                                        : f.reason === 'read_error'
                                        ? t('skills.binaryFileReadError')
                                        : f.reason;
                                    return `${f.path} - ${reason}`;
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
                            <div className="text-xs text-gray-500 mt-2 p-2 bg-gray-50 rounded">
                                <strong>{t('common.tip') || '提示'}:</strong> {t('skills.binaryFileNotSupported')}
                            </div>
                        )}
                    </div>
                )}

                {/* File preview */}
                {localImportFiles.length > 0 && (
                    <FileListBox
                        title={t('skills.filesToImport')}
                        files={localImportFiles.map(file => ({
                            name: file.webkitRelativePath || file.name,
                            size: file.size,
                            icon: <FileText size={12} />
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
                            <Plus size={20} className="text-emerald-500" />
                            Add New File
                        </DialogTitle>
                        <DialogDescription>
                            {newFileDirectory
                                ? <>Create a new file in <code className="bg-gray-100 px-1 rounded">{newFileDirectory}/</code></>
                                : <>Create a new file at root level</>
                            }
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
                            <Button type="submit" className="w-full bg-emerald-600 hover:bg-emerald-700">
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
                            {fileOperationLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : <Trash2 size={16} className="mr-2" />}
                            {t('skills.deleteFile')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Rename File Dialog */}
            <Dialog open={!!fileToRename} onOpenChange={() => { setFileToRename(null); setRenameValue(''); }}>
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
                            <p className="text-xs text-gray-500 mt-2">
                                {t('skills.fileWillBeLocated')}: <code className="bg-gray-100 px-1 rounded">{fileToRename.path.substring(0, fileToRename.path.lastIndexOf('/'))}/{renameValue || '...'}</code>
                            </p>
                        )}
                    </div>
                    <DialogFooter className="gap-2 sm:gap-0">
                        <Button
                            variant="outline"
                            onClick={() => { setFileToRename(null); setRenameValue(''); }}
                            disabled={fileOperationLoading}
                        >
                            {t('common.cancel')}
                        </Button>
                        <Button
                            onClick={handleRenameFile}
                            disabled={fileOperationLoading || !renameValue.trim()}
                            className="bg-blue-600 hover:bg-blue-700"
                        >
                            {fileOperationLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : <Pencil size={16} className="mr-2" />}
                            {t('skills.rename')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
