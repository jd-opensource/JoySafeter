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
  const totalMemories = pagination?.total_count ?? memories.length
  const hasFilters = Boolean(searchQuery.trim() || selectedTopic)

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
    <div className="executive-page executive-shell">
      <div className="executive-page-content space-y-6">
        <header className="executive-header">
          <div className="space-y-4">
            <div className="executive-kicker">
              <Brain className="h-3.5 w-3.5" />
              Knowledge Ledger
            </div>
            <div className="space-y-3">
              <h1 className="text-4xl font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                {t('memory.title', { defaultValue: 'Knowledge & Memory' })}
              </h1>
              <p className="max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
                {t('memory.subtitle', { defaultValue: 'Long-term memories stored across conversations' })}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="quiet-badge">{totalMemories} stored memories</div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleOptimize}
              disabled={optimizeMutation.isPending || memories.length === 0}
              className="h-10 gap-1.5 rounded-full border-[var(--border)] bg-white/80 px-4 text-xs hover:border-[var(--border-hover)] hover:bg-white"
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
              className="btn-primary h-10 gap-1.5 rounded-full px-5 text-xs"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('memory.addMemory', { defaultValue: 'Add Memory' })}
            </Button>
          </div>
        </header>

        <section className="grid gap-4 lg:grid-cols-[1.4fr_0.9fr]">
          <div className="surface-panel px-6 py-6 sm:px-7">
            <div className="space-y-5">
              <div className="space-y-3">
                <div className="section-label">Retrieval Controls</div>
                <div className="executive-rule" />
              </div>
              <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_176px_132px]">
                <SearchInput
                  value={searchQuery}
                  onValueChange={(v) => {
                    setSearchQuery(v)
                    setPage(1)
                  }}
                  placeholder={t('memory.searchPlaceholder', { defaultValue: 'Search memories...' })}
                  className="h-11"
                />
                <Select
                  value={selectedTopic || 'all'}
                  onValueChange={(v) => {
                    setSelectedTopic(v === 'all' ? '' : v)
                    setPage(1)
                  }}
                >
                  <SelectTrigger className="h-11 bg-white">
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
                  className="h-11 rounded-full border-[var(--border)] bg-white/80 text-xs hover:border-[var(--border-hover)] hover:bg-white"
                >
                  {sortOrder === 'desc' ? t('memory.newest', { defaultValue: 'Newest' }) : t('memory.oldest', { defaultValue: 'Oldest' })}
                </Button>
              </div>
            </div>
          </div>

          <aside className="surface-panel px-6 py-6">
            <div className="space-y-4">
              <div className="section-label">Archive Summary</div>
              <div className="executive-rule" />
              <div className="grid grid-cols-2 gap-3">
                <div className="surface-panel-flat px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                    Topics
                  </div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                    {topics.length}
                  </div>
                </div>
                <div className="surface-panel-flat px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                    Page
                  </div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                    {page}
                  </div>
                </div>
              </div>
              <p className="text-sm leading-6 text-[var(--text-secondary)]">
                Memory is presented as institutional knowledge rather than chat residue,
                so teams can audit what the system retains and why it matters.
              </p>
            </div>
          </aside>
        </section>

        <section className="surface-panel min-h-[420px] px-6 py-6 sm:px-7">
          <div className="space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-2">
                <div className="section-label">Memory Archive</div>
                <p className="text-sm text-[var(--text-secondary)]">
                  Showing {memories.length} of {totalMemories} stored entries.
                </p>
              </div>
              {selectedTopic && <div className="quiet-badge">{selectedTopic}</div>}
            </div>

            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
              </div>
            ) : error ? (
              <div className="surface-panel-flat flex flex-col items-center justify-center gap-3 py-16 text-center">
                <AlertCircle className="h-10 w-10 text-[var(--status-offline)]" />
                <p className="text-sm text-[var(--text-secondary)]">
                  {t('memory.loadError', { defaultValue: 'Failed to load memories' })}
                </p>
              </div>
            ) : memories.length === 0 ? (
              <div
                className={cn(
                  'surface-panel-flat flex min-h-[280px] flex-col items-center justify-center gap-3 px-6 py-12 text-center',
                  !hasFilters && 'cursor-pointer transition duration-200 hover:border-[var(--border-hover)] hover:bg-white'
                )}
                onClick={hasFilters ? undefined : openCreate}
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
                  {hasFilters ? <AlertCircle size={20} /> : <Plus size={20} />}
                </div>
                <div>
                  <h4 className="text-base font-semibold text-[var(--text-primary)]">
                    {hasFilters
                      ? t('memory.noMemoriesFiltered', { defaultValue: 'No memories found' })
                      : t('memory.noMemories', { defaultValue: 'No memories yet' })}
                  </h4>
                  <p className="mt-2 max-w-md text-sm leading-6 text-[var(--text-secondary)]">
                    {hasFilters
                      ? t('memory.noMemoriesFilteredDescription', {
                          defaultValue: 'Try adjusting your search or filter criteria'
                        })
                      : t('memory.noMemoriesDescription', { defaultValue: 'Click to add your first memory' })}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {memories.map((memory) => (
                  <Card
                    key={memory.memory_id}
                    className="surface-panel-flat group flex items-start justify-between gap-4 p-5 transition duration-200 hover:border-[var(--border-hover)] hover:bg-white"
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-4">
                      <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-2xl border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
                        <Brain size={18} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-7 text-[var(--text-primary)]">
                          {memory.memory}
                        </p>
                        <div className="mt-3 flex flex-wrap items-center gap-3">
                          {memory.topics && memory.topics.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Tag className="h-3 w-3 text-[var(--text-muted)]" />
                              {memory.topics.map((topic) => (
                                <Badge
                                  key={topic}
                                  variant="outline"
                                  className="border-[rgba(54,93,130,0.16)] bg-[rgba(54,93,130,0.08)] px-2 py-0 text-[9px] uppercase tracking-[0.16em] text-[var(--status-running)]"
                                >
                                  {topic}
                                </Badge>
                              ))}
                            </div>
                          )}
                          {memory.updated_at && (
                            <div className="flex items-center gap-1 text-[10px] uppercase tracking-[0.14em] text-[var(--text-muted)]">
                              <Calendar className="h-3 w-3" />
                              {formatDate(memory.updated_at)}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 rounded-full text-[var(--text-muted)] opacity-0 transition duration-200 hover:bg-white hover:text-[var(--text-primary)] group-hover:opacity-100"
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
        </section>
      </div>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[0_28px_70px_rgba(15,23,42,0.16)] sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5 text-[var(--brand-500)]" />
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
              className="btn-primary gap-1.5 rounded-full px-5"
            >
              {createMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('memory.create', { defaultValue: 'Create' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editingMemory} onOpenChange={(open) => !open && setEditingMemory(null)}>
        <DialogContent className="border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[0_28px_70px_rgba(15,23,42,0.16)] sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit3 className="h-5 w-5 text-[var(--brand-500)]" />
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
              className="btn-primary gap-1.5 rounded-full px-5"
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
