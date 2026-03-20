import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDate } from 'date-fns'
import { Key, Plus, Copy, Trash2, Loader2, Check, AlertTriangle } from 'lucide-react'
import { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { apiKeyService, type ApiKey } from '@/services/apiKeyService'

interface ApiKeysTableProps {
  workspaceId: string
  containerClassName?: string
}

export function ApiKeysTable({ workspaceId, containerClassName }: ApiKeysTableProps) {
  const queryClient = useQueryClient()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [keyType, setKeyType] = useState<'workspace' | 'personal'>('workspace')
  const [expiresInDays, setExpiresInDays] = useState<string>('90')
  const [deleteKeyId, setDeleteKeyId] = useState<string | null>(null)

  // State for newly created key (shown only once)
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // Fetch API keys
  const { data: apiKeys = [], isLoading } = useQuery<ApiKey[]>({
    queryKey: ['api-keys', workspaceId],
    queryFn: () => apiKeyService.listKeys(workspaceId),
    enabled: !!workspaceId,
  })

  // Create key mutation
  const createMutation = useMutation({
    mutationFn: () =>
      apiKeyService.createKey({
        name: keyName.trim(),
        type: keyType,
        workspaceId: keyType === 'workspace' ? workspaceId : undefined,
        expiresInDays:
          expiresInDays && expiresInDays !== 'never' ? parseInt(expiresInDays) : undefined,
      }),
    onSuccess: (data) => {
      setNewlyCreatedKey(data.key)
      setCreateDialogOpen(false)
      setKeyName('')
      setKeyType('workspace')
      setExpiresInDays('90')
      queryClient.invalidateQueries({ queryKey: ['api-keys', workspaceId] })
      toastSuccess('API Key 创建成功，请立即复制保存！', '创建成功')
    },
    onError: (error: any) => {
      toastError(error?.message || '创建 API Key 失败', '创建失败')
    },
  })

  // Delete key mutation
  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => apiKeyService.deleteKey(keyId),
    onSuccess: () => {
      setDeleteKeyId(null)
      queryClient.invalidateQueries({ queryKey: ['api-keys', workspaceId] })
      toastSuccess('API Key 已删除', '删除成功')
    },
    onError: (error: any) => {
      toastError(error?.message || '删除失败', '删除失败')
    },
  })

  // Copy to clipboard
  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      toastSuccess('已复制到剪贴板')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toastError('复制失败，请手动复制')
    }
  }

  return (
    <div className={`flex flex-col gap-4 ${containerClassName || ''}`}>
      <div className="mt-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">API Keys</h3>
        <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="mr-2 h-4 w-4" />
              Generate New Key
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>生成新的 API Key</DialogTitle>
              <DialogDescription>
                创建一个 API Key 用于通过 OpenAPI 远程调用 Graph。Key 只会显示一次，请妥善保存。
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div>
                <label className="mb-2 block text-xs font-medium text-gray-700">名称</label>
                <Input
                  placeholder="例如：Production Key"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-2 block text-xs font-medium text-gray-700">类型</label>
                <Select value={keyType} onValueChange={(v) => setKeyType(v as any)}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent portal={false}>
                    <SelectItem value="workspace">Workspace（可访问此工作空间的 Graph）</SelectItem>
                    <SelectItem value="personal">Personal（仅个人 Graph）</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-2 block text-xs font-medium text-gray-700">过期时间</label>
                <Select value={expiresInDays} onValueChange={setExpiresInDays}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent portal={false}>
                    <SelectItem value="30">30 天</SelectItem>
                    <SelectItem value="90">90 天</SelectItem>
                    <SelectItem value="180">180 天</SelectItem>
                    <SelectItem value="365">1 年</SelectItem>
                    <SelectItem value="never">永不过期</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
                取消
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending || !keyName.trim()}
              >
                {createMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    生成中...
                  </>
                ) : (
                  <>
                    <Key className="mr-2 h-4 w-4" />
                    生成 Key
                  </>
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* New Key Banner */}
      {newlyCreatedKey && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 transition-all duration-300">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-600" />
            <div className="min-w-0 flex-1">
              <p className="mb-1 text-sm font-semibold text-amber-800">
                请立即复制你的 API Key — 此 Key 不会再次显示！
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 break-all rounded border border-amber-200 bg-white px-3 py-2 font-mono text-xs text-gray-800">
                  {newlyCreatedKey}
                </code>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-shrink-0 border-amber-300 hover:bg-amber-100"
                        onClick={() => handleCopy(newlyCreatedKey)}
                      >
                        {copied ? (
                          <Check className="h-4 w-4 text-green-600" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>复制 Key</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="mt-2 text-xs text-amber-700 hover:text-amber-900"
                onClick={() => setNewlyCreatedKey(null)}
              >
                我已保存，关闭提示
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-200">
        {isLoading ? (
          <div className="flex h-48 items-center justify-center bg-white">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center bg-gray-50/50 text-center">
            <Key className="mb-2 h-10 w-10 text-gray-300" />
            <h3 className="text-sm font-medium text-gray-600">还没有 API Key</h3>
          </div>
        ) : (
          <div className="bg-white">
            <Table>
              <TableHeader>
                <TableRow className="border-b border-gray-100 bg-gray-50/80 hover:bg-gray-50/80">
                  <TableHead className="h-10 text-xs font-medium text-gray-500">名称</TableHead>
                  <TableHead className="h-10 text-xs font-medium text-gray-500">Key</TableHead>
                  <TableHead className="h-10 text-xs font-medium text-gray-500">类型</TableHead>
                  <TableHead className="h-10 text-xs font-medium text-gray-500">创建时间</TableHead>
                  <TableHead className="h-10 text-xs font-medium text-gray-500">过期时间</TableHead>
                  <TableHead className="h-10 w-[60px] text-right text-xs font-medium text-gray-500">
                    操作
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {apiKeys.map((apiKey) => (
                  <TableRow
                    key={apiKey.id}
                    className="border-b border-gray-50 transition-colors last:border-0 hover:bg-gray-50/50"
                  >
                    <TableCell className="py-2">
                      <div className="flex items-center gap-2">
                        <Key className="h-3.5 w-3.5 text-gray-400" />
                        <span className="text-xs font-medium text-gray-900">{apiKey.name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="py-2">
                      <div className="flex items-center gap-1.5">
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600">
                          {apiKey.keyMasked}
                        </code>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-5 w-5 p-0 text-gray-400 hover:text-gray-600"
                                onClick={() => handleCopy(apiKey.key)}
                              >
                                <Copy className="h-3 w-3" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>复制 Key</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </div>
                    </TableCell>
                    <TableCell className="py-2">
                      <Badge
                        variant="secondary"
                        className={
                          apiKey.type === 'workspace'
                            ? 'border-purple-200 bg-purple-100 px-1.5 py-0 text-[10px] text-purple-800'
                            : 'border-blue-200 bg-blue-100 px-1.5 py-0 text-[10px] text-blue-800'
                        }
                      >
                        {apiKey.type === 'workspace' ? 'Workspace' : 'Personal'}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2">
                      <span className="text-[11px] text-gray-600">
                        {apiKey.createdAt
                          ? formatDate(new Date(apiKey.createdAt), 'yyyy-MM-dd')
                          : '-'}
                      </span>
                    </TableCell>
                    <TableCell className="py-2">
                      <span className="text-[11px] text-gray-600">
                        {apiKey.expiresAt
                          ? formatDate(new Date(apiKey.expiresAt), 'yyyy-MM-dd')
                          : '永不过期'}
                      </span>
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 w-6 p-0 hover:bg-red-50 hover:text-red-600"
                              onClick={() => setDeleteKeyId(apiKey.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>删除 Key</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Delete confirmation */}
      <AlertDialog open={!!deleteKeyId} onOpenChange={(open) => !open && setDeleteKeyId(null)}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除 API Key？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后，使用此 Key 的所有请求将立即失效。此操作不可撤消。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteKeyId(null)}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteKeyId) deleteMutation.mutate(deleteKeyId)
              }}
              className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
