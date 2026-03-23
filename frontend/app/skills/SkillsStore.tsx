'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  Search,
  Store,
  ShieldCheck,
  Loader2,
  X,
  Filter,
  Copy,
  FileCode,
  FileText,
  ChevronRight,
} from 'lucide-react'
import React, { useState, useMemo, useEffect } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicSkills, skillKeys } from '@/hooks/queries/skills'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { skillService } from '@/services/skillService'
import { Skill, SkillFile } from '@/types'

import { SkillCard } from './components/SkillCard'


interface SkillsStoreProps {
  currentUserId?: string
  onSkillCopied?: () => void
}

// Get language from file extension
const getLanguageFromPath = (path: string): string => {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const langMap: Record<string, string> = {
    py: 'python',
    js: 'javascript',
    ts: 'typescript',
    tsx: 'tsx',
    jsx: 'jsx',
    json: 'json',
    md: 'markdown',
    yaml: 'yaml',
    yml: 'yaml',
    sh: 'bash',
    html: 'html',
    css: 'css',
    sql: 'sql',
  }
  return langMap[ext] || 'text'
}

// Check if file is a code file
const isCodeFile = (path: string): boolean => {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const codeExts = [
    'py',
    'js',
    'ts',
    'tsx',
    'jsx',
    'json',
    'yaml',
    'yml',
    'sh',
    'html',
    'css',
    'sql',
    'md',
  ]
  return codeExts.includes(ext)
}

