'use client'

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, ShieldCheck, ShieldOff } from 'lucide-react'
import { managedPut } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ConfirmDialog,
  DataTable,
  type Column,
  MonoId,
  PageHeader,
  RelativeTime,
  ResourceErrorState,
  StatusBadge,
} from '@/components/managed/shared'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { toastOperationError } from '@/lib/managed/errors'
import { useAuthStore } from '@/stores/auth/store'

interface PlatformUser {
  id: string
  email: string
  name: string
  image?: string | null
  email_verified: boolean
  is_active: boolean
  is_super_user: boolean
  created_at: string
  updated_at: string
}

export default function PlatformUsersPage() {
  const queryClient = useQueryClient()
  const currentUserId = useAuthStore((state) => state.user?.id)
  const [query, setQuery] = useState('')
  const [pendingUser, setPendingUser] = useState<PlatformUser | null>(null)

  const search = query.trim()
  const usersPath = `/auth/platform/users${search ? `?q=${encodeURIComponent(search)}` : ''}`
  const {
    data: users,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset,
  } = usePaginatedList<PlatformUser>({
    queryKey: 'platform-users',
    path: usersPath,
  })

  const updateMutation = useMutation({
    mutationFn: (user: PlatformUser) =>
      managedPut<PlatformUser>(`/auth/platform/users/${user.id}`, {
        is_super_user: !user.is_super_user,
      }),
    onSuccess: () => {
      setPendingUser(null)
      queryClient.invalidateQueries({ queryKey: ['platform-users'] })
    },
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const columns: Column<PlatformUser>[] = [
    {
      key: 'user',
      header: '用户',
      render: (user) => (
        <div>
          <div className="font-medium">{user.name || user.email}</div>
          <div className="text-xs text-muted-foreground">{user.email}</div>
        </div>
      ),
    },
    { key: 'id', header: 'ID', render: (user) => <MonoId id={user.id} /> },
    {
      key: 'super',
      header: '平台管理员',
      render: (user) => <StatusBadge status={user.is_super_user ? 'active' : 'archived'} />,
    },
    { key: 'active', header: '账号状态', render: (user) => (user.is_active ? '启用' : '禁用') },
    {
      key: 'created_at',
      header: '注册时间',
      render: (user) => <RelativeTime date={user.created_at} />,
    },
    {
      key: 'actions',
      header: '操作',
      render: (user) => (
        <Button
          size="sm"
          variant={user.is_super_user ? 'destructive' : 'outline'}
          disabled={user.id === currentUserId && user.is_super_user}
          onClick={() => setPendingUser(user)}
        >
          {user.is_super_user ? (
            <ShieldOff className="mr-1 h-3.5 w-3.5" />
          ) : (
            <ShieldCheck className="mr-1 h-3.5 w-3.5" />
          )}
          {user.is_super_user ? '撤销平台管理员' : '设为平台管理员'}
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="平台用户"
        subtitle="管理全局平台管理员。平台管理员可以维护跨组织基础设施配置，例如存储卷底层挂载。"
      />
      <div className="flex max-w-md items-center gap-2">
        <Search className="h-4 w-4 text-muted-foreground" />
        <Input
          value={query}
          placeholder="搜索邮箱或姓名"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {isError ? (
        <ResourceErrorState error={error} resource="project" />
      ) : (
        <DataTable
          data={users}
          columns={columns}
          loading={isLoading}
          fetching={isFetching}
          emptyMessage="暂无用户"
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
      )}
      <ConfirmDialog
        open={!!pendingUser}
        title={pendingUser?.is_super_user ? '撤销平台管理员' : '设为平台管理员'}
        description={
          pendingUser
            ? `确定${pendingUser.is_super_user ? '撤销' : '授予'} ${pendingUser.email} 的平台管理员权限吗？`
            : ''
        }
        confirmLabel={pendingUser?.is_super_user ? '撤销' : '授予'}
        destructive={Boolean(pendingUser?.is_super_user)}
        onCancel={() => setPendingUser(null)}
        onConfirm={() => pendingUser && updateMutation.mutate(pendingUser)}
      />
    </div>
  )
}
