import { useState, useCallback, useMemo } from 'react'

import { useMySkills, useDeleteSkill } from '@/hooks/queries/skills'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { Skill } from '@/types'

/**
 * Hook for managing skill list, selection, and CRUD operations
 * Uses React Query for data fetching and caching
 */
export function useSkillManager() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Use React Query hook to get user's skills
  const { data: skills = [], isLoading: loading, refetch } = useMySkills()
  
  // Delete mutation hook
  const deleteSkillMutation = useDeleteSkill()

  const handleSelectSkill = useCallback((skill: Skill) => {
    setSelectedSkill(skill)
  }, [])

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteSkillMutation.mutateAsync(id)
      // React Query will automatically refresh the data after mutation
      if (selectedSkill?.id === id) {
        setSelectedSkill(null)
      }
      toast({ title: t('skills.deleted') })
    } catch (e) {
      toast({ variant: 'destructive', title: t('skills.deleteFailed') })
    }
  }, [selectedSkill, deleteSkillMutation, toast, t])

  // Filter skills based on search query
  const filteredSkills = useMemo(() => {
    return skills.filter(s => 
      s.name.toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [skills, searchQuery])

  return {
    skills,
    loading,
    selectedSkill,
    searchQuery,
    setSearchQuery,
    isSaving,
    setIsSaving,
    setSelectedSkill,
    loadSkills: refetch, // Expose refetch for backward compatibility
    handleSelectSkill,
    handleDelete,
    filteredSkills,
    form: null, // Placeholder for form integration
  }
}
