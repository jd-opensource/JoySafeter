'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedDelete, managedPut } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import {
  DataTable,
  MonoId,
  RelativeTime,
  type Column,
  type MenuItem,
  PageHeader,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Plus, Check, Trash2, Pencil, Crown } from 'lucide-react'
import { useProjectStore } from '@/stores/managed/project-store'
import { canAdmin, canOwn, roleLabel } from '@/lib/managed/roles'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

interface MeResponse {
  organization: {
    id: string
    name: string
    slug: string
    role: string
    created_at?: string
  }
  organizations: { id: string; name: string; slug: string; role: string; created_at?: string }[]
}

interface OrganizationMember {
  id: string
  user_id: string
  organization_id: string
  role: string
  user_name?: string | null
  user_email?: string | null
}

export default function OrganizationPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canAdmin: canManageOrganizations } = useUserPermissionsContext()
  const [showCreateOrg, setShowCreateOrg] = useState(false)
  const [newOrgName, setNewOrgName] = useState('')

  const { data: me } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => managedGet<MeResponse>('auth/me'),
  })

  const currentOrg = me?.organization
  const organizations = me?.organizations || []

  const createOrgMutation = useMutation({
    mutationFn: (name: string) =>
      managedPost<{ id: string; name: string; slug: string }>('auth/organizations', { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      setShowCreateOrg(false)
      setNewOrgName('')
    },
    onError: (error) => {
      toastOperationError(t, error, 'manage.organization.createFailed')
    },
  })

  const switchOrgMutation = useMutation({
    mutationFn: (orgId: string) =>
      managedPost<{ org_id: string; project_id: string }>('auth/switch-context', { org_id: orgId }),
    onSuccess: (data, orgId) => {
      const { setCurrentOrg, setCurrentProject } = useProjectStore.getState()
      setCurrentOrg(orgId)
      if (data?.project_id) {
        setCurrentProject(data.project_id)
      }
      queryClient.invalidateQueries()
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  const deleteOrgMutation = useMutation({
    mutationFn: (orgId: string) => managedDelete(`/organizations/${orgId}`),
    onSuccess: () => {
      setDeleteTarget(null)
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const [editTarget, setEditTarget] = useState<{ id: string; name: string } | null>(null)
  const [editName, setEditName] = useState('')
  const [transferTarget, setTransferTarget] = useState<{ id: string; name: string } | null>(null)
  const [selectedNewOwnerId, setSelectedNewOwnerId] = useState('')

  const editOrgMutation = useMutation({
    mutationFn: ({ orgId, name }: { orgId: string; name: string }) =>
      managedPut(`/organizations/${orgId}`, { name }),
    onSuccess: () => {
      setEditTarget(null)
      setEditName('')
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const { data: transferMembers = [], isLoading: isLoadingTransferMembers } = useQuery({
    queryKey: ['organization-members', transferTarget?.id],
    queryFn: async () => {
      const response = await managedGet<{ data: OrganizationMember[] }>(
        `/organizations/${transferTarget!.id}/members`,
      )
      return response.data
    },
    enabled: !!transferTarget,
  })

  const transferCandidates = transferMembers.filter((member) => member.role !== 'owner')

  const transferOwnershipMutation = useMutation({
    mutationFn: ({ orgId, userId }: { orgId: string; userId: string }) =>
      managedPost(`/organizations/${orgId}/transfer-ownership`, { new_owner_user_id: userId }),
    onSuccess: () => {
      setTransferTarget(null)
      setSelectedNewOwnerId('')
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organization-members'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'manage.organization.transferFailed')
    },
  })

  type Organization = MeResponse['organizations'][number]

  const columns: Column<Organization>[] = [
    {
      key: 'name',
      header: t('manage.organization.name'),
      render: (org) => {
        const isCurrent = org.id === currentOrg?.id
        return (
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground">{org.name}</span>
            {isCurrent && (
              <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
                <Check className="h-3 w-3" />
                {t('manage.organization.current')}
              </span>
            )}
          </div>
        )
      },
    },
    {
      key: 'slug',
      header: 'Slug',
      render: (org) => <MonoId id={org.slug} truncate={false} />,
    },
    {
      key: 'role',
      header: t('manage.members.role'),
      render: (org) => <span className="text-muted-foreground">{roleLabel(t, org.role)}</span>,
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (org) =>
        org.created_at ? (
          <RelativeTime date={org.created_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.organization.title')}
        subtitle={t('manage.organization.subtitle')}
        action={
          canManageOrganizations ? (
            <Button size="sm" onClick={() => setShowCreateOrg(true)}>
              <Plus className="mr-1 h-4 w-4" />
              {t('manage.organization.create')}
            </Button>
          ) : null
        }
      />

      <DataTable
        columns={columns}
        data={organizations}
        emptyMessage={t('manage.organization.empty')}
        actionMenu={
          canManageOrganizations
            ? (org) => {
                const isCurrent = org.id === currentOrg?.id
                const items: MenuItem[] = []

                if (canAdmin(org.role)) {
                  items.push({
                    label: t('common.edit'),
                    icon: <Pencil className="h-3.5 w-3.5" />,
                    onClick: () => {
                      setEditTarget({ id: org.id, name: org.name })
                      setEditName(org.name)
                    },
                  })
                }

                if (!isCurrent) {
                  items.push({
                    label: t('manage.organization.switch'),
                    onClick: () => switchOrgMutation.mutate(org.id),
                  })
                }

                if (canOwn(org.role)) {
                  items.push({
                    label: t('manage.organization.transferOwnership'),
                    icon: <Crown className="h-3.5 w-3.5" />,
                    onClick: () => {
                      setTransferTarget({ id: org.id, name: org.name })
                      setSelectedNewOwnerId('')
                    },
                  })
                }

                if (canOwn(org.role) && !isCurrent) {
                  items.push({
                    label: t('common.delete'),
                    icon: <Trash2 className="h-3.5 w-3.5" />,
                    destructive: true,
                    onClick: () => setDeleteTarget({ id: org.id, name: org.name }),
                  })
                }

                return items
              }
            : undefined
        }
      />

      {/* Create Organization Dialog */}
      <Dialog open={showCreateOrg} onOpenChange={setShowCreateOrg}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.create')}</DialogTitle>
            <DialogDescription>{t('manage.organization.createDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.organization.name')}</label>
              <Input
                placeholder={t('manage.organization.namePlaceholder')}
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newOrgName.trim())
                    createOrgMutation.mutate(newOrgName.trim())
                }}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateOrg(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={() => createOrgMutation.mutate(newOrgName.trim())}
              disabled={!newOrgName.trim() || createOrgMutation.isPending}
            >
              {createOrgMutation.isPending ? t('common.loading') : t('manage.organization.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Organization Dialog */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.delete')}</DialogTitle>
            <DialogDescription>
              {t('manage.organization.deleteConfirm', { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && deleteOrgMutation.mutate(deleteTarget.id)}
              disabled={deleteOrgMutation.isPending}
            >
              {deleteOrgMutation.isPending ? t('common.loading') : t('manage.organization.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Organization Dialog */}
      <Dialog open={editTarget !== null} onOpenChange={(open) => !open && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.edit')}</DialogTitle>
            <DialogDescription>{t('manage.organization.editDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.organization.name')}</label>
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder={t('manage.organization.namePlaceholder')}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={() =>
                editTarget &&
                editOrgMutation.mutate({ orgId: editTarget.id, name: editName.trim() })
              }
              disabled={!editName.trim() || editOrgMutation.isPending}
            >
              {editOrgMutation.isPending ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Transfer Ownership Dialog */}
      <Dialog
        open={transferTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTransferTarget(null)
            setSelectedNewOwnerId('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.transferOwnership')}</DialogTitle>
            <DialogDescription>{t('manage.organization.transferOwnershipDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {isLoadingTransferMembers ? (
              <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
            ) : transferCandidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('manage.organization.noTransferCandidates')}
              </p>
            ) : (
              <div className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
                {transferCandidates.map((member) => {
                  const label = member.user_name || member.user_email || member.user_id
                  return (
                    <button
                      key={member.user_id}
                      type="button"
                      className={`w-full px-3 py-2 text-left hover:bg-muted/60 ${selectedNewOwnerId === member.user_id ? 'bg-muted' : ''}`}
                      onClick={() => setSelectedNewOwnerId(member.user_id)}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-foreground">
                            {label}
                          </div>
                          {member.user_email && member.user_name && (
                            <div className="truncate text-xs text-muted-foreground">
                              {member.user_email}
                            </div>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {roleLabel(t, member.role)}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setTransferTarget(null)
                setSelectedNewOwnerId('')
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                transferTarget &&
                transferOwnershipMutation.mutate({
                  orgId: transferTarget.id,
                  userId: selectedNewOwnerId,
                })
              }
              disabled={!selectedNewOwnerId || transferOwnershipMutation.isPending}
            >
              {transferOwnershipMutation.isPending
                ? t('common.loading')
                : t('manage.organization.transferOwnership')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
