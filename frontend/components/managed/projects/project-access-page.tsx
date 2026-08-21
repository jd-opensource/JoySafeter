'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, LockKeyhole } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import {
  DataTable,
  FilterBar,
  type Column,
  type FilterDef,
  PageHeader,
} from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
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
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { effectiveProjectAccessValue } from '@/lib/managed/project-access'
import { projectRoleLabel, roleLabel } from '@/lib/managed/roles'

interface ProjectAccessRecord {
  id?: string
  user_id: string
  email: string
  display_name: string
  org_role: string
  access: 'org_wide' | 'default' | 'explicit' | 'none' | string
  project_role?: string | null
  joined_at?: string | null
}

interface ProjectSummary {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
}

const PROJECT_ROLE_VALUES = ['viewer', 'editor', 'admin'] as const

export function ProjectAccessPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ProjectAccessRecord | null>(null)
  const [memberSearch, setMemberSearch] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [savedUserId, setSavedUserId] = useState<string | null>(null)

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => managedGet<ProjectSummary>(`auth/projects/${projectId}`),
    enabled: Boolean(projectId),
  })

  const {
    data: organizationMembers,
    isLoading,
    isFetching,
    isError,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset: resetAccessPagination,
  } = usePaginatedList<ProjectAccessRecord>({
    queryKey: 'project-access',
    path: `/auth/projects/${projectId}/members${memberSearch.trim() ? `?q=${encodeURIComponent(memberSearch.trim())}` : ''}`,
    enabled: Boolean(projectId),
  })
  const filteredMembers = organizationMembers.filter(
    (member) =>
      filterByCreatedTime(member.joined_at || '', createdFilter) &&
      matchesSearch(memberSearch, [member.user_id, member.display_name, member.email]),
  )

  const showSavedFeedback = (userId: string) => {
    if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
    setSavedUserId(userId)
    savedTimerRef.current = setTimeout(() => setSavedUserId(null), 2400)
  }

  useEffect(
    () => () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
    },
    [],
  )

  const grantMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      managedPost(`auth/projects/${projectId}/members`, { user_id: userId, role }),
    onMutate: ({ userId }) => {
      if (savedUserId === userId) setSavedUserId(null)
    },
    onSuccess: (_result, variables) => {
      resetAccessPagination()
      queryClient.invalidateQueries({ queryKey: ['project-access'] })
      showSavedFeedback(variables.userId)
    },
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  const revokeMut = useMutation({
    mutationFn: ({ userId }: { userId: string }) =>
      managedDelete(`auth/projects/${projectId}/members/${userId}`),
    onSuccess: (_result, variables) => {
      resetAccessPagination()
      queryClient.invalidateQueries({ queryKey: ['project-access'] })
      setRevokeTarget(null)
      showSavedFeedback(variables.userId)
    },
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  const handleRoleChange = (member: ProjectAccessRecord, value: string) => {
    const current = effectiveProjectAccessValue(member.access, member.project_role)
    if (value === current) return
    if (value === 'none') {
      setRevokeTarget(member)
      return
    }
    grantMut.mutate({ userId: member.user_id, role: value })
  }

  const subtitle = project ? project.name : t('manage.projectMembers.subtitle')
  const pendingUserId = grantMut.isPending
    ? grantMut.variables?.userId
    : revokeMut.isPending
      ? revokeMut.variables?.userId
      : null

  const columns: Column<ProjectAccessRecord>[] = [
    {
      key: 'name',
      header: t('manage.members.name'),
      render: (member) => (
        <span className="font-medium text-foreground">{member.display_name || '-'}</span>
      ),
    },
    {
      key: 'email',
      header: t('manage.members.email'),
      render: (member) => <span className="text-muted-foreground">{member.email}</span>,
    },
    {
      key: 'org_role',
      header: t('manage.projectMembers.orgRole'),
      render: (member) => (
        <span className="text-muted-foreground">{roleLabel(t, member.org_role)}</span>
      ),
    },
    {
      key: 'access',
      header: t('manage.projectMembers.access'),
      render: (member) => {
        if (member.access === 'org_wide') {
          return (
            <Badge variant="outline" className="gap-1">
              <LockKeyhole className="size-3" />
              {t('manage.projectMembers.accessOrgWide')}
            </Badge>
          )
        }
        const value = effectiveProjectAccessValue(member.access, member.project_role)
        const pending = pendingUserId === member.user_id
        const saved = savedUserId === member.user_id && !pending
        return (
          <div className="flex flex-col items-start gap-1">
            <Select
              value={value}
              onValueChange={(nextValue) => handleRoleChange(member, nextValue)}
              disabled={pending}
            >
              <SelectTrigger className="h-8 w-40">
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
            {member.access === 'default' ? (
              <span className="text-xs text-muted-foreground">
                {t('manage.projectMembers.accessDefault')}
              </span>
            ) : member.access === 'explicit' ? (
              <span className="text-xs text-muted-foreground">
                {t('manage.projectMembers.accessExplicit')}
              </span>
            ) : null}
            {pending ? (
              <span className="text-xs text-muted-foreground">
                {t('manage.projectMembers.saving')}
              </span>
            ) : saved ? (
              <span className="text-xs text-muted-foreground">
                {t('manage.projectMembers.saved')}
              </span>
            ) : project?.is_default ? (
              <span className="text-xs text-muted-foreground">
                {t('manage.projectMembers.defaultProjectRestriction')}
              </span>
            ) : null}
          </div>
        )
      },
    },
  ]
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
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

      <Alert className="mb-4">
        <Info />
        <AlertDescription className="flex flex-col gap-1">
          <p>{t('manage.projectMembers.inheritedExplanation')}</p>
          {project?.is_default ? (
            <p>{t('manage.projectMembers.defaultProjectRestriction')}</p>
          ) : null}
        </AlertDescription>
      </Alert>

      <FilterBar
        searchPlaceholder={t('manage.projectMembers.searchPlaceholder')}
        searchValue={memberSearch}
        onSearchChange={(value) => {
          resetAccessPagination()
          setMemberSearch(value)
        }}
        filters={filters}
      />

      <DataTable
        columns={columns}
        data={filteredMembers}
        loading={isLoading}
        fetching={isFetching}
        emptyMessage={t('manage.projectMembers.empty')}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
      />

      {!isLoading && organizationMembers.length === 0 && project?.org_id ? (
        <Button asChild variant="outline" className="mt-4">
          <Link href={`/managed/settings/organizations/${project?.org_id}/members`}>
            {t('manage.projectMembers.manageMembers')}
          </Link>
        </Button>
      ) : null}

      <Dialog open={!!revokeTarget} onOpenChange={(open) => !open && setRevokeTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projectMembers.remove')}</DialogTitle>
            <DialogDescription>{t('manage.projectMembers.removeConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => revokeTarget && revokeMut.mutate({ userId: revokeTarget.user_id })}
              disabled={revokeMut.isPending}
            >
              {t('manage.projectMembers.remove')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
