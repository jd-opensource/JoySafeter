'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Edit3, KeyRound, Plus, Search, ShieldCheck, Trash2, X } from 'lucide-react'
import type {
  ProjectRecord,
  StorageMountAudit,
  StorageOrganizationGrant,
  StorageProjectGrant,
  StorageVolume,
} from '@/types/managed'
import { parseStorageMountAuditId, type StorageVolumeId } from '@/types/entity-id'
import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { apiResourceId } from '@/lib/managed/api-paths'
import {
  parseStorageMountAuditResponse,
  parseStorageOrganizationGrantResponse,
  parseStorageProjectGrantResponse,
  parseStorageVolumeListResponse,
  parseStorageVolumeResponse,
} from '@/lib/managed/storage-mount-response-parsers'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'
import { useSession } from '@/lib/auth/auth-client'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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

const BACKEND_TYPES = [
  'generic',
  'cubefs',
  'cephfs',
  'nfs',
  'juicefs',
  'lustre',
  'pvc',
  'host_path',
]

type AccessMode = 'read_only' | 'read_write'
type VolumeFormMode = 'create' | 'edit'
type StorageRuntimeMode = 'docker' | 'k8s'

interface VolumeFormState {
  id?: StorageVolumeId
  mode: VolumeFormMode
  volumeRef: string
  backendType: string
  displayName: string
  description: string
  maxAccess: AccessMode
  allowedPrefixes: string
  runtimeMode: StorageRuntimeMode
  dockerHostPath: string
  k8sNamespace: string
  k8sPvc: string
  enabled: boolean
}

interface GrantFormState {
  orgId: string
  projectId: string
  maxAccess: AccessMode
  allowedPrefixes: string
  enabled: boolean
}

interface PlatformOrganization {
  id: string
  name: string
  slug: string
  member_count?: number
  project_count?: number
  member_emails?: string[]
}

interface SearchSelectOption {
  value: string
  label: string
  description?: string
  group?: string
  badge?: string
  searchText?: string
}

interface SimpleSelectOption {
  value: string
  label: string
}

type CollectionResponse<T> = T[] | { data?: T[] | null }

function collectionData<T>(value: CollectionResponse<T> | null | undefined): T[] {
  if (Array.isArray(value)) return value
  return Array.isArray(value?.data) ? value.data : []
}

const emptyVolumeForm = (mode: VolumeFormMode = 'create'): VolumeFormState => ({
  mode,
  volumeRef: '',
  backendType: 'cubefs',
  displayName: '',
  description: '',
  maxAccess: 'read_only',
  allowedPrefixes: '',
  runtimeMode: 'docker',
  dockerHostPath: '',
  k8sNamespace: 'joysafeter-sandboxes',
  k8sPvc: '',
  enabled: true,
})

const emptyGrantForm = (): GrantFormState => ({
  orgId: '',
  projectId: '',
  maxAccess: 'read_only',
  allowedPrefixes: '',
  enabled: true,
})

