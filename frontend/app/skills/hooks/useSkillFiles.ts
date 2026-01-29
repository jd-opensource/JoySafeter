import { useState, useMemo, useCallback } from 'react'

import { buildFileTree, parseSkillMd, generateSkillMd } from '@/services/skillService'
import { SkillFile, FileTreeNode } from '@/types'

import { SkillFormData } from '../schemas/skillFormSchema'

/**
 * Hook for managing skill files (tree, selection, CRUD operations)
 */
export function useSkillFiles(files: SkillFile[] = []) {
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null)
  const [fileToDelete, setFileToDelete] = useState<SkillFile | null>(null)
  const [fileToRename, setFileToRename] = useState<SkillFile | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [fileOperationLoading, setFileOperationLoading] = useState(false)

  // Build file tree structure
  const fileTree = useMemo(() => {
    return buildFileTree(files)
  }, [files])

  const activeFile = useMemo(() => {
    return files.find(f => f.path === activeFilePath) || null
  }, [files, activeFilePath])

  const updateFileContent = useCallback((
    filePath: string,
    content: string,
    onFormDataUpdate?: (updates: Partial<SkillFormData>) => void
  ) => {
    // If updating SKILL.md, parse and update form fields
    if (filePath === 'SKILL.md' && onFormDataUpdate) {
      const parsed = parseSkillMd(content)
      if (parsed.frontmatter.name) {
        // Normalize allowed_tools to string[]
        let allowedTools: string[] = []
        if (Array.isArray(parsed.frontmatter.allowed_tools)) {
          allowedTools = parsed.frontmatter.allowed_tools
        } else if (parsed.frontmatter['allowed-tools']) {
          if (typeof parsed.frontmatter['allowed-tools'] === 'string') {
            allowedTools = parsed.frontmatter['allowed-tools'].split(/\s+/).filter(t => t.trim())
          } else if (Array.isArray(parsed.frontmatter['allowed-tools'])) {
            allowedTools = parsed.frontmatter['allowed-tools']
          }
        }

        onFormDataUpdate({
          name: parsed.frontmatter.name,
          description: parsed.frontmatter.description || '',
          license: parsed.frontmatter.license || '',
          content: parsed.body,
          compatibility: parsed.frontmatter.compatibility,
          metadata: parsed.frontmatter.metadata || {},
          allowed_tools: allowedTools,
        })
      }
    }
  }, [])

  const updateFilesInFormData = useCallback((
    files: SkillFile[],
    formData: SkillFormData,
    onFormDataUpdate?: (updates: Partial<SkillFormData>) => void
  ) => {
    // Update SKILL.md content with current form data
    const updatedFiles = files.map(f => {
      if (f.path === 'SKILL.md' || f.file_name === 'SKILL.md') {
        // Build additional fields for frontmatter
        const additionalFields: Record<string, any> = {}
        if (formData.license) additionalFields.license = formData.license
        if (formData.compatibility) additionalFields.compatibility = formData.compatibility
        if (formData.metadata && Object.keys(formData.metadata).length > 0) {
          additionalFields.metadata = formData.metadata
        }
        if (formData.allowed_tools && formData.allowed_tools.length > 0) {
          // Per spec: allowed-tools is space-delimited string
          additionalFields['allowed-tools'] = formData.allowed_tools.join(' ')
        }

        const newContent = generateSkillMd(
          formData.name || '',
          formData.description || '',
          formData.content || '',
          additionalFields
        )
        return { ...f, content: newContent }
      }
      return f
    })

    if (onFormDataUpdate) {
      onFormDataUpdate({ files: updatedFiles })
    }
    return updatedFiles
  }, [])

  return {
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
  }
}
