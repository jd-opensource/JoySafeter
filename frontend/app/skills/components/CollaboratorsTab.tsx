'use client'

import { Crown, Edit, Eye, Plus, Shield, UserPlus, Users, X } from 'lucide-react'
import React, { useState } from 'react'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import {
  useSkillCollaborators,
  useAddCollaborator,
  useUpdateCollaboratorRole,
  useRemoveCollaborator,
  useTransferOwnership,
} from '@/hooks/queries/skillCollaborators'
import type { CollaboratorRole } from '@/hooks/queries/skillCollaborators'
import { useTranslation } from '@/lib/i18n'

interface CollaboratorsTabProps {
  skillId: string
  ownerId: string
  userRole: string // current user's role: 'owner' | 'admin' | etc.
}

const ROLES: CollaboratorRole[] = ['viewer', 'editor', 'publisher', 'admin']

const ROLE_ICONS = {
  owner: Crown,
  admin: Shield,
  editor: Edit,
  publisher: Users,
  viewer: Eye,
}

export function CollaboratorsTab({ skillId, ownerId, userRole }: CollaboratorsTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showAddForm, setShowAddForm] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newRole, setNewRole] = useState<CollaboratorRole>('viewer')
  const [removeTarget, setRemoveTarget] = useState<{ userId: string; open: boolean }>({
    userId: '',
    open: false,
  })
  const [transferDialog, setTransferDialog] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState('')

  const { data, isLoading } = useSkillCollaborators(skillId)
  const collaborators = data?.collaborators ?? []
  const ownerInfo = data?.owner
  const addMutation = useAddCollaborator(skillId)
  const updateRoleMutation = useUpdateCollaboratorRole(skillId)
  const removeMutation = useRemoveCollaborator(skillId)
  const transferMutation = useTransferOwnership(skillId)

  const canManage = ['owner', 'admin'].includes(userRole)
  const isOwner = userRole === 'owner'

  const handleAdd = async () => {
    if (!newEmail.trim()) return
    try {
      await addMutation.mutateAsync({ email: newEmail.trim(), role: newRole })
      toast({ title: t('skillCollaborators.addedSuccess') })
      setNewEmail('')
      setNewRole('viewer')
      setShowAddForm(false)
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
  }

  const handleRoleChange = async (userId: string, role: CollaboratorRole) => {
    try {
      await updateRoleMutation.mutateAsync({ userId, role })
      toast({ title: t('skillCollaborators.updatedSuccess') })
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
  }

  const handleRemove = async () => {
    try {
      await removeMutation.mutateAsync(removeTarget.userId)
      toast({ title: t('skillCollaborators.removedSuccess') })
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
    setRemoveTarget({ userId: '', open: false })
  }

  const handleTransfer = async () => {
    if (!transferTargetId.trim()) return
    try {
      await transferMutation.mutateAsync(transferTargetId.trim())
      toast({ title: t('skillCollaborators.transferredSuccess') })
      setTransferDialog(false)
      setTransferTargetId('')
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--border-strong)] border-t-[var(--text-secondary)]" />
      </div>
    )
  }

  const ownerDisplayName = ownerInfo?.name || ownerInfo?.email || ownerId
  const ownerDisplayEmail = ownerInfo?.email

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Add collaborator button */}
      {canManage && (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAddForm(!showAddForm)}
            className="gap-2"
          >
            <UserPlus size={14} />
            {t('skillCollaborators.add')}
          </Button>

          {showAddForm && (
            <div className="mt-3 flex items-end gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-4">
              <div className="flex-1">
                <Label className="text-xs">{t('skillCollaborators.emailAddress')}</Label>
                <Input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder={t('skillCollaborators.emailPlaceholder')}
                  className="mt-1"
                />
              </div>
              <div className="w-32">
                <Label className="text-xs">{t('skillCollaborators.role')}</Label>
                <Select
                  value={newRole}
                  onValueChange={(v) => setNewRole(v as CollaboratorRole)}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {t(`skillCollaborators.${r}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button size="sm" onClick={handleAdd} disabled={addMutation.isPending} aria-label="Add collaborator">
                <Plus size={14} />
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Collaborator list */}
      <div className="space-y-1">
        {/* Owner row (always first) */}
        <div className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-600)] text-xs font-semibold text-white shadow-sm">
            {(ownerDisplayName || '?').slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-[var(--text-primary)]">
              {ownerDisplayName}
            </p>
            {ownerDisplayEmail && ownerInfo?.name && (
              <p className="truncate text-xs text-[var(--text-tertiary)]">
                {ownerDisplayEmail}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-yellow-100">
              <Crown size={12} className="text-yellow-700" />
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {t('skillCollaborators.owner')}
            </span>
          </div>
        </div>

        {/* Collaborator rows */}
        {collaborators.map((c) => {
          const displayName = c.userName || c.userEmail || c.userId
          const displayEmail = c.userEmail
          const RoleIcon = ROLE_ICONS[c.role] || Eye

          return (
            <div
              key={c.userId}
              className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-600)] text-xs font-semibold text-white shadow-sm">
                {(displayName || '?').slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[var(--text-primary)]">
                  {displayName}
                </p>
                {displayEmail && c.userName && (
                  <p className="truncate text-xs text-[var(--text-tertiary)]">
                    {displayEmail}
                  </p>
                )}
              </div>
              {canManage ? (
                <Select
                  value={c.role}
                  onValueChange={(v) => handleRoleChange(c.userId, v as CollaboratorRole)}
                >
                  <SelectTrigger className="h-7 w-28 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {t(`skillCollaborators.${r}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <div className="flex items-center gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[var(--surface-3)]">
                    <RoleIcon size={12} className="text-[var(--text-secondary)]" />
                  </div>
                  <span className="text-xs text-[var(--text-tertiary)]">
                    {t(`skillCollaborators.${c.role}`)}
                  </span>
                </div>
              )}
              {canManage && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-[var(--text-muted)] hover:text-red-500"
                  onClick={() => setRemoveTarget({ userId: c.userId, open: true })}
                  aria-label="Remove collaborator"
                >
                  <X size={14} />
                </Button>
              )}
            </div>
          )
        })}

        {collaborators.length === 0 && (
          <p className="py-4 text-center text-xs text-[var(--text-muted)]">
            {t('skillCollaborators.emptyState')}
          </p>
        )}
      </div>

      {/* Transfer ownership button */}
      {isOwner && (
        <div className="border-t border-[var(--border)] pt-4">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => setTransferDialog(true)}
          >
            {t('skillCollaborators.transferOwnership')}
          </Button>
        </div>
      )}

      {/* Remove confirm dialog */}
      <ConfirmDialog
        open={removeTarget.open}
        onOpenChange={(open) => setRemoveTarget((prev) => ({ ...prev, open }))}
        title={t('skillCollaborators.removeConfirmTitle')}
        description={t('skillCollaborators.removeConfirmMessage')}
        confirmLabel={t('skillCollaborators.remove')}
        cancelLabel={t('common.cancel')}
        variant="destructive"
        onConfirm={handleRemove}
      />

      {/* Transfer ownership dialog */}
      <Dialog open={transferDialog} onOpenChange={setTransferDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('skillCollaborators.transferConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('skillCollaborators.transferConfirmMessage')}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label>{t('skillCollaborators.newOwner')}</Label>
            <Input
              value={transferTargetId}
              onChange={(e) => setTransferTargetId(e.target.value)}
              placeholder={t('skillCollaborators.newOwnerPlaceholder')}
              className="mt-1"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTransferDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleTransfer} disabled={transferMutation.isPending}>
              {t('skillCollaborators.transferOwnership')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
