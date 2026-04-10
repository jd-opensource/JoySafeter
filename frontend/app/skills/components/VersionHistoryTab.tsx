'use client'

import { ChevronDown, ChevronUp, History, Plus, RotateCcw, Trash2 } from 'lucide-react'
import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import {
  useSkillVersions,
  usePublishVersion,
  useDeleteVersion,
  useRestoreDraft,
} from '@/hooks/queries/skillVersions'
import { useTranslation } from '@/lib/i18n'
import {
  versionPublishSchema,
  type VersionPublishFormData,
} from '../schemas/versionPublishSchema'

interface VersionHistoryTabProps {
  skillId: string
  /** Current user's effective role for this skill: 'owner' | 'admin' | 'publisher' | 'editor' | 'viewer' */
  userRole: string
}

export function VersionHistoryTab({ skillId, userRole }: VersionHistoryTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showPublishForm, setShowPublishForm] = useState(false)
  const [confirmDialog, setConfirmDialog] = useState<{
    type: 'restore' | 'delete'
    version: string
    open: boolean
  }>({ type: 'restore', version: '', open: false })

  const { data: versions = [], isLoading } = useSkillVersions(skillId)
  const publishMutation = usePublishVersion(skillId)
  const deleteMutation = useDeleteVersion(skillId)
  const restoreMutation = useRestoreDraft(skillId)

  const canPublish = ['owner', 'admin', 'publisher'].includes(userRole)
  const canDelete = ['owner', 'admin'].includes(userRole)
  const canRestore = ['owner', 'admin', 'publisher'].includes(userRole)

  const form = useForm<VersionPublishFormData>({
    resolver: zodResolver(versionPublishSchema),
    defaultValues: { version: '', release_notes: '' },
  })

  const handlePublish = async (data: VersionPublishFormData) => {
    try {
      await publishMutation.mutateAsync(data)
      toast({ title: t('skillVersions.publishedSuccess', { version: data.version }) })
      form.reset()
      setShowPublishForm(false)
    } catch (error: unknown) {
      toast({
        title: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      })
    }
  }

  const handleConfirmAction = async () => {
    const { type, version } = confirmDialog
    try {
      if (type === 'restore') {
        await restoreMutation.mutateAsync(version)
        toast({ title: t('skillVersions.restoredSuccess', { version }) })
      } else {
        await deleteMutation.mutateAsync(version)
        toast({ title: t('skillVersions.deletedSuccess', { version }) })
      }
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--border-strong)] border-t-[var(--text-secondary)]" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Publish form toggle */}
      {canPublish && (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowPublishForm(!showPublishForm)}
            className="gap-2"
          >
            {showPublishForm ? <ChevronUp size={14} /> : <Plus size={14} />}
            {t('skillVersions.publish')}
          </Button>

          {showPublishForm && (
            <form
              onSubmit={form.handleSubmit(handlePublish)}
              className="mt-3 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-4"
            >
              <div>
                <Label className="text-xs">{t('skillVersions.versionNumber')}</Label>
                <Input
                  {...form.register('version')}
                  placeholder={t('skillVersions.versionPlaceholder')}
                  className="mt-1"
                />
                {form.formState.errors.version && (
                  <p className="mt-1 text-xs text-[var(--text-error)]">
                    {t('skillVersions.invalidVersion')}
                  </p>
                )}
              </div>
              <div>
                <Label className="text-xs">{t('skillVersions.releaseNotes')}</Label>
                <Textarea
                  {...form.register('release_notes')}
                  placeholder={t('skillVersions.releaseNotesPlaceholder')}
                  className="mt-1"
                  rows={3}
                />
              </div>
              <Button type="submit" size="sm" disabled={publishMutation.isPending}>
                {t('skillVersions.publishButton')}
              </Button>
            </form>
          )}
        </div>
      )}

      {/* Version list */}
      {versions.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <History className="h-8 w-8 text-[var(--text-subtle)]" />
          <p className="text-sm text-[var(--text-tertiary)]">{t('skillVersions.emptyState')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {versions.map((v) => (
            <div
              key={v.version}
              className="flex items-start justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-semibold">{v.version}</span>
                  {v.publishedAt && (
                    <span className="text-xs text-[var(--text-muted)]">
                      {new Date(v.publishedAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
                {v.releaseNotes && (
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">{v.releaseNotes}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {canRestore && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs"
                    onClick={() =>
                      setConfirmDialog({ type: 'restore', version: v.version, open: true })
                    }
                  >
                    <RotateCcw size={12} />
                    {t('skillVersions.restore')}
                  </Button>
                )}
                {canDelete && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs text-[var(--status-error)] hover:text-[var(--status-error-hover)]"
                    onClick={() =>
                      setConfirmDialog({ type: 'delete', version: v.version, open: true })
                    }
                  >
                    <Trash2 size={12} />
                    {t('skillVersions.delete')}
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirm dialog */}
      <ConfirmDialog
        open={confirmDialog.open}
        onOpenChange={(open) => setConfirmDialog((prev) => ({ ...prev, open }))}
        title={
          confirmDialog.type === 'restore'
            ? t('skillVersions.restoreConfirmTitle')
            : t('skillVersions.deleteConfirmTitle')
        }
        description={
          confirmDialog.type === 'restore'
            ? t('skillVersions.restoreConfirmMessage', {
                version: confirmDialog.version,
              })
            : t('skillVersions.deleteConfirmMessage')
        }
        confirmLabel={
          confirmDialog.type === 'restore'
            ? t('skillVersions.restore')
            : t('skillVersions.delete')
        }
        cancelLabel={t('common.cancel')}
        variant={confirmDialog.type === 'delete' ? 'destructive' : 'default'}
        onConfirm={handleConfirmAction}
      />
    </div>
  )
}