export default function SkillsStore({ currentUserId, onSkillCopied }: SkillsStoreProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [viewSkill, setViewSkill] = useState<Skill | null>(null)
  const [copyingSkill, setCopyingSkill] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<SkillFile | null>(null)

  // Use React Query hook for public skills only (for marketplace/store)
  // This hook reuses the cache from useSkills(true) and filters client-side
  const { data: skills = [], isLoading: loading, error } = usePublicSkills()

  // Show error toast if loading fails
  useEffect(() => {
    if (error) {
      console.error('Failed to load public skills:', error)
      toast({
        variant: 'destructive',
        title: t('skills.loadFailed'),
      })
    }
  }, [error, toast, t])

  // Extract all unique tags from skills
  const allTags = useMemo(() => {
    const tagSet = new Set<string>()
    skills.forEach((skill) => {
      skill.tags?.forEach((tag) => tagSet.add(tag))
    })
    return Array.from(tagSet).sort()
  }, [skills])

  // Filter skills based on search and tags
  const filteredSkills = useMemo(() => {
    return skills.filter((skill) => {
      // Search filter
      const matchesSearch =
        !searchQuery ||
        skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        skill.description.toLowerCase().includes(searchQuery.toLowerCase())

      // Tags filter
      const matchesTags =
        selectedTags.length === 0 || selectedTags.some((tag) => skill.tags?.includes(tag))

      return matchesSearch && matchesTags
    })
  }, [skills, searchQuery, selectedTags])

  // Toggle tag selection
  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]))
  }

  // Clear all filters
  const clearFilters = () => {
    setSearchQuery('')
    setSelectedTags([])
  }

  // Copy skill to user's collection
  const handleCopySkill = async (skill: Skill) => {
    setCopyingSkill(skill.id)
    try {
      await skillService.forkSkill(skill.id)
      // Invalidate queries to refresh "My Skills" data
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
      toast({
        title: t('skills.copySuccess'),
        description: t('skills.skillCopiedToYours', { name: skill.name }),
      })
      onSkillCopied?.()
    } catch (error) {
      console.error('Failed to copy skill:', error)
      toast({
        variant: 'destructive',
        title: t('skills.copyFailed'),
      })
    } finally {
      setCopyingSkill(null)
    }
  }

  // Loading skeleton
  const SkillCardSkeleton = () => (
    <div className="rounded-2xl border border-gray-200 bg-white p-5">
      <div className="mb-4 h-1.5 w-full rounded bg-gray-100" />
      <div className="mb-3 flex items-start gap-3">
        <Skeleton className="h-10 w-10 rounded-xl" />
        <div className="flex-1">
          <Skeleton className="mb-1 h-4 w-24" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
      <Skeleton className="mb-3 h-8 w-full" />
      <div className="mb-4 flex gap-1.5">
        <Skeleton className="h-5 w-14 rounded-full" />
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
      <Skeleton className="h-8 w-full" />
    </div>
  )

  return (
    <div className="flex h-full flex-col bg-gray-50/30">
      {/* Header with search and filters */}
      <div className="flex-shrink-0 border-b border-gray-100 bg-white px-6 py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4 flex-1 min-w-0">
            {/* Search bar */}
            <div className="relative max-w-sm flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder={t('skills.searchMarketplace')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 border-gray-200 bg-gray-50/50 pl-9 text-sm"
              />
            </div>

            {/* Tag filters */}
            {allTags.length > 0 && (
              <div className="hide-scrollbar flex items-center gap-2 overflow-x-auto min-w-0 hidden md:flex">
                <Filter className="h-4 w-4 flex-shrink-0 text-gray-400" />
                {allTags.slice(0, 5).map((tag) => (
                  <Badge
                    key={tag}
                    variant={selectedTags.includes(tag) ? 'default' : 'outline'}
                    className={cn(
                      'cursor-pointer whitespace-nowrap text-xs transition-colors',
                      selectedTags.includes(tag)
                        ? 'bg-emerald-600 hover:bg-emerald-700'
                        : 'hover:bg-gray-100',
                    )}
                    onClick={() => toggleTag(tag)}
                  >
                    {tag}
                  </Badge>
                ))}
                {allTags.length > 5 && (
                  <Badge variant="outline" className="text-xs text-gray-400">
                    +{allTags.length - 5}
                  </Badge>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <Badge variant="secondary" className="text-xs shrink-0">
              {filteredSkills.length} {t('skills.skillsAvailable')}
            </Badge>

            {(searchQuery || selectedTags.length > 0) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="text-xs text-gray-500 hover:text-gray-700 px-2 h-8"
              >
                <X className="mr-1 h-3 w-3" />
                {t('skills.clearFilters')}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Skills grid */}
      <div className="custom-scrollbar flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {[...Array(8)].map((_, i) => (
              <SkillCardSkeleton key={i} />
            ))}
          </div>
        ) : filteredSkills.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center py-16 text-center">
            <div className="mb-4 rounded-full bg-gray-100 p-6">
              <ShieldCheck className="h-12 w-12 text-gray-300" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-gray-700">
              {searchQuery || selectedTags.length > 0
                ? t('skills.noMatchingSkills')
                : t('skills.noPublicSkills')}
            </h3>
            <p className="max-w-md text-sm text-gray-500">
              {searchQuery || selectedTags.length > 0
                ? t('skills.tryDifferentFilters')
                : t('skills.beFirstToPublish')}
            </p>
            {(searchQuery || selectedTags.length > 0) && (
              <Button variant="outline" className="mt-4" onClick={clearFilters}>
                {t('skills.clearFilters')}
              </Button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredSkills.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                isOwner={skill.owner_id === currentUserId}
                onView={setViewSkill}
                onCopy={handleCopySkill}
              />
            ))}
          </div>
        )}
      </div>

      {/* Skill detail sheet */}
      <Sheet
        open={!!viewSkill}
        onOpenChange={(open) => {
          if (!open) {
            setViewSkill(null)
            setSelectedFile(null)
          }
        }}
      >
        <SheetContent side="right" className="flex w-full flex-col overflow-hidden p-0 sm:max-w-4xl">
          {viewSkill && (
            <div className="flex h-full flex-1 flex-col overflow-hidden bg-white p-6">
              <SheetHeader className="flex-shrink-0 text-left">
                <SheetTitle className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500">
                    <ShieldCheck className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <span className="text-xl">{viewSkill.name}</span>
                    {viewSkill.license && (
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        {viewSkill.license}
                      </span>
                    )}
                  </div>
                </SheetTitle>
                <SheetDescription className="pt-2 text-left">
                  {viewSkill.description}
                </SheetDescription>
              </SheetHeader>

              <div className="flex flex-1 flex-col gap-4 overflow-hidden py-4">
                {/* Tags */}
                {viewSkill.tags && viewSkill.tags.length > 0 && (
                  <div className="flex-shrink-0">
                    <h4 className="mb-2 text-xs font-medium text-gray-500">{t('skills.tags')}</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {viewSkill.tags.map((tag, i) => (
                        <Badge key={i} variant="secondary" className="text-xs">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Files section with preview */}
                {viewSkill.files && viewSkill.files.length > 0 && (
                  <div className="flex flex-1 flex-col overflow-hidden">
                    <h4 className="mb-2 flex-shrink-0 text-xs font-medium text-gray-500">
                      {t('skills.includedFiles')} ({viewSkill.files.length})
                    </h4>
                    <div className="flex min-h-0 flex-1 gap-4">
                      {/* File list */}
                      <div className="flex w-1/3 flex-col overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
                        <div className="flex-1 overflow-y-auto">
                          {viewSkill.files.map((file, i) => (
                            <button
                              key={i}
                              onClick={() => setSelectedFile(file)}
                              className={cn(
                                'flex w-full items-center gap-2 border-b border-gray-100 px-3 py-2 text-left transition-colors last:border-b-0',
                                selectedFile?.path === file.path
                                  ? 'bg-emerald-50 text-emerald-700'
                                  : 'text-gray-600 hover:bg-gray-100',
                              )}
                            >
                              {isCodeFile(file.path) ? (
                                <FileCode
                                  size={14}
                                  className={cn(
                                    selectedFile?.path === file.path
                                      ? 'text-emerald-500'
                                      : 'text-gray-400',
                                  )}
                                />
                              ) : (
                                <FileText
                                  size={14}
                                  className={cn(
                                    selectedFile?.path === file.path
                                      ? 'text-emerald-500'
                                      : 'text-gray-400',
                                  )}
                                />
                              )}
                              <span className="flex-1 truncate font-mono text-xs">{file.path}</span>
                              <ChevronRight
                                size={12}
                                className={cn(
                                  'flex-shrink-0 transition-colors',
                                  selectedFile?.path === file.path
                                    ? 'text-emerald-500'
                                    : 'text-gray-300',
                                )}
                              />
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* File content preview */}
                      <div className="min-w-0 flex-1 overflow-hidden">
                        {selectedFile ? (
                          <CodeViewer
                            code={selectedFile.content || ''}
                            language={getLanguageFromPath(selectedFile.path)}
                            filename={selectedFile.path}
                            className="h-full"
                            maxHeight="100%"
                          />
                        ) : (
                          <div className="flex h-full items-center justify-center rounded-lg border border-gray-200 bg-gray-50">
                            <div className="text-center text-gray-400">
                              <FileCode size={32} className="mx-auto mb-2 opacity-50" />
                              <p className="text-xs">{t('skills.selectFileToPreview')}</p>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <SheetFooter className="mt-4 flex-shrink-0">
                <Button
                  variant="outline"
                  onClick={() => {
                    setViewSkill(null)
                    setSelectedFile(null)
                  }}
                >
                  {t('common.cancel')}
                </Button>
                {viewSkill.owner_id !== currentUserId && (
                  <Button
                    className="gap-2 bg-emerald-600 hover:bg-emerald-700"
                    onClick={() => {
                      handleCopySkill(viewSkill)
                      setViewSkill(null)
                      setSelectedFile(null)
                    }}
                    disabled={copyingSkill === viewSkill.id}
                  >
                    {copyingSkill === viewSkill.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                    {t('skills.copyToMine')}
                  </Button>
                )}
              </SheetFooter>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
