'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Network, Search } from 'lucide-react'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { parseNetworkPolicyListResponse } from '@/lib/managed/network-policy-response-parsers'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import {
  DataTable,
  MonoId,
  PageHeader,
  RelativeTime,
  ResourceErrorState,
  type Column,
} from '@/components/managed/shared'
import type { NetworkPolicyStatus } from '@/types/managed'

const PAGE_SIZE_OPTIONS = [10, 25, 50]

function shortHash(hash?: string | null) {
  if (!hash) return '-'
  return hash.length > 16 ? `${hash.slice(0, 12)}…` : hash
}

function statusTone(status: string) {
  if (status === 'ready') return 'active'
  if (status === 'nacked' || status === 'failed') return 'failed'
  if (status === 'pending') return 'pending'
  return 'archived'
}

export default function NetworkPolicyDiagnosticsPage() {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')

  const searchParams = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (status !== 'all') params.set('status', status)
    if (query.trim()) params.set('query', query.trim())
    return params.toString()
  }, [page, pageSize, query, status])

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ['network-policy-diagnostics', managedScope.key, searchParams],
    queryFn: () =>
      managedGet<unknown>(
        `network-policies/diagnostics?${searchParams}`,
        managedRequestOptions(managedScope),
      ).then(parseNetworkPolicyListResponse),
  })

  const rows = data?.data ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const columns: Column<NetworkPolicyStatus>[] = useMemo(
    () => [
    {
      key: 'target',
      header: t('managed.networkPolicies.columns.target'),
      render: (row) => (
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Network className="h-3.5 w-3.5 text-muted-foreground" />
            {row.session_title || row.agent_name || t('managed.networkPolicies.untitledSession')}
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>{t('managed.networkPolicies.sandbox')}</span>
            <MonoId id={row.sandbox_id} />
            {row.session_id ? <MonoId id={row.session_id} /> : null}
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      header: t('managed.networkPolicies.columns.status'),
      render: (row) => (
        <Badge
          variant="outline"
          className={
            statusTone(row.networking_status) === 'failed'
              ? 'border-destructive/40 bg-destructive/10 text-destructive'
              : ''
          }
        >
          {row.networking_status}
        </Badge>
      ),
    },
    {
      key: 'policy',
      header: t('managed.networkPolicies.columns.policy'),
      render: (row) => (
        <div className="space-y-1 text-xs">
          <div>v{row.networking_policy_version || 0}</div>
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
            {shortHash(row.networking_policy_hash)}
          </code>
        </div>
      ),
    },
    {
      key: 'health',
      header: t('managed.networkPolicies.columns.health'),
      render: (row) => {
        const errorText =
          row.networking_last_error || row.latest_policy_error || row.latest_policy_nack_reason
        if (!errorText) {
          return (
            <div className="flex items-center gap-1.5 text-sm text-emerald-600">
              <CheckCircle2 className="h-4 w-4" />
              {t('managed.networkPolicies.noError')}
            </div>
          )
        }
        return (
          <div className="max-w-[360px] space-y-1">
            <div className="flex items-center gap-1.5 text-sm font-medium text-destructive">
              <AlertTriangle className="h-4 w-4" />
              {t('managed.networkPolicies.hasError')}
            </div>
            <p className="line-clamp-2 text-xs text-muted-foreground" title={errorText}>
              {errorText}
            </p>
          </div>
        )
      },
    },
    {
      key: 'updated',
      header: t('managed.networkPolicies.columns.updated'),
      render: (row) => (
        <RelativeTime
          date={row.latest_policy_updated_at || row.networking_ready_at || row.sandbox_updated_at}
        />
      ),
    },
    ],
    [t],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title={t('managed.networkPolicies.title')}
        subtitle={t('managed.networkPolicies.subtitle')}
      />
      <div className="grid gap-3 rounded-xl border bg-card p-4 md:grid-cols-[1fr_180px]">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => {
              setPage(1)
              setQuery(event.target.value)
            }}
            placeholder={t('managed.networkPolicies.searchPlaceholder')}
            className="pl-9"
          />
        </div>
        <Select
          value={status}
          onValueChange={(value) => {
            setPage(1)
            setStatus(value)
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('common.all')}</SelectItem>
            <SelectItem value="ready">ready</SelectItem>
            <SelectItem value="pending">pending</SelectItem>
            <SelectItem value="nacked">nacked</SelectItem>
            <SelectItem value="failed">failed</SelectItem>
            <SelectItem value="disabled">disabled</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">{t('managed.networkPolicies.latestStateHint')}</Badge>
        <Badge variant="outline">{t('managed.networkPolicies.failureAuditHint')}</Badge>
      </div>
      {isError ? (
        <ResourceErrorState error={error} resource="project" />
      ) : (
        <DataTable
          data={rows}
          columns={columns}
          loading={isLoading}
          fetching={isFetching}
          emptyMessage={t('managed.networkPolicies.empty')}
          pagination={{
            page,
            pageSize,
            pageSizeOptions: PAGE_SIZE_OPTIONS,
            hasNext: page < totalPages,
            hasPrev: page > 1,
            onNext: () => setPage((value) => Math.min(totalPages, value + 1)),
            onPrev: () => setPage((value) => Math.max(1, value - 1)),
            onPageChange: setPage,
            onPageSizeChange: (size) => {
              setPage(1)
              setPageSize(size)
            },
          }}
        />
      )}
    </div>
  )
}
