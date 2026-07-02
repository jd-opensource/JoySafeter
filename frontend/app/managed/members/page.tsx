'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedPut, managedDelete } from '@/lib/api-client'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { UserPlus, Trash2, Search } from 'lucide-react'
import { DataTable, RelativeTime, type Column, PageHeader } from '@/components/managed/shared'
import { toastOperationError } from '@/lib/managed/errors'
import { useSession } from '@/lib/auth/auth-client'
import { normalizeManagedRole, roleLabel, roleOptions } from '@/lib/managed/roles'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

interface MemberRecord {
  user_id: string
  email: string
  display_name: string
  role: string
  joined_at?: string
}

export default function MembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const session = useSession()
  const { canAdmin } = useUserPermissionsContext()

  // ── State ──
  const [showInvite, setShowInvite] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('developer')
  const [inviting, setInviting] = useState(false)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<
    { id: string; email: string; name: string; image?: string; already_member: boolean }[]
  >([])
  const [showDropdown, setShowDropdown] = useState(false)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Role change dialog
  const [roleTarget, setRoleTarget] = useState<MemberRecord | null>(null)
  const [newRole, setNewRole] = useState('developer')

  // Remove confirm
  const [removeTarget, setRemoveTarget] = useState<MemberRecord | null>(null)

  // ── Queries ──
  const { data: members = [], isLoading } = useQuery({
    queryKey: ['org-members'],
    queryFn: () => managedGet<MemberRecord[]>('auth/members'),
  })

  // ── Mutations ──
  const inviteMember = useMutation({
    mutationFn: (data: { email: string; role: string }) =>
      managedPost<MemberRecord>('auth/members/invite', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['org-members'] })
      resetInviteDialog(false)
    },
    onError: (err: Error) => {
      toastOperationError(t, err, 'manage.members.inviteFailed')
    },
  })

  const removeMemberMut = useMutation({
    mutationFn: (userId: string) => managedDelete(`auth/members/${userId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['org-members'] })
      setRemoveTarget(null)
    },
    onError: (err: Error) => {
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  const updateRoleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      managedPut<MemberRecord>(`auth/members/${userId}`, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['org-members'] })
      setRoleTarget(null)
    },
    onError: (err: Error) => {
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  // ── Handlers ──
  const resetInviteDialog = (open: boolean) => {
    setShowInvite(open)
    if (!open) {
      setEmail('')
      setRole('developer')
      setError('')
      setSearchQuery('')
      setSearchResults([])
      setShowDropdown(false)
    }
  }

  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    setEmail(value)
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    if (value.length < 2) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const results = await managedGet<
          { id: string; email: string; name: string; image?: string; already_member: boolean }[]
        >(`/auth/search-users?q=${encodeURIComponent(value)}&limit=5`)
        setSearchResults(results)
        setShowDropdown(true)
      } catch {
        setSearchResults([])
      }
    }, 300)
  }

  const selectUser = (user: { id: string; email: string; name: string }) => {
    setEmail(user.email)
    setSearchQuery(user.email)
    setShowDropdown(false)
  }

  const handleInvite = () => {
    if (!email.trim()) return
    setError('')
    inviteMember.mutate({ email: email.trim(), role })
  }

  const openRoleDialog = (m: MemberRecord) => {
    setRoleTarget(m)
    setNewRole(m.role)
  }

  const handleChangeRole = () => {
    if (!roleTarget) return
    updateRoleMut.mutate({ userId: roleTarget.user_id, role: newRole })
  }

  const handleRemove = () => {
    if (!removeTarget) return
    removeMemberMut.mutate(removeTarget.user_id)
  }

  const columns: Column<MemberRecord>[] = [
    {
      key: 'name',
      header: t('manage.members.name'),
      render: (member) => (
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
            {member.display_name?.charAt(0)?.toUpperCase() || '?'}
          </div>
          <span className="font-medium text-foreground">
            {member.display_name || '-'}
            {member.user_id === session?.data?.user?.id && (
              <span className="ml-1.5 text-xs text-muted-foreground">
                ({t('manage.members.you')})
              </span>
            )}
          </span>
        </div>
      ),
    },
    {
      key: 'email',
      header: t('manage.members.email'),
      render: (member) => <span className="text-muted-foreground">{member.email}</span>,
    },
    {
      key: 'role',
      header: t('manage.members.role'),
      render: (member) => (
        <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium">
          {roleLabel(t, member.role)}
        </span>
      ),
    },
    {
      key: 'joined',
      header: t('manage.members.joined'),
      render: (member) =>
        member.joined_at ? (
          <RelativeTime date={member.joined_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.members.title')}
        subtitle={t('manage.members.subtitle')}
        action={
          canAdmin ? (
            <Button size="sm" onClick={() => resetInviteDialog(true)}>
              <UserPlus className="mr-1 h-4 w-4" />
              {t('manage.members.invite')}
            </Button>
          ) : null
        }
      />

      <DataTable
        columns={columns}
        data={members}
        loading={isLoading}
        emptyMessage={t('manage.members.empty')}
        actionMenu={
          canAdmin
            ? (member) =>
                normalizeManagedRole(member.role) === 'owner'
                  ? []
                  : [
                      {
                        label: t('manage.members.changeRole'),
                        onClick: () => openRoleDialog(member),
                      },
                      {
                        label: t('manage.members.remove'),
                        icon: <Trash2 className="h-3.5 w-3.5" />,
                        destructive: true,
                        onClick: () => setRemoveTarget(member),
                      },
                    ]
            : undefined
        }
      />

      {/* Invite Dialog */}
      <Dialog open={showInvite} onOpenChange={resetInviteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.invite')}</DialogTitle>
            <DialogDescription>{t('manage.members.subtitle')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.email')}</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="user@example.com"
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  className="pl-9"
                  autoFocus
                />
                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-lg border border-border bg-background shadow-lg">
                    {searchResults.map((user) => (
                      <button
                        key={user.id}
                        type="button"
                        disabled={user.already_member}
                        onClick={() => selectUser(user)}
                        className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                          {user.name?.charAt(0)?.toUpperCase() ||
                            user.email?.charAt(0)?.toUpperCase() ||
                            '?'}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-foreground">
                            {user.name || user.email}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">{user.email}</div>
                        </div>
                        {user.already_member && (
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {t('manage.members.alreadyMember')}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.role')}</label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleOptions(t).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => resetInviteDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleInvite} disabled={!email.trim() || inviteMember.isPending}>
              {inviteMember.isPending ? t('common.loading') : t('manage.members.invite')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Change Role Dialog */}
      <Dialog
        open={!!roleTarget}
        onOpenChange={(v) => {
          if (!v) setRoleTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.changeRole')}</DialogTitle>
            <DialogDescription>{roleTarget?.display_name || roleTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Select value={newRole} onValueChange={setNewRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roleOptions(t).map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleChangeRole} disabled={newRole === roleTarget?.role}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Confirm Dialog */}
      <Dialog
        open={!!removeTarget}
        onOpenChange={(v) => {
          if (!v) setRemoveTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.remove')}</DialogTitle>
            <DialogDescription>{t('manage.members.removeConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleRemove}>
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
