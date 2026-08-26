'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Crown, Info, Save, Trash2 } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { managedDelete, managedGet, managedPost, managedPut } from '@/lib/api-client'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { normalizeManagedRole, roleLabel } from '@/lib/managed/roles'
import {
  parseOrganizationDetailResponse,
  parseOrganizationMemberPageResponse,
  type OrganizationDetail,
} from '@/lib/managed/tenant-response-parsers'
import { useProjectStore } from '@/stores/managed/project-store'
import { parseOrganizationId, type OrganizationId, type UserId } from '@/types/entity-id'

interface OrganizationDraft {
  organizationId: OrganizationId
  name: string
  projectCreationPolicy: 'admins_only' | 'all_members'
}

export default function OrganizationOverviewPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const params = useParams<{ organizationId: string }>()
  const organizationId = parseOrganizationId(params.organizationId)
  const queryClient = useQueryClient()
  const session = useSession()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const [draft, setDraft] = useState<OrganizationDraft | null>(null)
  const [showTransfer, setShowTransfer] = useState(false)
  const [selectedNewOwnerId, setSelectedNewOwnerId] = useState<UserId | null>(null)
  const [showDelete, setShowDelete] = useState(false)

  const organizationQuery = useQuery({
    queryKey: ['organization-detail', organizationId],
    queryFn: () =>
      managedGet<unknown>(`organizations/${organizationId}`).then(parseOrganizationDetailResponse),
    enabled: Boolean(organizationId),
  })
  const organization = organizationQuery.data
  const normalizedRole = normalizeManagedRole(organization?.role)
  const canEdit = normalizedRole === 'owner' || normalizedRole === 'admin'
  const isOwner = normalizedRole === 'owner'
  const isCurrent = currentOrgId === organizationId
  const activeDraft = draft?.organizationId === organizationId ? draft : null
  const name = activeDraft?.name ?? organization?.name ?? ''
  const projectCreationPolicy =
    activeDraft?.projectCreationPolicy ?? organization?.project_creation_policy ?? 'admins_only'

  const membersQuery = useQuery({
    queryKey: ['organization-members', organizationId, 'ownership-transfer'],
    queryFn: () =>
      managedGet<unknown>(`organizations/${organizationId}/members?limit=200`).then(
        parseOrganizationMemberPageResponse,
      ),
    enabled: Boolean(organizationId) && isOwner,
  })
  const transferCandidates = (membersQuery.data?.data ?? []).filter(
    (member) =>
      member.user_id !== session.data?.user?.id && normalizeManagedRole(member.role) !== 'owner',
  )

  const updateOrganization = useMutation({
    mutationFn: (variables: { name: string; projectCreationPolicy: string }) =>
      managedPut(`organizations/${organizationId}`, {
        name: variables.name,
        project_creation_policy: variables.projectCreationPolicy,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organization-detail', organizationId] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  const transferOwnership = useMutation({
    mutationFn: (variables: { userId: UserId }) =>
      managedPost(`organizations/${organizationId}/transfer-ownership`, {
        new_owner_user_id: variables.userId,
      }),
    onSuccess: () => {
      setShowTransfer(false)
      setSelectedNewOwnerId(null)
      queryClient.invalidateQueries({ queryKey: ['organization-detail', organizationId] })
      queryClient.invalidateQueries({ queryKey: ['organization-members', organizationId] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => toastOperationError(t, error, 'manage.organization.transferFailed'),
  })

  const deleteOrganization = useMutation({
    mutationFn: () => managedDelete(`organizations/${organizationId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      router.push('/managed/settings')
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  if (!organization) return null

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Card>
        <CardHeader>
          <CardTitle>{t('manage.organization.detail.settingsTitle')}</CardTitle>
          <CardDescription>{t('manage.organization.detail.settingsDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {!canEdit ? (
            <Alert>
              <Info />
              <AlertDescription>
                {t('manage.organization.detail.readOnlySettings')}
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="space-y-2">
            <label htmlFor="organization-name" className="text-sm font-medium">
              {t('manage.organization.name')}
            </label>
            <Input
              id="organization-name"
              value={name}
              onChange={(event) =>
                setDraft({
                  organizationId,
                  name: event.target.value,
                  projectCreationPolicy,
                })
              }
              disabled={!canEdit || updateOrganization.isPending}
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t('manage.organization.projectCreationPolicy')}
            </label>
            {canEdit ? (
              <Select
                value={projectCreationPolicy}
                onValueChange={(value) =>
                  setDraft({
                    organizationId,
                    name,
                    projectCreationPolicy: value as 'admins_only' | 'all_members',
                  })
                }
                disabled={updateOrganization.isPending}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admins_only">
                    {t('manage.organization.projectCreationAdminsOnly')}
                  </SelectItem>
                  <SelectItem value="all_members">
                    {t('manage.organization.projectCreationAllMembers')}
                  </SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <p className="text-sm text-foreground">
                {projectCreationPolicy === 'all_members'
                  ? t('manage.organization.projectCreationAllMembers')
                  : t('manage.organization.projectCreationAdminsOnly')}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {t('manage.organization.projectCreationPolicyHint')}
            </p>
          </div>

          {canEdit ? (
            <Button
              onClick={() =>
                updateOrganization.mutate({
                  name: name.trim(),
                  projectCreationPolicy,
                })
              }
              disabled={!name.trim() || updateOrganization.isPending}
            >
              <Save className="size-4" />
              {updateOrganization.isPending ? t('common.loading') : t('common.save')}
            </Button>
          ) : null}
        </CardContent>
      </Card>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>{t('manage.organization.detail.identityTitle')}</CardTitle>
            <CardDescription>{t('manage.organization.detail.identityDescription')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-4">
              <span className="text-muted-foreground">Slug</span>
              <span className="truncate font-mono text-foreground">{organization.slug}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-muted-foreground">{t('manage.members.role')}</span>
              <span className="text-foreground">{roleLabel(t, organization.role)}</span>
            </div>
          </CardContent>
        </Card>

        {isOwner ? (
          <Card className="border-destructive/30">
            <CardHeader>
              <CardTitle>{t('manage.organization.advanced')}</CardTitle>
              <CardDescription>{t('manage.organization.advancedDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => setShowTransfer(true)}
              >
                <Crown className="size-4" />
                {t('manage.organization.transferOwnership')}
              </Button>
              <div className="space-y-2">
                <Button
                  variant="destructive"
                  className="w-full justify-start"
                  onClick={() => setShowDelete(true)}
                  disabled={isCurrent}
                >
                  <Trash2 className="size-4" />
                  {t('manage.organization.delete')}
                </Button>
                {isCurrent ? (
                  <p className="text-xs text-muted-foreground">
                    {t('manage.organization.detail.deleteCurrentFirst')}
                  </p>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ) : null}
      </div>

      <Dialog open={showTransfer} onOpenChange={setShowTransfer}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.transferOwnership')}</DialogTitle>
            <DialogDescription>{t('manage.organization.transferOwnershipDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {transferCandidates.length ? (
              transferCandidates.map((member) => (
                <button
                  key={member.user_id}
                  type="button"
                  className={`w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted/60 ${selectedNewOwnerId === member.user_id ? 'border-primary bg-muted' : 'border-border'}`}
                  onClick={() => setSelectedNewOwnerId(member.user_id)}
                >
                  <span className="block text-sm font-medium">
                    {member.user_name || member.user_email || member.user_id}
                  </span>
                  {member.user_email ? (
                    <span className="block text-xs text-muted-foreground">{member.user_email}</span>
                  ) : null}
                </button>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                {t('manage.organization.noTransferCandidates')}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowTransfer(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={!selectedNewOwnerId || transferOwnership.isPending}
              onClick={() => {
                if (selectedNewOwnerId) {
                  transferOwnership.mutate({ userId: selectedNewOwnerId })
                }
              }}
            >
              {t('manage.organization.transferOwnership')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showDelete} onOpenChange={setShowDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.delete')}</DialogTitle>
            <DialogDescription>
              {t('manage.organization.deleteConfirm', { name: organization.name })}
            </DialogDescription>
          </DialogHeader>
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertDescription>{t('manage.organization.detail.deleteWarning')}</AlertDescription>
          </Alert>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDelete(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteOrganization.mutate()}
              disabled={deleteOrganization.isPending}
            >
              {t('manage.organization.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
