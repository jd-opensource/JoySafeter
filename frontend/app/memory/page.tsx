'use client'

import {
  Brain,
  Plus,
  Trash2,
  Edit3,
  Tag,
  Calendar,
  Loader2,
  AlertCircle,
  MoreHorizontal,
  Zap,
} from 'lucide-react'
import React, { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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
import { Pagination } from '@/components/ui/pagination'
import { SearchInput } from '@/components/ui/search-input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  useMemories,
  useMemoryTopics,
  useCreateMemory,
  useUpdateMemory,
  useDeleteMemory,
  useOptimizeMemories,
  UserMemory,
} from '@/hooks/queries/useMemories'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

export default function KnowledgePage() {
  const { t } = useTranslation()
  const { toast } = useToast()

  // State
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTopic, setSelectedTopic] = useState<string>('')
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc')
  const [page, setPage] = useState(1)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [editingMemory, setEditingMemory] = useState<UserMemory | null>(null)
  const [deleteConfirmMemory, setDeleteConfirmMemory] = useState<UserMemory | null>(null)

  // Form state
  const [formMemory, setFormMemory] = useState('')
  const [formTopics, setFormTopics] = useState('')

  const pageSize = 20

  // Queries
  const { data: memoriesData, isLoading, error } = useMemories({
    page,
    limit: pageSize,
    search_content: searchQuery || undefined,
    topics: selectedTopic ? [selectedTopic] : undefined,
    sort_order: sortOrder,
  })

  const { data: topics = [] } = useMemoryTopics()

  // Mutations
  const createMutation = useCreateMemory()
  const updateMutation = useUpdateMemory()
  const deleteMutation = useDeleteMemory()
  const optimizeMutation = useOptimizeMemories()

  const memories = memoriesData?.data || []
  const pagination = memoriesData?.meta

  // Handlers
  const handleCreate = async () => {
    if (!formMemory.trim()) {
      toast({ variant: 'destructive', title: t('memory.memoryRequired', { defaultValue: 'Memory content is required' }) })
      return
    }

    try {
      await createMutation.mutateAsync({
        memory: formMemory.trim(),
        topics: formTopics.split(',').map(t => t.trim()).filter(Boolean),
      })
      toast({ title: t('memory.memoryCreated', { defaultValue: 'Memory created successfully' }) })
      setIsCreateOpen(false)
      resetForm()
    } catch {
      toast({ variant: 'destructive', title: t('memory.createFailed', { defaultValue: 'Failed to create memory' }) })
    }
  }

  const handleUpdate = async () => {
    if (!editingMemory || !formMemory.trim()) return

    try {
      await updateMutation.mutateAsync({
        memoryId: editingMemory.memory_id,
        data: {
          memory: formMemory.trim(),
          topics: formTopics.split(',').map(t => t.trim()).filter(Boolean),
        },
      })
      toast({ title: t('memory.memoryUpdated', { defaultValue: 'Memory updated successfully' }) })
      setEditingMemory(null)
      resetForm()
    } catch {
      toast({ variant: 'destructive', title: t('memory.updateFailed', { defaultValue: 'Failed to update memory' }) })
    }
  }

  const handleDelete = async () => {
    if (!deleteConfirmMemory) return
    try {
      await deleteMutation.mutateAsync(deleteConfirmMemory.memory_id)
      toast({ title: t('memory.memoryDeleted', { defaultValue: 'Memory deleted successfully' }) })
      setDeleteConfirmMemory(null)
    } catch {
      toast({ variant: 'destructive', title: t('memory.deleteFailed', { defaultValue: 'Failed to delete memory' }) })
    }
  }

  const handleOptimize = async () => {
    try {
      const result = await optimizeMutation.mutateAsync(true)
      toast({
        title: t('memory.optimized', { defaultValue: 'Memories optimized' }),
        description: `${result.memories_before} → ${result.memories_after} (${result.reduction_percentage.toFixed(1)}% reduction)`,
      })
    } catch {
      toast({ variant: 'destructive', title: t('memory.optimizeFailed', { defaultValue: 'Failed to optimize memories' }) })
    }
  }

  const openEdit = (memory: UserMemory) => {
    setEditingMemory(memory)
    setFormMemory(memory.memory)
    setFormTopics(memory.topics?.join(', ') || '')
  }

  const resetForm = () => {
    setFormMemory('')
    setFormTopics('')
  }

  const openCreate = () => {
    resetForm()
    setIsCreateOpen(true)
  }

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-gray-100 bg-white p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center border bg-emerald-50 border-emerald-100 text-emerald-600">
              <Brain size={18} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                {t('memory.title', { defaultValue: 'Knowledge & Memory' })}
              </h2>
              <p className="text-xs text-gray-500 mt-1">
                {t('memory.subtitle', { defaultValue: 'Long-term memories stored across conversations' })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleOptimize}
              disabled={optimizeMutation.isPending || memories.length === 0}
              className="gap-1.5 text-xs h-9"
            >
              {optimizeMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Zap className="h-3.5 w-3.5" />
              )}
              {t('memory.optimize', { defaultValue: 'Optimize' })}
            </Button>
            <Button
              size="sm"
              onClick={openCreate}
              className="gap-1.5 text-xs h-9 bg-emerald-600 hover:bg-emerald-700 shadow-emerald-100 shadow-lg"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('memory.addMemory', { defaultValue: 'Add Memory' })}
            </Button>
          </div>
        </div>

        {/* Filters - using SearchInput component */}
        <div className="flex items-center gap-3 mt-4">
          <SearchInput
            value={searchQuery}
            onValueChange={(v) => {
              setSearchQuery(v)
              setPage(1)
            }}
            placeholder={t('memory.searchPlaceholder', { defaultValue: 'Search memories...' })}
            className="flex-1 max-w-md h-9"
          />
          <Select
            value={selectedTopic || 'all'}
            onValueChange={(v) => {
              setSelectedTopic(v === 'all' ? '' : v)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-40 h-9 text-sm">
              <SelectValue placeholder={t('memory.allTopics', { defaultValue: 'All Topics' })} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('memory.allTopics', { defaultValue: 'All Topics' })}</SelectItem>
              {topics.map((topic) => (
                <SelectItem key={topic} value={topic}>
                  {topic}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')}
            className="h-9 text-xs"
          >
            {sortOrder === 'desc' ? t('memory.newest', { defaultValue: 'Newest' }) : t('memory.oldest', { defaultValue: 'Oldest' })}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 bg-gray-50/50 space-y-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 text-gray-500">
            <AlertCircle className="h-10 w-10 mb-3 text-red-400" />
            <p>{t('memory.loadError', { defaultValue: 'Failed to load memories' })}</p>
          </div>
        ) : memories.length === 0 ? (
          // Empty state - distinguish between filtered empty and truly empty
          (() => {
            const hasFilters = searchQuery.trim() || selectedTopic
            return (
              <div 
                className={`p-4 rounded-xl border border-dashed border-gray-300 flex flex-col items-center justify-center text-center gap-2 bg-gray-50 ${hasFilters ? '' : 'hover:bg-white hover:border-gray-400 transition-colors cursor-pointer'} py-12`}
                onClick={hasFilters ? undefined : openCreate}
              >
                <div className="w-10 h-10 rounded-full bg-white border border-gray-200 flex items-center justify-center shadow-sm text-gray-400">
                  {hasFilters ? (
                    <AlertCircle size={20} />
                  ) : (
                    <Plus size={20} />
                  )}
                </div>
                <div>
                  <h4 className="text-sm font-medium text-gray-900">
                    {hasFilters 
                      ? t('memory.noMemoriesFiltered', { defaultValue: 'No memories found' })
                      : t('memory.noMemories', { defaultValue: 'No memories yet' })
                    }
                  </h4>
                  <p className="text-xs text-gray-500 mt-1 max-w-md">
                    {hasFilters
                      ? t('memory.noMemoriesFilteredDescription', { 
                          defaultValue: 'Try adjusting your search or filter criteria' 
                        })
                      : t('memory.noMemoriesDescription', { defaultValue: 'Click to add your first memory' })
                    }
                  </p>
                </div>
              </div>
            )
          })()
        ) : (
          // Memory list - using Card component, style consistent with McpServerCard
          <div className="space-y-3">
            {memories.map((memory) => (
              <Card
                key={memory.memory_id}
                className="group flex items-start justify-between p-4 bg-white border-gray-200 hover:shadow-md transition-all hover:border-emerald-200"
              >
                <div className="flex items-start gap-4 flex-1 min-w-0">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center border bg-emerald-50 border-emerald-100 text-emerald-600 flex-shrink-0">
                    <Brain size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap line-clamp-3">
                      {memory.memory}
                    </p>
                    <div className="flex items-center gap-3 mt-2 flex-wrap">
                      {memory.topics && memory.topics.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Tag className="h-3 w-3 text-gray-400" />
                          {memory.topics.map((topic) => (
                            <Badge
                              key={topic}
                              variant="outline"
                              className="text-[9px] px-1.5 py-0 bg-emerald-50 text-emerald-600 border-emerald-100"
                            >
                              {topic}
                            </Badge>
                          ))}
                        </div>
                      )}
                      {memory.updated_at && (
                        <div className="flex items-center gap-1 text-[10px] text-gray-400">
                          <Calendar className="h-3 w-3" />
                          {formatDate(memory.updated_at)}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Actions - consistent with McpServerCard */}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-gray-400 hover:text-gray-900 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <MoreHorizontal size={16} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => openEdit(memory)}>
                      <Edit3 size={14} className="mr-2" />
                      {t('memory.edit', { defaultValue: 'Edit' })}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => setDeleteConfirmMemory(memory)}
                      className="text-red-600 focus:text-red-600"
                    >
                      <Trash2 size={14} className="mr-2" />
                      {t('memory.delete', { defaultValue: 'Delete' })}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </Card>
            ))}
          </div>
        )}

        {/* Pagination - using Pagination component */}
        {pagination && pagination.total_pages > 1 && (
          <Pagination
            page={page}
            totalPages={pagination.total_pages}
            total={pagination.total_count}
            pageSize={pageSize}
            onPageChange={setPage}
            isLoading={isLoading}
            className="pt-4"
          />
        )}
      </div>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5 text-emerald-600" />
              {t('memory.createMemory', { defaultValue: 'Create Memory' })}
            </DialogTitle>
            <DialogDescription>
              {t('memory.createMemoryDescription', { defaultValue: 'Add a new memory that will be available to your agents.' })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-xs font-medium">{t('memory.memoryContent', { defaultValue: 'Memory Content' })}</Label>
              <Textarea
                value={formMemory}
                onChange={(e) => setFormMemory(e.target.value)}
                placeholder={t('memory.memoryPlaceholder', { defaultValue: 'e.g., User prefers concise technical explanations' })}
                rows={4}
                className="resize-none text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-medium">{t('memory.topics', { defaultValue: 'Topics' })}</Label>
              <Input
                value={formTopics}
                onChange={(e) => setFormTopics(e.target.value)}
                placeholder={t('memory.topicsPlaceholder', { defaultValue: 'preferences, technical (comma separated)' })}
                className="text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={createMutation.isPending}
              className="gap-1.5 bg-emerald-600 hover:bg-emerald-700"
            >
              {createMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('memory.create', { defaultValue: 'Create' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editingMemory} onOpenChange={(open) => !open && setEditingMemory(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit3 className="h-5 w-5 text-emerald-600" />
              {t('memory.editMemory', { defaultValue: 'Edit Memory' })}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-xs font-medium">{t('memory.memoryContent', { defaultValue: 'Memory Content' })}</Label>
              <Textarea
                value={formMemory}
                onChange={(e) => setFormMemory(e.target.value)}
                rows={4}
                className="resize-none text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-medium">{t('memory.topics', { defaultValue: 'Topics' })}</Label>
              <Input
                value={formTopics}
                onChange={(e) => setFormTopics(e.target.value)}
                placeholder={t('memory.topicsPlaceholder', { defaultValue: 'preferences, technical (comma separated)' })}
                className="text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingMemory(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              onClick={handleUpdate}
              disabled={updateMutation.isPending}
              className="gap-1.5 bg-emerald-600 hover:bg-emerald-700"
            >
              {updateMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('memory.save', { defaultValue: 'Save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation - using AlertDialog for better semantics */}
      <AlertDialog open={!!deleteConfirmMemory} onOpenChange={(open) => !open && setDeleteConfirmMemory(null)}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('memory.confirmDelete', { defaultValue: 'Delete Memory?' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('memory.confirmDeleteDescription', { defaultValue: 'This action cannot be undone. The memory will be permanently removed.' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {t('memory.delete', { defaultValue: 'Delete' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
