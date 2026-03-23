'use client'

import { Plus, User, UserPlus, Users, X } from 'lucide-react'
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

export function CollaboratorsTab({ skillId, ownerId, userRole }: CollaboratorsTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showAddForm, setShowAddForm] = useState(false)
  const [newUserId, setNewUserId] = useState('')
  const [newRole, setNewRole] = useState<CollaboratorRole>('viewer')
  const [removeTarget, setRemoveTarget] = useState<{ userId: string; open: boolean }>({
    userId: '',
    open: false,
  })
  const [transferDialog, setTransferDialog] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState('')

  const { data: collaborators = [], isLoading } = useSkillCollaborators(skillId)
  const addMutation = useAddCollaborator(skillId)
  const updateRoleMutation = useUpdateCollaboratorRole(skillId)
  const removeMutation = useRemoveCollaborator(skillId)
  const transferMutation = useTransferOwnership(skillId)

  const canManage = ['owner', 'admin'].includes(userRole)
  const isOwner = userRole === 'owner'

  const handleAdd = async () => {
    if (!newUserId.trim()) return
    try {
      await addMutation.mutateAsync({ user_id: newUserId.trim(), role: newRole })
      toast({ title: t('skillCollaborators.addedSuccess') })
      setNewUserId('')
      setNewRole('viewer')
      setShowAddForm(false)
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRoleChange = async (userId: string, role: CollaboratorRole) => {
    try {
      await updateRoleMutation.mutateAsync({ userId, role })
      toast({ title: t('skillCollaborators.updatedSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRemove = async () => {
    try {
      await removeMutation.mutateAsync(removeTarget.userId)
      toast({ title: t('skillCollaborators.removedSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
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
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
      </div>
    )
  }

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
            <div className="mt-3 flex items-end gap-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <div className="flex-1">
                <Label className="text-xs">{t('skillCollaborators.userId')}</Label>
                <Input
                  value={newUserId}
                  onChange={(e) => setNewUserId(e.target.value)}
                  placeholder={t('skillCollaborators.userIdPlaceholder')}
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
              <Button size="sm" onClick={handleAdd} disabled={addMutation.isPending}>
                <Plus size={14} />
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Collaborator list */}
      <div className="space-y-1">
        {/* Owner row (always first) */}
        <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-200">
            <User size={12} className="text-gray-500" />
          </div>
          <span className="flex-1 text-sm font-medium">{ownerId}</span>
          <span className="text-xs text-gray-400">({t('skillCollaborators.owner')})</span>
        </div>

        {/* Collaborator rows */}
        {collaborators.map((c) => (
          <div
            key={c.userId}
            className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2"
          >
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-200">
              <User size={12} className="text-gray-500" />
            </div>
            <span className="flex-1 text-sm">{c.userId}</span>
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
              <span className="text-xs text-gray-500">
                {t(`skillCollaborators.${c.role}`)}
              </span>
            )}
            {canManage && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-gray-400 hover:text-red-500"
                onClick={() => setRemoveTarget({ userId: c.userId, open: true })}
              >
                <X size={14} />
              </Button>
            )}
          </div>
        ))}

        {collaborators.length === 0 && (
          <p className="py-4 text-center text-xs text-gray-400">
            {t('skillCollaborators.emptyState')}
          </p>
        )}
      </div>

      {/* Transfer ownership button */}
      {isOwner && (
        <div className="border-t border-gray-200 pt-4">
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
      <AlertDialog
        open={removeTarget.open}
        onOpenChange={(open) => setRemoveTarget((prev) => ({ ...prev, open }))}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('skillCollaborators.removeConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('skillCollaborators.removeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRemove}
              className="bg-red-600 text-white hover:bg-red-700"
            >
              {t('skillCollaborators.remove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
