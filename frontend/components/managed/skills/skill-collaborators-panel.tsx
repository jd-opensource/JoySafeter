'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { DataTable, type Column } from '@/components/managed/shared'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import {
  type ManagedRequestScope,
  hasManagedRequestScope,
  managedRequestOptions,
} from '@/lib/managed/request-scope'
import {
  type SkillCapability,
  canManageSkillCollaborators,
  projectRoleOptions,
} from '@/lib/managed/roles'

interface SkillCollaboratorRecord {
  user_id: string
  email: string
  display_name: string
  role: string
}

interface UserSearchResult {
  id: string
  email: string
  name: string
  image?: string
  already_member: boolean
}

const DEFAULT_ROLE = 'viewer'

function RoleSelect({
  value,
  onValueChange,
  triggerClassName,
}: {
  value: string
  onValueChange: (value: string) => void
  triggerClassName: string
}) {
  const { t } = useTranslation()
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className={triggerClassName}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {projectRoleOptions(t).map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function SkillCollaboratorsPanel({
  skillId,
  capability,
  requestScope,
  queryScopeKey,
}: {
  skillId: string
  capability?: SkillCapability
  requestScope: ManagedRequestScope
  queryScopeKey: string
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canManage = canManageSkillCollaborators(capability)

  const listKey = ['skill-collaborators', queryScopeKey, skillId] as const

  const {
    data: collaborators = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: listKey,
    queryFn: () =>
      managedGet<SkillCollaboratorRecord[]>(
        apiResourcePath('skills', skillId, 'collaborators'),
        managedRequestOptions(requestScope),
      ),
    enabled: canManage && !!skillId && hasManagedRequestScope(requestScope),
    retry: false,
  })

  const grantMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      managedPost(
        apiResourcePath('skills', skillId, 'collaborators'),
        { user_id: userId, role },
        managedRequestOptions(requestScope),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  const [removeTarget, setRemoveTarget] = useState<SkillCollaboratorRecord | null>(null)
  const removeMut = useMutation({
    mutationFn: ({ userId }: { userId: string }) =>
      managedDelete(
        apiResourcePath('skills', skillId, 'collaborators', userId),
        managedRequestOptions(requestScope),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey })
      setRemoveTarget(null)
    },
    onError: (err: Error) => toastOperationError(t, err, 'common.operationFailed'),
  })

  // ── Add-collaborator form: debounced org-user search + role picker ──
  const [addRole, setAddRole] = useState<string>(DEFAULT_ROLE)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [searchResults, setSearchResults] = useState<UserSearchResult[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchSeqRef = useRef(0)

  useEffect(
    () => () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    },
    [],
  )

  const existingIds = useMemo(() => new Set(collaborators.map((c) => c.user_id)), [collaborators])

  const resetAddForm = () => {
    searchSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setSearchQuery('')
    setSelectedUserId(null)
    setSearchResults([])
    setShowDropdown(false)
    setAddRole(DEFAULT_ROLE)
  }

  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    setSelectedUserId(null)
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    const seq = (searchSeqRef.current += 1)
    if (value.trim().length < 2) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const results = await managedGet<UserSearchResult[]>(
          `/auth/search-users?q=${encodeURIComponent(value.trim())}&limit=5`,
        )
        if (seq !== searchSeqRef.current) return
        setSearchResults(results)
        setShowDropdown(true)
      } catch {
        if (seq !== searchSeqRef.current) return
        setSearchResults([])
      }
    }, 300)
  }

  const selectUser = (user: UserSearchResult) => {
    searchSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setSelectedUserId(user.id)
    setSearchQuery(user.email || user.name)
    setShowDropdown(false)
  }

  const handleAdd = () => {
    if (!selectedUserId || existingIds.has(selectedUserId)) return
    grantMut.mutate({ userId: selectedUserId, role: addRole }, { onSuccess: () => resetAddForm() })
  }

  const handleRoleChange = (member: SkillCollaboratorRecord, value: string) => {
    if (value === member.role) return
    grantMut.mutate({ userId: member.user_id, role: value })
  }

  const columns: Column<SkillCollaboratorRecord>[] = [
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
      key: 'role',
      header: t('managed.skills.collaborators.role'),
      render: (m) => (
        <RoleSelect
          value={m.role}
          onValueChange={(v) => handleRoleChange(m, v)}
          triggerClassName="h-8 w-36"
        />
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (m) => (
        <Button variant="ghost" size="sm" onClick={() => setRemoveTarget(m)}>
          {t('managed.skills.collaborators.remove')}
        </Button>
      ),
    },
  ]

  if (!canManage) {
    return (
      <div className="p-4">
        <p className="text-sm text-muted-foreground">
          {t('managed.skills.collaborators.adminOnly')}
        </p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-4">
        <p className="text-sm text-muted-foreground">
          {t('managed.skills.collaborators.loadFailed')}
        </p>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4">
      <div>
        <h3 className="text-sm font-medium text-foreground">
          {t('managed.skills.collaborators.title')}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {t('managed.skills.collaborators.subtitle')}
        </p>
      </div>

      {/* Add form */}
      <div className="flex flex-wrap items-start gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Input
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder={t('managed.skills.collaborators.searchPlaceholder')}
            aria-label={t('managed.skills.collaborators.searchPlaceholder')}
          />
          {showDropdown && searchResults.length > 0 && (
            <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-border bg-popover shadow-md">
              {searchResults.map((u) => {
                const disabled = existingIds.has(u.id)
                return (
                  <button
                    key={u.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => selectUser(u)}
                    className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="font-medium">{u.name || u.email}</span>
                    <span className="text-xs text-muted-foreground">
                      {u.email}
                      {disabled ? ` · ${t('managed.skills.collaborators.alreadyAdded')}` : ''}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
        <RoleSelect value={addRole} onValueChange={setAddRole} triggerClassName="h-9 w-32" />
        <Button
          onClick={handleAdd}
          disabled={!selectedUserId || grantMut.isPending || existingIds.has(selectedUserId)}
        >
          {t('managed.skills.collaborators.add')}
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={collaborators}
        loading={isLoading}
        emptyMessage={t('managed.skills.collaborators.empty')}
      />

      {/* Remove confirm */}
      <Dialog open={!!removeTarget} onOpenChange={(v) => !v && setRemoveTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.collaborators.remove')}</DialogTitle>
            <DialogDescription>
              {t('managed.skills.collaborators.removeConfirm', {
                name: removeTarget?.display_name || removeTarget?.email || '',
              })}
            </DialogDescription>
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
