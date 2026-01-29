import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'


import { parseSkillMd } from '@/services/skillService'
import { Skill } from '@/types'

import { skillFormSchema, type SkillFormData } from '../schemas/skillFormSchema'

interface UseSkillFormOptions {
  initialSkill?: Skill | null
  onSave?: (data: SkillFormData) => Promise<void>
  form?: any // Allow passing existing form instance
}

/**
 * Hook for managing skill form state and validation using react-hook-form
 */
export function useSkillForm({ initialSkill, onSave, form: existingForm }: UseSkillFormOptions = {}) {
  const [showAdvancedFields, setShowAdvancedFields] = useState(false)

  const internalForm = useForm<SkillFormData>({
    resolver: zodResolver(skillFormSchema),
    defaultValues: {
      name: '',
      description: '',
      content: '',
      license: '',
      compatibility: undefined,
      metadata: {},
      allowed_tools: [],
      is_public: false,
      files: [],
      source: 'local',
    },
    mode: 'onChange',
  })

  const form = existingForm ?? internalForm

  // Initialize form when skill is selected
  useEffect(() => {
    if (initialSkill) {
      // Parse SKILL.md if present to extract frontmatter
      const skillMdFile = initialSkill.files?.find(
        f => f.path === 'SKILL.md' || f.file_name === 'SKILL.md'
      )
      let content = initialSkill.content
      // Use source_type if available, otherwise fall back to legacy source field
      // source_type is the canonical field, source is legacy
      const source = initialSkill.source_type || initialSkill.source || 'local'
      
      let formData: Partial<SkillFormData> = {
        name: initialSkill.name,
        description: initialSkill.description,
        license: initialSkill.license || '',
        content: content,
        files: [...(initialSkill.files || [])],
        source: source as 'local' | 'git' | 's3',
        is_public: initialSkill.is_public || false,
        compatibility: initialSkill.compatibility || undefined,
        metadata: initialSkill.metadata || {},
        allowed_tools: initialSkill.allowed_tools || [],
      }

      if (skillMdFile?.content) {
        const parsed = parseSkillMd(skillMdFile.content)
        content = parsed.body
        const frontmatter = parsed.frontmatter

        // Normalize allowed_tools
        let allowedTools: string[] = []
        if (Array.isArray(frontmatter.allowed_tools)) {
          allowedTools = frontmatter.allowed_tools
        } else if (frontmatter['allowed-tools']) {
          if (typeof frontmatter['allowed-tools'] === 'string') {
            allowedTools = frontmatter['allowed-tools'].split(/\s+/).filter(t => t.trim())
          } else if (Array.isArray(frontmatter['allowed-tools'])) {
            allowedTools = frontmatter['allowed-tools']
          }
        }

        formData = {
          ...formData,
          name: initialSkill.name,
          description: initialSkill.description,
          license: initialSkill.license || frontmatter.license || '',
          content: content,
          compatibility: initialSkill.compatibility || frontmatter.compatibility,
          metadata: initialSkill.metadata || frontmatter.metadata || {},
          allowed_tools: initialSkill.allowed_tools || allowedTools,
        }
      }

      form.reset(formData as SkillFormData)
    } else {
      form.reset()
    }
  }, [initialSkill, form])

  const handleSubmit = form.handleSubmit(async (data: SkillFormData) => {
    if (onSave) {
      try {
        await onSave(data)
      } catch (error) {
        // Error is handled by the onSave callback
        // Re-throw to let the caller handle it
        throw error
      }
    } else {
      // Log warning in development if onSave is not provided
      if (process.env.NODE_ENV === 'development') {
        console.warn('useSkillForm: onSave callback is not provided. Form submission will not save data.')
      }
    }
  })

  // Watch for real-time validation feedback
  const name = form.watch('name')
  const description = form.watch('description')
  const compatibility = form.watch('compatibility')

  // Get validation errors
  const nameError = form.formState.errors.name?.message
  const descriptionError = form.formState.errors.description?.message
  const compatibilityError = form.formState.errors.compatibility?.message

  return {
    form,
    showAdvancedFields,
    setShowAdvancedFields,
    handleSubmit,
    name,
    description,
    compatibility,
    nameError,
    descriptionError,
    compatibilityError,
    isDirty: form.formState.isDirty,
    isValid: form.formState.isValid,
  }
}
