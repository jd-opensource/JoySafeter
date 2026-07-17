'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { DataTable, type Column, PageHeader } from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { roleLabel, projectRoleLabel, projectRoleOptions } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'

interface ProjectMemberRecord {
  user_id: string
  email: string
  display_name: string
  org_role: string
  access: 'org_wide' | 'explicit' | 'none' | string
  project_role?: string | null
}

export default function ProjectMembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const currentProject = useProjectStore((state) => state.currentProject)
  const projectId = currentProjectId ?? ''
  const isProjectAdmin = currentProject?.capability === 'admin'

  const [grantTarget, setGrantTarget] = useState<ProjectMemberRecord | null>(null)
  const [grantRole, setGrantRole] = useState('editor')
  const [removeTarget, setRemoveTarget] = useState<ProjectMemberRecord | null>(null)

  const { data: members = [], isLoading } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => managedGet<ProjectMemberRecord[]>(`auth/projects/${projectId}/members`),
    enabled: Boolean(projectId) && isProjectAdmin,
  })

  const grantMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      managedPost(`auth/projects/${projectId}/members`, { user_id: userId, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
      setGrantTarget(null)
    },
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  const removeMut = useMutation({
    mutationFn: ({ userId }: { userId: string }) =>
      managedDelete(`auth/projects/${projectId}/members/${userId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
      setRemoveTarget(null)
    },
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  const openGrant = (member: ProjectMemberRecord) => {
    setGrantRole(member.project_role || 'editor')
    setGrantTarget(member)
  }

  const accessBadge = (member: ProjectMemberRecord) => {
    if (member.access === 'org_wide') return t('manage.projectMembers.accessOrgWide')
    if (member.access === 'explicit') return projectRoleLabel(t, member.project_role)
    return t('manage.projectMembers.accessNone')
  }

  const columns: Column<ProjectMemberRecord>[] = [
    {
      key: 'name',
      header: t('manage.members.name'),
      render: (m) => <span className="font-medium text-foreground">{m.display_name || '-'}</span>,
    },
    {
      key: 'email',
      header: t('manage.members.email'),
      render: (m) => <span className="text-muted-foreground">{m.email}</span>,
    },
    {
      key: 'org_role',
      header: t('manage.projectMembers.orgRole'),
      render: (m) => <span className="text-muted-foreground">{roleLabel(t, m.org_role)}</span>,
    },
    {
      key: 'access',
      header: t('manage.projectMembers.access'),
      render: (m) => (
        <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium">
          {accessBadge(m)}
        </span>
      ),
    },
  ]

  if (!isProjectAdmin) {
    return (
      <div className="w-full">
        <PageHeader
          title={t('manage.projectMembers.title')}
          subtitle={t('manage.projectMembers.subtitle')}
        />
        <p className="text-sm text-muted-foreground">{t('manage.projectMembers.adminOnly')}</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.projectMembers.title')}
        subtitle={t('manage.projectMembers.subtitle')}
      />

      <DataTable
        columns={columns}
        data={members}
        loading={isLoading}
        emptyMessage={t('manage.members.empty')}
        actionMenu={(member) => {
          if (member.access === 'org_wide') return []
          if (member.access === 'explicit') {
            return [
              {
                label: t('manage.projectMembers.changeRole'),
                onClick: () => openGrant(member),
              },
              {
                label: t('manage.projectMembers.remove'),
                icon: <Trash2 className="h-3.5 w-3.5" />,
                destructive: true,
                onClick: () => setRemoveTarget(member),
              },
            ]
          }
          return [
            {
              label: t('manage.projectMembers.add'),
              onClick: () => openGrant(member),
            },
          ]
        }}
      />

      {/* Grant / change role dialog */}
      <Dialog open={!!grantTarget} onOpenChange={(v) => !v && setGrantTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projectMembers.assignRole')}</DialogTitle>
            <DialogDescription>{grantTarget?.display_name || grantTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Select value={grantRole} onValueChange={setGrantRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {projectRoleOptions(t).map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={() =>
                grantTarget && grantMut.mutate({ userId: grantTarget.user_id, role: grantRole })
              }
              disabled={grantMut.isPending}
            >
              {grantMut.isPending ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove confirm dialog */}
      <Dialog open={!!removeTarget} onOpenChange={(v) => !v && setRemoveTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projectMembers.remove')}</DialogTitle>
            <DialogDescription>{t('manage.projectMembers.removeConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => removeTarget && removeMut.mutate({ userId: removeTarget.user_id })}
              disabled={removeMut.isPending}
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
