'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
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
import { roleLabel, projectRoleLabel } from '@/lib/managed/roles'

interface ProjectMemberRecord {
  user_id: string
  email: string
  display_name: string
  org_role: string
  access: 'org_wide' | 'explicit' | 'none' | string
  project_role?: string | null
}

interface ProjectSummary {
  id: string
  name: string
  slug: string
  is_default: boolean
}

const PROJECT_ROLE_VALUES = ['viewer', 'editor', 'admin'] as const

export default function ProjectMembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const params = useParams<{ projectId: string }>()
  const projectId = params?.projectId ?? ''

  const [removeTarget, setRemoveTarget] = useState<ProjectMemberRecord | null>(null)

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => managedGet<ProjectSummary>(`auth/projects/${projectId}`),
    enabled: Boolean(projectId),
  })

  const {
    data: members = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => managedGet<ProjectMemberRecord[]>(`auth/projects/${projectId}/members`),
    enabled: Boolean(projectId),
    retry: false,
  })

  const grantMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      managedPost(`auth/projects/${projectId}/members`, { user_id: userId, role }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['project-members', projectId] }),
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

  // Inline role change: selecting a role grants/updates; selecting "no access"
  // is destructive, so it routes through an explicit confirm dialog instead.
  const handleRoleChange = (member: ProjectMemberRecord, value: string) => {
    const current = member.access === 'explicit' ? member.project_role || 'editor' : 'none'
    if (value === current) return
    if (value === 'none') {
      setRemoveTarget(member)
      return
    }
    grantMut.mutate({ userId: member.user_id, role: value })
  }

  const subtitle = project ? project.name : t('manage.projectMembers.subtitle')

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
      render: (m) => {
        if (m.access === 'org_wide') {
          return (
            <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium">
              {t('manage.projectMembers.accessOrgWide')}
            </span>
          )
        }
        const value = m.access === 'explicit' ? m.project_role || 'editor' : 'none'
        return (
          <Select value={value} onValueChange={(v) => handleRoleChange(m, v)}>
            <SelectTrigger className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled={project?.is_default}>
                {t('manage.projectMembers.accessNone')}
              </SelectItem>
              {PROJECT_ROLE_VALUES.map((role) => (
                <SelectItem key={role} value={role}>
                  {projectRoleLabel(t, role)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      },
    },
  ]

  if (isError) {
    return (
      <div className="w-full">
        <PageHeader title={t('manage.projectMembers.title')} subtitle={subtitle} />
        <p className="text-sm text-muted-foreground">{t('manage.projectMembers.adminOnly')}</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <PageHeader title={t('manage.projectMembers.title')} subtitle={subtitle} />

      <DataTable
        columns={columns}
        data={members}
        loading={isLoading}
        emptyMessage={t('manage.members.empty')}
      />

      {/* Remove confirm dialog (destructive path of the inline role select) */}
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
