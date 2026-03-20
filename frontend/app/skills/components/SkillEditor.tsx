'use client'

import { FileText } from 'lucide-react'
import { UseFormReturn } from 'react-hook-form'

import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import { SkillFile } from '@/types'

import { SkillFormData } from '../schemas/skillFormSchema'

import { getFileIcon } from './SkillFileTree'
import { SkillForm } from './SkillForm'

interface SkillEditorProps {
  activeFilePath: string | null
  activeFile: SkillFile | null
  isSkillMd: boolean
  form: UseFormReturn<SkillFormData>
  showAdvancedFields: boolean
  onToggleAdvancedFields: () => void
  onUpdateFileContent: (filePath: string, content: string) => void
}

export function SkillEditor({
  activeFilePath,
  activeFile,
  isSkillMd,
  form,
  showAdvancedFields,
  onToggleAdvancedFields,
  onUpdateFileContent,
}: SkillEditorProps) {
  const { t } = useTranslation()
  const content = form.watch('content')

  if (isSkillMd) {
    return (
      <div className="custom-scrollbar mx-auto w-full max-w-4xl flex-1 space-y-6 overflow-y-auto p-6">
        {/* YAML Frontmatter Section */}
        <SkillForm
          form={form}
          showAdvancedFields={showAdvancedFields}
          onToggleAdvancedFields={onToggleAdvancedFields}
        />

        {/* Markdown Content Section */}
        <div className="flex flex-1 flex-col space-y-2">
          <Label className="text-[10px] font-bold uppercase text-gray-400">
            {t('skills.content') || 'Instructions'} (Markdown)
          </Label>
          <Textarea
            {...form.register('content')}
            className="min-h-[350px] flex-1 resize-none border-gray-200 bg-white p-4 font-mono text-xs"
            placeholder="# Skill Instructions

## Overview
Describe what this skill does...

## Usage
How to use this skill..."
          />
        </div>
      </div>
    )
  }

  if (activeFile) {
    return (
      <div className="flex flex-1 flex-col bg-gray-50 p-2">
        <div className="mb-2 flex items-center gap-2 px-2 py-1 text-xs text-gray-500">
          {getFileIcon(activeFile.path, activeFile.file_type)}
          <span className="font-mono">{activeFilePath}</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-400">{activeFile.file_type || 'text'}</span>
        </div>
        <Textarea
          value={activeFile?.content || ''}
          onChange={(e) => onUpdateFileContent(activeFilePath!, e.target.value)}
          className="flex-1 resize-none rounded-xl border-gray-200 p-6 font-mono text-xs shadow-sm focus-visible:ring-emerald-50"
          placeholder={t('skills.codingLogicPlaceholder') || 'Enter file content...'}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-1 items-center justify-center text-gray-400">
      <div className="text-center">
        <FileText size={32} className="mx-auto mb-2 text-gray-200" />
        <p className="text-xs">Select a file to edit</p>
      </div>
    </div>
  )
}