function splitLines(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinLines(value?: string[]) {
  return (value || []).join(', ')
}

function formatBytes(value?: number | null) {
  if (value == null) return '-'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB', 'PB']
  let size = value / 1024
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

function SearchableGroupedSelect({
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyText,
  options,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  searchPlaceholder: string
  emptyText: string
  options: SearchSelectOption[]
  disabled?: boolean
}) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return options
    return options.filter((option) =>
      `${option.label} ${option.description || ''} ${option.searchText || ''}`
        .toLowerCase()
        .includes(query),
    )
  }, [options, search])
  const groups = useMemo(() => {
    const map = new Map<string, SearchSelectOption[]>()
    for (const option of filtered) {
      const group = option.group || '其他'
      map.set(group, [...(map.get(group) || []), option])
    }
    return Array.from(map.entries())
  }, [filtered])
  const palette = ['bg-purple-500', 'bg-blue-500', 'bg-emerald-500', 'bg-slate-500']

  return (
    <Select value={value || undefined} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-80">
        <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={searchPlaceholder}
              className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch('')}
                onMouseDown={(event) => event.preventDefault()}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>
        {!groups.length ? (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">{emptyText}</div>
        ) : (
          groups.map(([group, items], groupIndex) => (
            <SelectGroup key={group}>
              <SelectLabel className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                <span
                  className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[8px] font-bold text-white ${palette[groupIndex % palette.length]}`}
                >
                  {group.charAt(0).toUpperCase()}
                </span>
                {group}
                <span className="text-[10px] font-normal text-muted-foreground/60">
                  {items.length}
                </span>
              </SelectLabel>
              {items.map((option, optionIndex) => (
                <SelectItem key={option.value} value={option.value}>
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="w-3 shrink-0 text-[11px] text-muted-foreground/40">
                      {optionIndex === items.length - 1 ? '└' : '├'}
                    </span>
                    <span className="min-w-0 truncate">{option.label}</span>
                    {option.badge ? (
                      <span className="shrink-0 text-[10px] text-muted-foreground/60">
                        {option.badge}
                      </span>
                    ) : null}
                  </span>
                </SelectItem>
              ))}
            </SelectGroup>
          ))
        )}
      </SelectContent>
    </Select>
  )
}

function SimpleStyledSelect({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  options: SimpleSelectOption[]
}) {
  return (
    <Select value={value || undefined} onValueChange={onChange}>
      <SelectTrigger>
        <SelectValue placeholder={placeholder || '请选择'} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function volumeToForm(volume: StorageVolume): VolumeFormState {
  const dockerHostPath = typeof volume.docker?.host_path === 'string' ? volume.docker.host_path : ''
  const k8sPvc = typeof volume.k8s?.pvc === 'string' ? volume.k8s.pvc : ''
  return {
    mode: 'edit',
    id: volume.id,
    volumeRef: volume.volume_ref,
    backendType: volume.backend_type || 'generic',
    displayName: volume.display_name,
    description: volume.description || '',
    maxAccess: volume.max_access === 'read_write' ? 'read_write' : 'read_only',
    allowedPrefixes: joinLines(volume.allowed_prefixes),
    runtimeMode: k8sPvc && !dockerHostPath ? 'k8s' : 'docker',
    dockerHostPath,
    k8sNamespace:
      typeof volume.k8s?.namespace === 'string' ? volume.k8s.namespace : 'joysafeter-sandboxes',
    k8sPvc,
    enabled: volume.enabled,
  }
}

function projectGrantToForm(grant?: StorageProjectGrant): GrantFormState {
  if (!grant) return emptyGrantForm()
  return {
    orgId: '',
    projectId: grant.project_id,
    maxAccess: grant.max_access === 'read_write' ? 'read_write' : 'read_only',
    allowedPrefixes: joinLines(grant.allowed_prefixes),
    enabled: grant.enabled,
  }
}

function organizationGrantToForm(grant?: StorageOrganizationGrant): GrantFormState {
  if (!grant) return emptyGrantForm()
  return {
    orgId: grant.org_id,
    projectId: '',
    maxAccess: grant.max_access === 'read_write' ? 'read_write' : 'read_only',
    allowedPrefixes: joinLines(grant.allowed_prefixes),
    enabled: grant.enabled,
  }
}

function defaultGrantFormForProject(projectId?: string | null): GrantFormState {
  return { ...emptyGrantForm(), projectId: projectId || '' }
}

function currentProjectGrant(volume: StorageVolume, projectId?: string | null) {
  return projectId ? volume.grants?.find((item) => item.project_id === projectId) : undefined
}

function buildVolumePayload(form: VolumeFormState) {
  const docker =
    form.runtimeMode === 'docker' && form.dockerHostPath.trim()
      ? { host_path: form.dockerHostPath.trim() }
      : {}
  const k8s =
    form.runtimeMode === 'k8s' && form.k8sPvc.trim()
      ? { namespace: form.k8sNamespace.trim(), pvc: form.k8sPvc.trim() }
      : {}
  const payload: Record<string, unknown> = {
    backend_type: form.backendType.trim() || 'generic',
    display_name: form.displayName.trim(),
    description: form.description.trim(),
    max_access: form.maxAccess,
    allowed_prefixes: splitLines(form.allowedPrefixes),
    docker,
    k8s,
    enabled: form.enabled,
  }
  if (form.mode === 'create') {
    payload.volume_ref = form.volumeRef.trim()
  }
  return payload
}

function buildGrantPayload(form: GrantFormState) {
  return {
    project_id: form.projectId.trim(),
    max_access: form.maxAccess,
    allowed_prefixes: splitLines(form.allowedPrefixes),
    enabled: form.enabled,
  }
}

function buildOrganizationGrantPayload(form: GrantFormState) {
  return {
    org_id: form.orgId.trim(),
    max_access: form.maxAccess,
    allowed_prefixes: splitLines(form.allowedPrefixes),
    enabled: form.enabled,
  }
}

function grantStatus(volume: StorageVolume, projectId?: string | null) {
  const grant = projectId ? volume.grants?.find((item) => item.project_id === projectId) : undefined
  if (!grant) return '未授权'
  return grant.enabled ? '已授权' : '已禁用'
}

function organizationOptionLabel(org: PlatformOrganization) {
  const name = org.name || org.slug || org.id
  const owner = org.member_emails?.[0]
  const projectText =
    typeof org.project_count === 'number'
      ? `${org.project_count}个项目`
      : `组织：${org.id.slice(0, 8)}`
  const memberText = owner
    ? `${owner}${(org.member_count || 0) > 1 ? ` 等${org.member_count}人` : ''}`
    : org.slug || org.id.slice(0, 8)
  return `${name} · ${memberText} · ${projectText}`
}

export function StorageVolumesPage({ mode }: { mode: 'org' | 'platform' }) {
  const queryClient = useQueryClient()
  const requestScope = useManagedRequestScope()
  const readOnly = useCurrentProjectReadOnly()
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const session = useSession()
  const isPlatformAdmin = Boolean(session.data?.user?.isSuperUser)
  const platformMode = mode === 'platform'
  const canManagePlatformVolumes = platformMode && isPlatformAdmin
  const pageTitle = platformMode ? '存储卷配置' : '数据卷'
  const [volumeForm, setVolumeForm] = useState<VolumeFormState | null>(null)
  const [grantTarget, setGrantTarget] = useState<StorageVolume | null>(null)
  const [grantForm, setGrantForm] = useState<GrantFormState>(emptyGrantForm())
  const [deleteTarget, setDeleteTarget] = useState<StorageVolume | null>(null)
  const [selectedVolume, setSelectedVolume] = useState<StorageVolume | null>(null)

  const volumesQuery = useQuery({
    queryKey: ['storage-volumes', requestScope.key],
    queryFn: () =>
      managedGet<unknown>(
        `/storage-volumes?include_disabled=true${platformMode ? '' : '&scope=organization'}`,
      ).then(parseStorageVolumeListResponse),
  })
  const auditPath = selectedVolume
    ? `/storage-volumes/audit/logs?volume_id=${encodeURIComponent(apiResourceId(selectedVolume.id))}`
    : '/storage-volumes/audit/logs'
  const auditQuery = usePaginatedList<StorageMountAudit>({
    queryKey: 'storage-volumes-audit',
    path: auditPath,
    limit: 25,
    pageSizeOptions: [25, 50, 100],
    parseItem: parseStorageMountAuditResponse,
    parseCursor: parseStorageMountAuditId,
  })
  const projectsQuery = useQuery({
    queryKey: ['storage-volumes-projects', requestScope.key],
    queryFn: () => managedGet<CollectionResponse<ProjectRecord>>('/auth/projects'),
  })
  const organizationsQuery = useQuery({
    queryKey: ['platform-organizations', requestScope.key],
    queryFn: () =>
      managedGet<CollectionResponse<PlatformOrganization>>(
        '/auth/platform/organizations?limit=500',
      ),
    enabled: platformMode && isPlatformAdmin,
  })

  const volumes = collectionData(volumesQuery.data)
  const auditRows = auditQuery.data
  const projects = collectionData(projectsQuery.data)
  const organizations = collectionData(organizationsQuery.data)
  const projectNameById = useMemo(
    () =>
      new Map(projects.map((project) => [project.id, project.name || project.slug || project.id])),
    [projects],
  )
  const auditColumns: Column<StorageMountAudit>[] = [
    {
      key: 'created_at',
      header: '时间',
      render: (row) => <RelativeTime date={row.created_at} />,
    },
    {
      key: 'action',
      header: '动作',
      render: (row) => <span className="font-medium">{row.action}</span>,
    },
    {
      key: 'volume_ref',
      header: 'Volume',
      render: (row) => row.volume_ref || '-',
    },
    {
      key: 'project_id',
      header: '项目',
      render: (row) =>
        row.project_id ? projectNameById.get(row.project_id) || row.project_id : '-',
    },
    {
      key: 'path',
      header: '路径',
      render: (row) => row.mount_path || row.sub_path || '-',
    },
    {
      key: 'result',
      header: '结果',
      render: (row) => row.result,
    },
  ]
  const organizationNameById = useMemo(
    () => new Map(organizations.map((org) => [org.id, organizationOptionLabel(org)])),
    [organizations],
  )
  const volumeOptions = useMemo<SearchSelectOption[]>(
    () =>
      volumes.map((volume) => ({
        value: volume.id,
        label: volume.display_name,
        description: `${volume.volume_ref} · ${volume.backend_type || 'generic'}`,
        group: volume.backend_type || 'generic',
        badge: grantStatus(volume, currentProjectId),
        searchText: `${volume.display_name} ${volume.volume_ref} ${volume.description || ''} ${volume.backend_type || ''}`,
      })),
    [volumes, currentProjectId],
  )
  const organizationOptions = useMemo<SearchSelectOption[]>(
    () =>
      organizations.map((org) => ({
        value: org.id,
        label: organizationOptionLabel(org),
        description: org.slug,
        group: '组织',
        badge: typeof org.project_count === 'number' ? `${org.project_count}项目` : undefined,
        searchText: `${org.name} ${org.slug} ${org.id} ${(org.member_emails || []).join(' ')}`,
      })),
    [organizations],
  )
  const projectOptions = useMemo<SearchSelectOption[]>(
    () =>
      projects.map((project) => ({
        value: project.id,
        label: project.name || project.slug || project.id,
        description: project.slug || project.id,
        group: '项目',
        searchText: `${project.name || ''} ${project.slug || ''} ${project.id}`,
      })),
    [projects],
  )
  const orgGrantableVolumes = volumes.filter(
    (volume) => !currentProjectGrant(volume, currentProjectId),
  )

  const openOrgGrantDialog = (volume?: StorageVolume) => {
    const target = volume || orgGrantableVolumes[0] || volumes[0] || null
    if (!target) return
    const existing = currentProjectGrant(target, currentProjectId)
    setGrantTarget(target)
    setGrantForm(
      existing ? projectGrantToForm(existing) : defaultGrantFormForProject(currentProjectId),
    )
  }

  const invalidateStorage = () => {
    queryClient.invalidateQueries({ queryKey: ['storage-volumes', requestScope.key] })
    queryClient.invalidateQueries({ queryKey: ['storage-volumes-audit', requestScope.key] })
    queryClient.invalidateQueries({ queryKey: ['storage-mount-catalog', requestScope.key] })
  }

  const saveVolumeMutation = useMutation({
    mutationFn: async (form: VolumeFormState) => {
      const payload = buildVolumePayload(form)
      if (form.mode === 'edit' && form.id) {
        return managedPost<unknown>(
          `/storage-volumes/${form.id}`,
          payload,
          managedRequestOptions(requestScope),
        ).then(parseStorageVolumeResponse)
      }
      return managedPost<unknown>(
        '/storage-volumes',
        payload,
        managedRequestOptions(requestScope),
      ).then(parseStorageVolumeResponse)
    },
    onSuccess: () => {
      setVolumeForm(null)
      invalidateStorage()
    },
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const saveGrantMutation = useMutation({
    mutationFn: async ({ volume, form }: { volume: StorageVolume; form: GrantFormState }) => {
      if (platformMode) {
        return managedPost<unknown>(
          `/storage-volumes/${volume.id}/organization-grants`,
          buildOrganizationGrantPayload(form),
          managedRequestOptions(requestScope),
        ).then(parseStorageOrganizationGrantResponse)
      }
      return managedPost<unknown>(
        `/storage-volumes/${volume.id}/grants`,
        buildGrantPayload(form),
        managedRequestOptions(requestScope),
      ).then(parseStorageProjectGrantResponse)
    },
    onSuccess: () => {
      setGrantTarget(null)
      setGrantForm(emptyGrantForm())
      invalidateStorage()
    },
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const deleteGrantMutation = useMutation({
    mutationFn: async ({
      volume,
      projectId,
      orgId,
    }: {
      volume: StorageVolume
      projectId?: string
      orgId?: string
    }) => {
      if (platformMode && orgId) {
        return managedDelete(
          `/storage-volumes/${volume.id}/organization-grants/${encodeURIComponent(orgId)}`,
          managedRequestOptions(requestScope),
        )
      }
      return managedDelete(
        `/storage-volumes/${volume.id}/grants/${encodeURIComponent(projectId || '')}`,
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: invalidateStorage,
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const deleteVolumeMutation = useMutation({
    mutationFn: async (volume: StorageVolume) =>
      managedDelete(`/storage-volumes/${volume.id}`, managedRequestOptions(requestScope)),
    onSuccess: () => {
      setDeleteTarget(null)
      invalidateStorage()
    },
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const toggleVolumeMutation = useMutation({
    mutationFn: async (volume: StorageVolume) =>
      managedPost<unknown>(
        `/storage-volumes/${volume.id}`,
        { enabled: !volume.enabled },
        managedRequestOptions(requestScope),
      ).then(parseStorageVolumeResponse),
    onSuccess: invalidateStorage,
    onError: (err) =>
      toastOperationError({ t: (key: string) => key } as never, err, 'common.operationFailed'),
  })

  const volumeRuntimeMissing = volumeForm
    ? volumeForm.runtimeMode === 'docker'
      ? !volumeForm.dockerHostPath.trim()
      : !volumeForm.k8sPvc.trim()
    : false

  const columns: Column<StorageVolume>[] = [
    {
      key: 'display_name',
      header: platformMode ? '名称' : '平台存储卷',
      render: (volume) => (
        <div className="space-y-1">
          <div className="font-medium">{volume.display_name}</div>
          <div className="text-xs text-muted-foreground">
            {volume.description || volume.volume_ref}
          </div>
        </div>
      ),
    },
    ...(platformMode
      ? [
          {
            key: 'id',
            header: 'ID',
            render: (volume: StorageVolume) => <MonoId id={volume.id} />,
          } satisfies Column<StorageVolume>,
        ]
      : []),
    {
      key: 'backend_type',
      header: '后端',
      render: (volume) => <span className="uppercase">{volume.backend_type || 'generic'}</span>,
    },
    {
      key: 'usage',
      header: '用量',
      render: (volume) => <span className="text-xs">{formatBytes(volume.used_bytes)}</span>,
    },
    {
      key: 'access',
      header: platformMode ? '最大权限' : '可申请权限',
      render: (volume) => (volume.max_access === 'read_write' ? '读写' : '只读'),
    },
    {
      key: 'grants',
      header: platformMode ? '授权组织' : '当前项目授权',
      render: (volume) =>
        platformMode ? (
          <span>{volume.organization_grants?.filter((grant) => grant.enabled).length || 0}</span>
        ) : (
          <span>{grantStatus(volume, currentProjectId)}</span>
        ),
    },
    ...(platformMode
      ? [
          {
            key: 'status',
            header: '状态',
            render: (volume: StorageVolume) => (
              <StatusBadge status={volume.enabled ? 'active' : 'archived'} />
            ),
          } satisfies Column<StorageVolume>,
        ]
      : []),
    {
      key: 'actions',
      header: '操作',
      width: '320px',
      render: (volume) => (
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setSelectedVolume(volume)}>
            审计
          </Button>
          {canManagePlatformVolumes ? (
            <Button
              size="sm"
              variant="outline"
              disabled={readOnly}
              onClick={() => setVolumeForm(volumeToForm(volume))}
            >
              <Edit3 className="mr-1 h-3.5 w-3.5" /> 编辑
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            disabled={readOnly}
            onClick={() => {
              if (!platformMode) {
                openOrgGrantDialog(volume)
                return
              }
              setGrantTarget(volume)
              setGrantForm(emptyGrantForm())
            }}
          >
            <KeyRound className="mr-1 h-3.5 w-3.5" /> 授权
          </Button>
          {canManagePlatformVolumes ? (
            <Button
              size="sm"
              variant="outline"
              disabled={readOnly || toggleVolumeMutation.isPending}
              onClick={() => toggleVolumeMutation.mutate(volume)}
            >
              {volume.enabled ? '禁用' : '启用'}
            </Button>
          ) : null}
          {canManagePlatformVolumes ? (
            <Button
              size="sm"
              variant="destructive"
              disabled={readOnly}
              onClick={() => setDeleteTarget(volume)}
            >
              <Trash2 className="mr-1 h-3.5 w-3.5" /> 删除
            </Button>
          ) : null}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title={pageTitle}
        subtitle={
          platformMode
            ? '平台侧维护底层存储卷：CFS/CubeFS/NFS/PVC 等运行时配置只在这里维护。'
            : '将平台已授权给本组织的存储卷分配给当前项目。'
        }
        action={
          platformMode ? (
            <Button
              size="sm"
              disabled={readOnly || !canManagePlatformVolumes}
              title={canManagePlatformVolumes ? undefined : '只有平台管理员可以新增底层存储卷'}
              onClick={() => setVolumeForm(emptyVolumeForm('create'))}
            >
              <Plus className="mr-2 h-4 w-4" />
              新增存储卷
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={readOnly || !currentProjectId || !volumes.length}
              onClick={() => openOrgGrantDialog()}
            >
              <Plus className="mr-2 h-4 w-4" />
              新增授权
            </Button>
          )
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Database className="h-4 w-4" /> {platformMode ? '存储卷' : '可授权存储卷'}
          </div>
          <div className="mt-2 text-2xl font-semibold">{volumes.length}</div>
          <div className="text-xs text-muted-foreground">
            {platformMode
              ? `${volumes.filter((volume) => volume.enabled).length} 个启用`
              : '平台已发布的存储卷'}
          </div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldCheck className="h-4 w-4" /> {platformMode ? '组织授权' : '当前项目授权'}
          </div>
          <div className="mt-2 text-2xl font-semibold">
            {platformMode
              ? volumes.reduce((sum, volume) => sum + (volume.organization_grants?.length || 0), 0)
              : volumes.filter(
                  (volume) =>
                    currentProjectId &&
                    volume.grants?.some(
                      (grant) => grant.project_id === currentProjectId && grant.enabled,
                    ),
                ).length}
          </div>
          <div className="text-xs text-muted-foreground">
            {platformMode ? '平台授权给组织' : '当前项目已授权'}
          </div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-sm font-medium">{platformMode ? '总用量' : '当前项目可见用量'}</div>
          <div className="mt-2 text-2xl font-semibold">
            {formatBytes(volumes.reduce((sum, volume) => sum + (volume.used_bytes || 0), 0))}
          </div>
          <div className="text-xs text-muted-foreground">由后端 usage collector 更新</div>
        </div>
      </div>

      {!platformMode && !volumes.length ? (
        <div className="rounded-lg border border-dashed bg-muted/30 p-4 text-sm text-muted-foreground">
          当前还没有可授权的存储卷。请先由平台管理员在“平台管理 /
          存储卷配置”中创建底层存储卷，然后这里才能为当前项目配置授权策略。
        </div>
      ) : null}

      {volumesQuery.isError ? (
        <ResourceErrorState error={volumesQuery.error} resource="file" />
      ) : (
        <DataTable
          data={volumes}
          columns={columns}
          loading={volumesQuery.isLoading}
          fetching={volumesQuery.isFetching}
          emptyMessage={
            platformMode ? '暂无存储卷' : '暂无可授权的存储卷，请先由平台管理员创建存储卷配置'
          }
        />
      )}

      <section className="space-y-3 rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">{platformMode ? '挂载审计' : '授权审计'}</h2>
            <p className="text-sm text-muted-foreground">
              {platformMode
                ? '查看 volume、grant、session attach 等存储挂载相关操作。'
                : '查看当前项目的数据卷授权和挂载相关操作。'}
            </p>
          </div>
          {selectedVolume ? (
            <Button size="sm" variant="outline" onClick={() => setSelectedVolume(null)}>
              查看全部
            </Button>
          ) : null}
        </div>
        <div className="text-sm text-muted-foreground">
          当前筛选：
          {selectedVolume ? selectedVolume.display_name : platformMode ? '全部存储卷' : '当前项目'}
        </div>
        <DataTable
          data={auditRows}
          columns={auditColumns}
          loading={auditQuery.isLoading}
          fetching={auditQuery.isFetching}
          pagination={{
            hasNext: auditQuery.hasNext,
            hasPrev: auditQuery.hasPrev,
            page: auditQuery.page,
            pageSize: auditQuery.pageSize,
            pageSizeOptions: auditQuery.pageSizeOptions,
            onNext: auditQuery.goNext,
            onPrev: auditQuery.goPrev,
            onPageChange: auditQuery.goToPage,
            onPageSizeChange: auditQuery.setPageSize,
          }}
          emptyMessage="暂无审计记录"
        />
      </section>

      <Dialog open={!!volumeForm} onOpenChange={(open) => !open && setVolumeForm(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{volumeForm?.mode === 'edit' ? '编辑存储卷' : '新增存储卷'}</DialogTitle>
            <DialogDescription>
              建议一个项目一个独立目录或 PVC，默认只读，沙箱只挂载授权后的 volume_ref。
            </DialogDescription>
          </DialogHeader>
          {volumeForm ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium">Volume Ref</span>
                <Input
                  value={volumeForm.volumeRef}
                  disabled={volumeForm.mode === 'edit'}
                  placeholder="org-a-project-a-assets"
                  onChange={(e) => setVolumeForm({ ...volumeForm, volumeRef: e.target.value })}
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">后端类型</span>
                <SearchableGroupedSelect
                  value={volumeForm.backendType}
                  onChange={(value) => setVolumeForm({ ...volumeForm, backendType: value })}
                  placeholder="选择后端类型"
                  searchPlaceholder="搜索存储后端类型"
                  emptyText="没有匹配的后端类型"
                  options={BACKEND_TYPES.map((type) => ({
                    value: type,
                    label: type,
                    group: type === 'pvc' || type === 'host_path' ? '运行时' : '分布式文件系统',
                    searchText: type,
                  }))}
                />
              </label>
              <label className="space-y-1 text-sm sm:col-span-2">
                <span className="font-medium">显示名称</span>
                <Input
                  value={volumeForm.displayName}
                  placeholder="资产数据"
                  onChange={(e) => setVolumeForm({ ...volumeForm, displayName: e.target.value })}
                />
              </label>
              <label className="space-y-1 text-sm sm:col-span-2">
                <span className="font-medium">描述</span>
                <Input
                  value={volumeForm.description}
                  placeholder="资产平台数据目录"
                  onChange={(e) => setVolumeForm({ ...volumeForm, description: e.target.value })}
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">最大权限</span>
                <SimpleStyledSelect
                  value={volumeForm.maxAccess}
                  onChange={(value) =>
                    setVolumeForm({ ...volumeForm, maxAccess: value as AccessMode })
                  }
                  options={[
                    { value: 'read_only', label: '只读' },
                    { value: 'read_write', label: '读写' },
                  ]}
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">状态</span>
                <SimpleStyledSelect
                  value={volumeForm.enabled ? 'enabled' : 'disabled'}
                  onChange={(value) =>
                    setVolumeForm({ ...volumeForm, enabled: value === 'enabled' })
                  }
                  options={[
                    { value: 'enabled', label: '启用' },
                    { value: 'disabled', label: '禁用' },
                  ]}
                />
              </label>
              <label className="space-y-1 text-sm sm:col-span-2">
                <span className="font-medium">允许前缀</span>
                <Input
                  value={volumeForm.allowedPrefixes}
                  placeholder="强隔离模式下建议留空"
                  onChange={(e) =>
                    setVolumeForm({ ...volumeForm, allowedPrefixes: e.target.value })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  如果 host_path/PVC
                  已经是项目独立目录，建议留空；只有共享大目录才需要填写子目录前缀。
                </p>
              </label>
              <label className="space-y-1 text-sm sm:col-span-2">
                <span className="font-medium">运行时类型</span>
                <SimpleStyledSelect
                  value={volumeForm.runtimeMode}
                  onChange={(value) =>
                    setVolumeForm({ ...volumeForm, runtimeMode: value as StorageRuntimeMode })
                  }
                  options={[
                    { value: 'docker', label: 'Docker 容器' },
                    { value: 'k8s', label: 'Kubernetes PVC' },
                  ]}
                />
                <p className="text-xs text-muted-foreground">
                  Docker 使用平台受控根目录下的项目独立目录；Kubernetes 使用项目独立 PVC。
                </p>
              </label>
              {volumeForm.runtimeMode === 'docker' ? (
                <label className="space-y-1 text-sm sm:col-span-2">
                  <span className="font-medium">Docker 宿主路径</span>
                  <Input
                    value={volumeForm.dockerHostPath}
                    placeholder="/mnt/joysafeter/storage/cubefs/org-a/project-a/assets"
                    onChange={(e) =>
                      setVolumeForm({ ...volumeForm, dockerHostPath: e.target.value })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    默认只允许 /mnt/joysafeter/storage 下的路径；不要配置 CubeFS
                    根目录或多项目共享目录。
                  </p>
                </label>
              ) : (
                <>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">K8s Namespace</span>
                    <Input
                      value={volumeForm.k8sNamespace}
                      onChange={(e) =>
                        setVolumeForm({ ...volumeForm, k8sNamespace: e.target.value })
                      }
                    />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium">K8s PVC</span>
                    <Input
                      value={volumeForm.k8sPvc}
                      placeholder="cubefs-org-a-project-a-assets"
                      onChange={(e) => setVolumeForm({ ...volumeForm, k8sPvc: e.target.value })}
                    />
                  </label>
                </>
              )}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setVolumeForm(null)}>
              取消
            </Button>
            <Button
              disabled={
                saveVolumeMutation.isPending ||
                volumeRuntimeMissing ||
                !volumeForm?.displayName.trim() ||
                (volumeForm.mode === 'create' && !volumeForm.volumeRef.trim())
              }
              onClick={() => volumeForm && saveVolumeMutation.mutate(volumeForm)}
            >
              {saveVolumeMutation.isPending ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!grantTarget} onOpenChange={(open) => !open && setGrantTarget(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{platformMode ? '组织授权' : '项目授权'}</DialogTitle>
            <DialogDescription>
              {platformMode
                ? '平台管理员先把存储卷授权给组织；组织管理员再授权给本组织项目。'
                : '授权项目后，该项目下环境和 session 才能挂载此存储卷。'}
            </DialogDescription>
          </DialogHeader>
          {grantTarget ? (
            <div className="space-y-4">
              <div className="rounded-md border p-3">
                <div className="font-medium">{grantTarget.display_name}</div>
                <div className="text-xs text-muted-foreground">{grantTarget.volume_ref}</div>
              </div>
              {!platformMode ? (
                <label className="space-y-1 text-sm">
                  <span className="font-medium">选择平台存储卷</span>
                  <SearchableGroupedSelect
                    value={grantTarget.id}
                    onChange={(value) => {
                      const nextVolume = volumes.find((volume) => volume.id === value)
                      if (!nextVolume) return
                      const existing = currentProjectGrant(nextVolume, currentProjectId)
                      setGrantTarget(nextVolume)
                      setGrantForm(
                        existing
                          ? projectGrantToForm(existing)
                          : defaultGrantFormForProject(currentProjectId),
                      )
                    }}
                    placeholder="选择平台存储卷"
                    searchPlaceholder="搜索存储卷、volume_ref 或后端"
                    emptyText="没有匹配的存储卷"
                    options={volumeOptions}
                  />
                  <p className="text-xs text-muted-foreground">
                    只能选择平台管理员已发布的存储卷；底层路径和 PVC 不会暴露给项目。
                  </p>
                </label>
              ) : null}
              <div className="grid gap-4 sm:grid-cols-2">
                {platformMode ? (
                  <label className="space-y-1 text-sm sm:col-span-2">
                    <span className="font-medium">组织</span>
                    <SearchableGroupedSelect
                      value={grantForm.orgId}
                      onChange={(value) => {
                        const existing = grantTarget.organization_grants?.find(
                          (grant) => grant.org_id === value,
                        )
                        setGrantForm(
                          existing
                            ? organizationGrantToForm(existing)
                            : { ...emptyGrantForm(), orgId: value },
                        )
                      }}
                      placeholder={
                        organizationsQuery.isLoading
                          ? '正在加载组织...'
                          : organizationsQuery.isError
                            ? '组织加载失败'
                            : organizations.length
                              ? '选择组织'
                              : '暂无可授权组织'
                      }
                      searchPlaceholder="搜索组织、成员邮箱或 ID"
                      emptyText="没有匹配的组织"
                      options={organizationOptions}
                      disabled={
                        organizationsQuery.isLoading ||
                        organizationsQuery.isError ||
                        !organizations.length
                      }
                    />
                    {organizationsQuery.isError ? (
                      <p className="text-xs text-destructive">
                        组织列表加载失败，请确认后端已重启并且当前账号是平台管理员。
                      </p>
                    ) : null}
                  </label>
                ) : (
                  <label className="space-y-1 text-sm sm:col-span-2">
                    <span className="font-medium">项目</span>
                    <SearchableGroupedSelect
                      value={grantForm.projectId}
                      onChange={(value) => {
                        const existing = grantTarget.grants?.find(
                          (grant) => grant.project_id === value,
                        )
                        setGrantForm(
                          existing
                            ? projectGrantToForm(existing)
                            : { ...emptyGrantForm(), projectId: value },
                        )
                      }}
                      placeholder="选择项目"
                      searchPlaceholder="搜索项目名称、slug 或 ID"
                      emptyText="没有匹配的项目"
                      options={projectOptions}
                    />
                    <p className="text-xs text-muted-foreground">只能授权给当前组织内的项目。</p>
                  </label>
                )}
                <label className="space-y-1 text-sm">
                  <span className="font-medium">权限</span>
                  <SimpleStyledSelect
                    value={grantForm.maxAccess}
                    onChange={(value) =>
                      setGrantForm({ ...grantForm, maxAccess: value as AccessMode })
                    }
                    options={[
                      { value: 'read_only', label: '只读' },
                      { value: 'read_write', label: '读写' },
                    ]}
                  />
                </label>
                <label className="space-y-1 text-sm">
                  <span className="font-medium">状态</span>
                  <SimpleStyledSelect
                    value={grantForm.enabled ? 'enabled' : 'disabled'}
                    onChange={(value) =>
                      setGrantForm({ ...grantForm, enabled: value === 'enabled' })
                    }
                    options={[
                      { value: 'enabled', label: '启用' },
                      { value: 'disabled', label: '禁用' },
                    ]}
                  />
                </label>
                <label className="space-y-1 text-sm sm:col-span-2">
                  <span className="font-medium">允许前缀</span>
                  <Input
                    value={grantForm.allowedPrefixes}
                    placeholder="默认继承 volume 前缀"
                    onChange={(e) =>
                      setGrantForm({ ...grantForm, allowedPrefixes: e.target.value })
                    }
                  />
                </label>
              </div>
              {platformMode ? (
                <div className="space-y-2">
                  <div className="text-sm font-medium">已有组织授权</div>
                  <div className="max-h-44 overflow-auto rounded-md border">
                    {(grantTarget.organization_grants || []).map((grant) => (
                      <div
                        key={grant.id}
                        className="flex items-center justify-between gap-3 border-b p-3 last:border-0"
                      >
                        <div>
                          <div className="text-sm font-medium">
                            {organizationNameById.get(grant.org_id) || grant.org_id}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {grant.max_access === 'read_write' ? '读写' : '只读'} ·{' '}
                            {grant.enabled ? '启用' : '禁用'} ·{' '}
                            {joinLines(grant.allowed_prefixes) || '继承 volume 前缀'}
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setGrantForm(organizationGrantToForm(grant))}
                          >
                            编辑
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={deleteGrantMutation.isPending}
                            onClick={() =>
                              deleteGrantMutation.mutate({
                                volume: grantTarget,
                                orgId: grant.org_id,
                              })
                            }
                          >
                            删除
                          </Button>
                        </div>
                      </div>
                    ))}
                    {!grantTarget.organization_grants?.length ? (
                      <div className="p-4 text-sm text-muted-foreground">暂无组织授权</div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantTarget(null)}>
              关闭
            </Button>
            <Button
              disabled={
                saveGrantMutation.isPending ||
                (platformMode ? !grantForm.orgId : !grantForm.projectId)
              }
              onClick={() =>
                grantTarget && saveGrantMutation.mutate({ volume: grantTarget, form: grantForm })
              }
            >
              {saveGrantMutation.isPending ? '保存中...' : '保存授权'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        title="删除存储卷"
        description={`确定删除存储卷「${deleteTarget?.display_name || ''}」吗？如果仍有活动 session 挂载，后端会拒绝删除。`}
        confirmLabel="删除"
        destructive
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && deleteVolumeMutation.mutate(deleteTarget)}
      />
    </div>
  )
}
