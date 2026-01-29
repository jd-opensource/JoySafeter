'use client'

import { FileText } from 'lucide-react'
import React from 'react'
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

export const SkillEditor: React.FC<SkillEditorProps> = ({
  activeFilePath,
  activeFile,
  isSkillMd,
  form,
  showAdvancedFields,
  onToggleAdvancedFields,
  onUpdateFileContent,
}) => {
  const { t } = useTranslation()
  const content = form.watch('content')

  if (isSkillMd) {
    return (
      <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar max-w-4xl mx-auto w-full">
        {/* YAML Frontmatter Section */}
        <SkillForm
          form={form}
          showAdvancedFields={showAdvancedFields}
          onToggleAdvancedFields={onToggleAdvancedFields}
        />

        {/* Markdown Content Section */}
        <div className="flex-1 flex flex-col space-y-2">
          <Label className="text-[10px] font-bold text-gray-400 uppercase">
            {t('skills.content') || 'Instructions'} (Markdown)
          </Label>
          <Textarea
            {...form.register('content')}
            className="flex-1 min-h-[350px] font-mono text-xs p-4 bg-white border-gray-200 resize-none"
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
      <div className="flex-1 flex flex-col bg-gray-50 p-2">
        <div className="mb-2 px-2 py-1 flex items-center gap-2 text-xs text-gray-500">
          {getFileIcon(activeFile.path, activeFile.file_type)}
          <span className="font-mono">{activeFilePath}</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-400">{activeFile.file_type || 'text'}</span>
        </div>
        <Textarea
          value={activeFile?.content || ''}
          onChange={(e) => onUpdateFileContent(activeFilePath!, e.target.value)}
          className="flex-1 border-gray-200 rounded-xl focus-visible:ring-emerald-50 font-mono text-xs p-6 resize-none shadow-sm"
          placeholder={t('skills.codingLogicPlaceholder') || 'Enter file content...'}
        />
      </div>
    )
  }

  return (
    <div className="flex-1 flex items-center justify-center text-gray-400">
      <div className="text-center">
        <FileText size={32} className="mx-auto mb-2 text-gray-200" />
        <p className="text-xs">Select a file to edit</p>
      </div>
    </div>
  )
}
