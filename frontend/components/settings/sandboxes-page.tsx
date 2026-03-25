'use client'

import { formatDistanceToNow } from 'date-fns'
import {
  RefreshCw,
  StopCircle,
  Trash2,
  PlayCircle,
  RotateCcw,
  Cpu,
  MemoryStick,
  Clock,
  Box,
  Loader2,
  User,
  Activity,
  Check,
  X,
} from 'lucide-react'
import React, { useEffect, useState } from 'react'

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
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { sandboxService, Sandbox } from '@/services/sandbox-service'

const IMAGE_PRESETS = ['python:3.12-slim', 'python:3.11-slim', 'node:20-slim'] as const
const CUSTOM_IMAGE_VALUE = '__custom__'

export const SandboxesPage = () => {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [sandboxes, setSandboxes] = useState<Sandbox[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [confirmDialog, setConfirmDialog] = useState<{
    type: 'stop' | 'restart' | 'rebuild' | 'delete'
    sandboxId: string
    open: boolean
  }>({ type: 'stop', sandboxId: '', open: false })
  const [inlineEdit, setInlineEdit] = useState<{
    sandboxId: string
    image: string
    useCustom: boolean
  } | null>(null)
  const [inlineSaving, setInlineSaving] = useState(false)
  const [needsRebuild, setNeedsRebuild] = useState<Set<string>>(new Set())

  const fetchSandboxes = async () => {
    try {
      const response = await sandboxService.listSandboxes(1, 100)
      setSandboxes(response.items)
    } catch (error) {
      toast({
        title: t('settings.sandboxes.operationFailed'),
        description: String(error),
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSandboxes()
    const interval = setInterval(fetchSandboxes, 30000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleAction = async () => {
    if (!confirmDialog.sandboxId) return

    setActionLoading(confirmDialog.sandboxId)
    try {
      switch (confirmDialog.type) {
        case 'stop':
          await sandboxService.stopSandbox(confirmDialog.sandboxId)
          break
        case 'restart':
          await sandboxService.restartSandbox(confirmDialog.sandboxId)
          break
        case 'rebuild':
          await sandboxService.rebuildSandbox(confirmDialog.sandboxId)
          break
        case 'delete':
          await sandboxService.deleteSandbox(confirmDialog.sandboxId)
          break
      }
      toast({
        title: t('settings.sandboxes.operationSuccess'),
      })
      if (confirmDialog.type === 'rebuild') {
        setNeedsRebuild((prev) => {
          const next = new Set(prev)
          next.delete(confirmDialog.sandboxId)
          return next
        })
      }
      fetchSandboxes()
    } catch (error) {
      toast({
        title: t('settings.sandboxes.operationFailed'),
        description: String(error),
        variant: 'destructive',
      })
    } finally {
      setActionLoading(null)
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    }
  }

  const openInlineEdit = (sandbox: Sandbox) => {
    const isPreset = IMAGE_PRESETS.includes(sandbox.image as (typeof IMAGE_PRESETS)[number])
    setInlineEdit({
      sandboxId: sandbox.id,
      image: sandbox.image,
      useCustom: !isPreset,
    })
  }

  const handleInlineSave = async () => {
    if (!inlineEdit) return
    const imageToSave = inlineEdit.useCustom ? inlineEdit.image.trim() : inlineEdit.image
    if (!imageToSave) {
      toast({
        title: t('settings.sandboxes.operationFailed'),
        description: t('settings.sandboxes.imageRequired'),
        variant: 'destructive',
      })
      return
    }
    setInlineSaving(true)
    try {
      await sandboxService.updateSandbox(inlineEdit.sandboxId, { image: imageToSave })
      setNeedsRebuild((prev) => new Set(prev).add(inlineEdit.sandboxId))
      setInlineEdit(null)
      toast({ title: t('settings.sandboxes.operationSuccess') })
      fetchSandboxes()
    } catch (error) {
      toast({
        title: t('settings.sandboxes.operationFailed'),
        description: String(error),
        variant: 'destructive',
      })
    } finally {
      setInlineSaving(false)
    }
  }

  const getStatusConfig = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
        return {
          color: 'bg-[var(--status-success-bg)] text-[var(--status-success)] border-[var(--status-success-border)]',
          dot: 'bg-emerald-500',
          animate: true,
        }
      case 'creating':
        return {
          color: 'bg-blue-50 text-blue-700 border-blue-200',
          dot: 'bg-blue-500',
          animate: true,
        }
      case 'stopped':
        return {
          color: 'bg-[var(--surface-1)] text-[var(--text-secondary)] border-[var(--border)]',
          dot: 'bg-[var(--text-muted)]',
          animate: false,
        }
      case 'failed':
        return {
          color: 'bg-red-50 text-red-700 border-red-200',
          dot: 'bg-red-500',
          animate: false,
        }
      default:
        return {
          color: 'bg-[var(--surface-1)] text-[var(--text-secondary)] border-[var(--border)]',
          dot: 'bg-[var(--text-muted)]',
          animate: false,
        }
    }
  }

  if (loading) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 p-2 shadow-sm">
              <Box className="h-5 w-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-[var(--text-primary)]">
                {t('settings.sandboxes.title')}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">{t('settings.sandboxes.description')}</p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setLoading(true)
              fetchSandboxes()
            }}
            className="gap-2 rounded-lg border-[var(--border)] transition-all hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)]"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            <span className="text-xs font-medium">{t('settings.sandboxes.refresh')}</span>
          </Button>
        </div>

        {/* Stats Bar */}
        <div className="mb-4 flex items-center gap-4 px-1">
          <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
            <Activity className="h-3.5 w-3.5" />
            <span>
              {sandboxes.filter((s) => s.status === 'running').length}{' '}
              {t('settings.sandboxes.running', 'running')}
            </span>
          </div>
          <div className="h-3 w-px bg-[var(--border)]" />
          <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
            <User className="h-3.5 w-3.5" />
            <span>
              {sandboxes.length} {t('settings.sandboxes.total', 'total')}
            </span>
          </div>
        </div>

        {/* Table Container */}
        <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-sm">
          <div className="flex-1 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-[var(--surface-1)]/80 hover:bg-[var(--surface-1)]/80">
                  <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.user')}
                  </TableHead>
                  <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.status')}
                  </TableHead>
                  <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.image')}
                  </TableHead>
                  <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.resources')}
                  </TableHead>
                  <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.runtime')}
                  </TableHead>
                  <TableHead className="py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    {t('settings.sandboxes.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sandboxes.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-16 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <div className="rounded-full border border-[var(--border)] bg-[var(--surface-3)] p-4">
                          <Box className="h-8 w-8 text-[var(--text-subtle)]" />
                        </div>
                        <p className="text-sm font-medium text-[var(--text-tertiary)]">
                          {t('settings.sandboxes.noSandboxes')}
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  sandboxes.map((sandbox) => {
                    const statusConfig = getStatusConfig(sandbox.status)
                    return (
                      <TableRow
                        key={sandbox.id}
                        className="group transition-colors hover:bg-[var(--surface-1)]/50"
                      >
                        <TableCell className="py-3">
                          <div className="flex items-center gap-3">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-[var(--surface-3)] to-[var(--surface-5)]">
                              <User className="h-4 w-4 text-[var(--text-tertiary)]" />
                            </div>
                            <div className="flex flex-col">
                              <span className="text-sm font-medium text-[var(--text-primary)]">
                                {sandbox.user?.name || sandbox.user?.email || 'Unknown'}
                              </span>
                              <span className="font-mono text-[10px] text-[var(--text-muted)]">
                                {sandbox.id.substring(0, 8)}...
                              </span>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="py-3">
                          <Badge
                            variant="outline"
                            className={cn(
                              'gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium',
                              statusConfig.color,
                            )}
                          >
                            <span
                              className={cn(
                                'h-1.5 w-1.5 rounded-full',
                                statusConfig.dot,
                                statusConfig.animate && 'animate-pulse',
                              )}
                            />
                            {sandbox.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="py-3">
                          {inlineEdit?.sandboxId === sandbox.id ? (
                            <div className="flex min-w-[200px] flex-col gap-2">
                              <Select
                                value={inlineEdit.useCustom ? CUSTOM_IMAGE_VALUE : inlineEdit.image}
                                onValueChange={(v) => {
                                  if (v === CUSTOM_IMAGE_VALUE) {
                                    setInlineEdit((prev) =>
                                      prev ? { ...prev, useCustom: true } : null,
                                    )
                                  } else {
                                    setInlineEdit((prev) =>
                                      prev ? { ...prev, image: v, useCustom: false } : null,
                                    )
                                  }
                                }}
                              >
                                <SelectTrigger className="h-8 text-xs">
                                  <SelectValue placeholder={t('settings.sandboxes.selectImage')} />
                                </SelectTrigger>
                                <SelectContent className="z-[10000001]">
                                  {IMAGE_PRESETS.map((img) => (
                                    <SelectItem key={img} value={img}>
                                      {img}
                                    </SelectItem>
                                  ))}
                                  <SelectItem value={CUSTOM_IMAGE_VALUE}>
                                    {t('settings.sandboxes.customImage')}
                                  </SelectItem>
                                </SelectContent>
                              </Select>
                              {inlineEdit.useCustom && (
                                <Input
                                  className="h-8 font-mono text-xs"
                                  placeholder="e.g. python:3.10-slim"
                                  value={inlineEdit.image}
                                  onChange={(e) =>
                                    setInlineEdit((prev) =>
                                      prev ? { ...prev, image: e.target.value } : null,
                                    )
                                  }
                                  maxLength={255}
                                />
                              )}
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700"
                                  onClick={handleInlineSave}
                                  disabled={inlineSaving}
                                >
                                  {inlineSaving ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Check className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
                                  onClick={() => setInlineEdit(null)}
                                  disabled={inlineSaving}
                                >
                                  <X className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                className="max-w-[140px] cursor-pointer truncate text-left font-mono text-xs text-[var(--text-secondary)] hover:text-violet-600 hover:underline"
                                title={sandbox.image}
                                onClick={() => openInlineEdit(sandbox)}
                                disabled={actionLoading === sandbox.id}
                              >
                                {sandbox.image}
                              </button>
                              {needsRebuild.has(sandbox.id) && (
                                <Badge
                                  variant="outline"
                                  className="shrink-0 rounded-md border-amber-200 bg-amber-50 text-[10px] font-medium text-amber-700"
                                >
                                  {t('settings.sandboxes.needsRebuild')}
                                </Badge>
                              )}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="py-3">
                          <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                              <Cpu className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                              <span className="font-medium">{sandbox.cpu_limit}</span>
                            </div>
                            <div className="h-3 w-px bg-[var(--border)]" />
                            <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                              <MemoryStick className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                              <span className="font-medium">{sandbox.memory_limit}M</span>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="py-3">
                          {sandbox.status === 'running' && sandbox.created_at ? (
                            <div className="flex items-center gap-1.5 text-xs text-emerald-600">
                              <Clock className="h-3.5 w-3.5" />
                              <span className="font-medium">
                                {formatDistanceToNow(new Date(sandbox.created_at))}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-[var(--text-muted)]">—</span>
                          )}
                        </TableCell>
                        <TableCell className="py-3">
                          <div className="flex justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                            {sandbox.status === 'running' ? (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 rounded-md text-amber-600 hover:bg-amber-50 hover:text-amber-700"
                                    onClick={() =>
                                      setConfirmDialog({
                                        type: 'stop',
                                        sandboxId: sandbox.id,
                                        open: true,
                                      })
                                    }
                                    disabled={actionLoading === sandbox.id}
                                  >
                                    <StopCircle className="h-3.5 w-3.5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="text-xs">
                                  {t('settings.sandboxes.stop')}
                                </TooltipContent>
                              </Tooltip>
                            ) : (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 rounded-md text-emerald-600 hover:bg-emerald-50 hover:text-emerald-700"
                                    onClick={() =>
                                      setConfirmDialog({
                                        type: 'restart',
                                        sandboxId: sandbox.id,
                                        open: true,
                                      })
                                    }
                                    disabled={actionLoading === sandbox.id}
                                  >
                                    <PlayCircle className="h-3.5 w-3.5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="text-xs">
                                  {t('settings.sandboxes.restart')}
                                </TooltipContent>
                              </Tooltip>
                            )}
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 rounded-md text-blue-600 hover:bg-blue-50 hover:text-blue-700"
                                  onClick={() =>
                                    setConfirmDialog({
                                      type: 'rebuild',
                                      sandboxId: sandbox.id,
                                      open: true,
                                    })
                                  }
                                  disabled={actionLoading === sandbox.id}
                                >
                                  <RotateCcw className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="text-xs">
                                {t('settings.sandboxes.rebuild')}
                              </TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 rounded-md text-red-600 hover:bg-red-50 hover:text-red-700"
                                  onClick={() =>
                                    setConfirmDialog({
                                      type: 'delete',
                                      sandboxId: sandbox.id,
                                      open: true,
                                    })
                                  }
                                  disabled={actionLoading === sandbox.id}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="text-xs">
                                {t('settings.sandboxes.delete')}
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </div>

        {/* Confirm Dialog */}
        <AlertDialog
          open={confirmDialog.open}
          onOpenChange={(open) => setConfirmDialog((prev) => ({ ...prev, open }))}
        >
          <AlertDialogContent className="rounded-xl border-0 shadow-xl">
            <AlertDialogHeader>
              <AlertDialogTitle className="text-lg font-semibold">
                {confirmDialog.type === 'stop' && t('settings.sandboxes.stop')}
                {confirmDialog.type === 'restart' && t('settings.sandboxes.restart')}
                {confirmDialog.type === 'rebuild' && t('settings.sandboxes.rebuild')}
                {confirmDialog.type === 'delete' && t('settings.sandboxes.delete')}
              </AlertDialogTitle>
              <AlertDialogDescription className="text-sm text-[var(--text-tertiary)]">
                {confirmDialog.type === 'stop' && t('settings.sandboxes.stopConfirm')}
                {confirmDialog.type === 'restart' && t('settings.sandboxes.restartConfirm')}
                {confirmDialog.type === 'rebuild' && t('settings.sandboxes.rebuildConfirm')}
                {confirmDialog.type === 'delete' && t('settings.sandboxes.deleteConfirm')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="rounded-lg">
                {t('common.cancel', 'Cancel')}
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={handleAction}
                className={cn(
                  'rounded-lg text-white',
                  confirmDialog.type === 'delete'
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-violet-600 hover:bg-violet-700',
                )}
              >
                {actionLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('common.confirm', 'Confirm')}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </TooltipProvider>
  )
}
