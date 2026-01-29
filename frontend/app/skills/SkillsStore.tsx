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
    CheckCircle,
    FileCode,
    FileText,
    ChevronRight
} from 'lucide-react'
import React, { useState, useMemo, useEffect } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter
} from "@/components/ui/dialog"
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/core/utils/cn'
import { skillService } from '@/services/skillService'
import { Skill, SkillFile } from '@/types'
import { SkillCard } from './components/SkillCard'

import { useTranslation } from '@/lib/i18n'
import { useToast } from '@/hooks/use-toast'
import { usePublicSkills, skillKeys } from '@/hooks/queries/skills'


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
    const codeExts = ['py', 'js', 'ts', 'tsx', 'jsx', 'json', 'yaml', 'yml', 'sh', 'html', 'css', 'sql', 'md']
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
                title: t('skills.loadFailed')
            })
        }
    }, [error, toast, t])

    // Extract all unique tags from skills
    const allTags = useMemo(() => {
        const tagSet = new Set<string>()
        skills.forEach(skill => {
            skill.tags?.forEach(tag => tagSet.add(tag))
        })
        return Array.from(tagSet).sort()
    }, [skills])

    // Filter skills based on search and tags
    const filteredSkills = useMemo(() => {
        return skills.filter(skill => {
            // Search filter
            const matchesSearch = !searchQuery || 
                skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                skill.description.toLowerCase().includes(searchQuery.toLowerCase())
            
            // Tags filter
            const matchesTags = selectedTags.length === 0 || 
                selectedTags.some(tag => skill.tags?.includes(tag))
            
            return matchesSearch && matchesTags
        })
    }, [skills, searchQuery, selectedTags])

    // Toggle tag selection
    const toggleTag = (tag: string) => {
        setSelectedTags(prev => 
            prev.includes(tag) 
                ? prev.filter(t => t !== tag)
                : [...prev, tag]
        )
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
                description: t('skills.skillCopiedToYours', { name: skill.name })
            })
            onSkillCopied?.()
        } catch (error) {
            console.error('Failed to copy skill:', error)
            toast({
                variant: 'destructive',
                title: t('skills.copyFailed')
            })
        } finally {
            setCopyingSkill(null)
        }
    }

    // Loading skeleton
    const SkillCardSkeleton = () => (
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
            <div className="h-1.5 w-full bg-gray-100 rounded mb-4" />
            <div className="flex items-start gap-3 mb-3">
                <Skeleton className="w-10 h-10 rounded-xl" />
                <div className="flex-1">
                    <Skeleton className="h-4 w-24 mb-1" />
                    <Skeleton className="h-3 w-16" />
                </div>
            </div>
            <Skeleton className="h-8 w-full mb-3" />
            <div className="flex gap-1.5 mb-4">
                <Skeleton className="h-5 w-14 rounded-full" />
                <Skeleton className="h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="h-8 w-full" />
        </div>
    )

    return (
        <div className="flex flex-col h-full bg-gray-50/30">
            {/* Header with search and filters */}
            <div className="flex-shrink-0 bg-white border-b border-gray-100 px-6 py-4">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <Store className="w-5 h-5 text-emerald-500" />
                        <h2 className="text-lg font-bold text-gray-900">
                            {t('skills.marketplace')}
                        </h2>
                        <Badge variant="secondary" className="text-xs">
                            {filteredSkills.length} {t('skills.skillsAvailable')}
                        </Badge>
                    </div>
                    
                    {(searchQuery || selectedTags.length > 0) && (
                        <Button 
                            variant="ghost" 
                            size="sm" 
                            onClick={clearFilters}
                            className="text-xs text-gray-500 hover:text-gray-700"
                        >
                            <X className="w-3 h-3 mr-1" />
                            {t('skills.clearFilters')}
                        </Button>
                    )}
                </div>

                {/* Search bar */}
                <div className="flex items-center gap-4">
                    <div className="relative flex-1 max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                        <Input
                            placeholder={t('skills.searchMarketplace')}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-9 h-9 text-sm bg-gray-50/50 border-gray-200"
                        />
                    </div>

                    {/* Tag filters */}
                    {allTags.length > 0 && (
                        <div className="flex items-center gap-2 overflow-x-auto hide-scrollbar">
                            <Filter className="w-4 h-4 text-gray-400 flex-shrink-0" />
                            {allTags.slice(0, 8).map(tag => (
                                <Badge
                                    key={tag}
                                    variant={selectedTags.includes(tag) ? "default" : "outline"}
                                    className={cn(
                                        "cursor-pointer text-xs whitespace-nowrap transition-colors",
                                        selectedTags.includes(tag)
                                            ? "bg-emerald-600 hover:bg-emerald-700"
                                            : "hover:bg-gray-100"
                                    )}
                                    onClick={() => toggleTag(tag)}
                                >
                                    {tag}
                                </Badge>
                            ))}
                            {allTags.length > 8 && (
                                <Badge variant="outline" className="text-xs text-gray-400">
                                    +{allTags.length - 8}
                                </Badge>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Skills grid */}
            <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                {loading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {[...Array(8)].map((_, i) => (
                            <SkillCardSkeleton key={i} />
                        ))}
                    </div>
                ) : filteredSkills.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center py-16">
                        <div className="p-6 rounded-full bg-gray-100 mb-4">
                            <ShieldCheck className="w-12 h-12 text-gray-300" />
                        </div>
                        <h3 className="text-lg font-semibold text-gray-700 mb-2">
                            {searchQuery || selectedTags.length > 0 
                                ? t('skills.noMatchingSkills')
                                : t('skills.noPublicSkills')
                            }
                        </h3>
                        <p className="text-sm text-gray-500 max-w-md">
                            {searchQuery || selectedTags.length > 0 
                                ? t('skills.tryDifferentFilters')
                                : t('skills.beFirstToPublish')
                            }
                        </p>
                        {(searchQuery || selectedTags.length > 0) && (
                            <Button 
                                variant="outline" 
                                className="mt-4"
                                onClick={clearFilters}
                            >
                                {t('skills.clearFilters')}
                            </Button>
                        )}
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {filteredSkills.map(skill => (
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

            {/* Skill detail dialog */}
            <Dialog open={!!viewSkill} onOpenChange={() => { setViewSkill(null); setSelectedFile(null) }}>
                <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
                    {viewSkill && (
                        <>
                            <DialogHeader className="flex-shrink-0">
                                <DialogTitle className="flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center">
                                        <ShieldCheck className="w-5 h-5 text-white" />
                                    </div>
                                    <div>
                                        <span className="text-xl">{viewSkill.name}</span>
                                        {viewSkill.license && (
                                            <span className="ml-2 text-xs font-normal text-gray-400">
                                                {viewSkill.license}
                                            </span>
                                        )}
                                    </div>
                                </DialogTitle>
                                <DialogDescription className="text-left pt-2">
                                    {viewSkill.description}
                                </DialogDescription>
                            </DialogHeader>
                            
                            <div className="flex-1 overflow-hidden flex flex-col gap-4 py-4">
                                {/* Tags */}
                                {viewSkill.tags && viewSkill.tags.length > 0 && (
                                    <div className="flex-shrink-0">
                                        <h4 className="text-xs font-medium text-gray-500 mb-2">
                                            {t('skills.tags')}
                                        </h4>
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
                                    <div className="flex-1 flex flex-col overflow-hidden">
                                        <h4 className="text-xs font-medium text-gray-500 mb-2 flex-shrink-0">
                                            {t('skills.includedFiles')} ({viewSkill.files.length})
                                        </h4>
                                        <div className="flex-1 flex gap-4 min-h-0">
                                            {/* File list */}
                                            <div className="w-1/3 bg-gray-50 rounded-lg border border-gray-200 overflow-hidden flex flex-col">
                                                <div className="flex-1 overflow-y-auto">
                                                    {viewSkill.files.map((file, i) => (
                                                        <button
                                                            key={i}
                                                            onClick={() => setSelectedFile(file)}
                                                            className={cn(
                                                                "w-full text-left px-3 py-2 flex items-center gap-2 transition-colors border-b border-gray-100 last:border-b-0",
                                                                selectedFile?.path === file.path
                                                                    ? "bg-emerald-50 text-emerald-700"
                                                                    : "hover:bg-gray-100 text-gray-600"
                                                            )}
                                                        >
                                                            {isCodeFile(file.path) ? (
                                                                <FileCode size={14} className={cn(
                                                                    selectedFile?.path === file.path ? "text-emerald-500" : "text-gray-400"
                                                                )} />
                                                            ) : (
                                                                <FileText size={14} className={cn(
                                                                    selectedFile?.path === file.path ? "text-emerald-500" : "text-gray-400"
                                                                )} />
                                                            )}
                                                            <span className="text-xs font-mono truncate flex-1">
                                                                {file.path}
                                                            </span>
                                                            <ChevronRight size={12} className={cn(
                                                                "flex-shrink-0 transition-colors",
                                                                selectedFile?.path === file.path ? "text-emerald-500" : "text-gray-300"
                                                            )} />
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>

                                            {/* File content preview */}
                                            <div className="flex-1 min-w-0 overflow-hidden">
                                                {selectedFile ? (
                                                    <CodeViewer
                                                        code={selectedFile.content || ''}
                                                        language={getLanguageFromPath(selectedFile.path)}
                                                        filename={selectedFile.path}
                                                        className="h-full"
                                                        maxHeight="100%"
                                                    />
                                                ) : (
                                                    <div className="h-full flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200">
                                                        <div className="text-center text-gray-400">
                                                            <FileCode size={32} className="mx-auto mb-2 opacity-50" />
                                                            <p className="text-xs">
                                                                {t('skills.selectFileToPreview')}
                                                            </p>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <DialogFooter className="flex-shrink-0">
                                <Button variant="outline" onClick={() => { setViewSkill(null); setSelectedFile(null) }}>
                                    {t('common.cancel')}
                                </Button>
                                {viewSkill.owner_id !== currentUserId && (
                                    <Button
                                        className="bg-emerald-600 hover:bg-emerald-700 gap-2"
                                        onClick={() => {
                                            handleCopySkill(viewSkill)
                                            setViewSkill(null)
                                            setSelectedFile(null)
                                        }}
                                        disabled={copyingSkill === viewSkill.id}
                                    >
                                        {copyingSkill === viewSkill.id ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <Copy className="w-4 h-4" />
                                        )}
                                        {t('skills.copyToMine')}
                                    </Button>
                                )}
                            </DialogFooter>
                        </>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    )
}
