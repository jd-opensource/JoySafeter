'use client'

import { Key, Loader2, Trash2, Copy, Check } from 'lucide-react'
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
import { useToast } from '@/components/ui/use-toast'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import {
  usePlatformTokens,
  useRevokeToken,
  type PlatformToken,
  type TokenListParams,
} from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { formatResourceType } from '@/lib/utils/formatResourceType'

interface TokenListProps {
  resourceType?: TokenListParams['resourceType']
  resourceId?: string
  header?: React.ReactNode
}

const getTypeBadgeColor = (type?: string | null) => {
  switch (type) {
    case 'workspace':
      return 'bg-purple-100 text-purple-700 hover:bg-purple-100/80 border-purple-200'
    case 'skill':
      return 'bg-blue-100 text-blue-700 hover:bg-blue-100/80 border-blue-200'
    case 'personal':
    default:
      return 'bg-gray-100 text-gray-700 hover:bg-gray-100/80 border-gray-200'
  }
}

function TokenTableRow({ token, onRevoke, revokingId }: { token: PlatformToken, onRevoke: (t: PlatformToken) => void, revokingId: string | null }) {
  const { t } = useTranslation()
  const { copied, handleCopy } = useCopyToClipboard()

  return (
    <TableRow>
      <TableCell className="font-medium text-gray-900 border-b border-gray-100">
        {token.name}
      </TableCell>
      <TableCell className="border-b border-gray-100">
        <div className="flex items-center gap-2">
          <code className="bg-gray-50 px-2 py-1 rounded text-xs text-gray-600 font-mono border border-gray-100">
            {token.tokenPrefix}...
          </code>
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-gray-400 hover:text-gray-600"
                  onClick={() => handleCopy(token.tokenPrefix)}
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('common.copy', { defaultValue: 'Copy' })}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </TableCell>
      <TableCell className="border-b border-gray-100">
        <Badge variant="outline" className={getTypeBadgeColor(token.resourceType)}>
          {formatResourceType(token.resourceType)}
        </Badge>
      </TableCell>
      <TableCell className="text-gray-500 text-sm border-b border-gray-100">
        {token.createdAt ? new Date(token.createdAt).toLocaleDateString() : '-'}
      </TableCell>
      <TableCell className="text-gray-500 text-sm border-b border-gray-100">
        {token.expiresAt ? new Date(token.expiresAt).toLocaleDateString() : t('settings.tokens.noExpiry', { defaultValue: 'No expiry' })}
      </TableCell>
      <TableCell className="text-right border-b border-gray-100">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onRevoke(token)}
          className="h-8 w-8 text-gray-400 hover:bg-red-50 hover:text-red-600"
          disabled={revokingId === token.id}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
}

export function TokenList({ resourceType, resourceId, header }: TokenListProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const params: TokenListParams | undefined =
    resourceType || resourceId ? { resourceType, resourceId } : undefined
  const { data: tokens, isLoading } = usePlatformTokens(params)
  const revokeToken = useRevokeToken()

  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false)
  const [tokenToRevoke, setTokenToRevoke] = useState<PlatformToken | null>(null)

  const openRevokeDialog = (token: PlatformToken) => {
    setTokenToRevoke(token)
    setRevokeDialogOpen(true)
  }

  const handleRevokeConfirm = async () => {
    if (!tokenToRevoke) return
    try {
      await revokeToken.mutateAsync(tokenToRevoke.id)
      toast({ title: t('settings.tokens.revokedSuccess') })
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error ? error.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    } finally {
      setRevokeDialogOpen(false)
      setTokenToRevoke(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full min-h-[200px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {header}

      {!tokens || tokens.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-200 bg-gray-50/50 py-12">
          <div className="rounded-full border border-gray-200 bg-gray-100 p-4">
             <Key className="h-8 w-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-500">{t('settings.tokens.emptyState')}</p>
        </div>
      ) : (
        <div className="rounded-md border border-gray-200 bg-white shadow-sm">
          <Table>
            <TableHeader>
              <TableRow className="bg-gray-50 hover:bg-gray-50">
                <TableHead className="w-[200px] text-gray-600 font-medium">{t('settings.tokens.name', { defaultValue: '名称' })}</TableHead>
                <TableHead className="text-gray-600 font-medium">{t('settings.tokens.key', { defaultValue: 'Key' })}</TableHead>
                <TableHead className="text-gray-600 font-medium">{t('settings.tokens.type', { defaultValue: '类型' })}</TableHead>
                <TableHead className="text-gray-600 font-medium">{t('settings.tokens.createdAt', { defaultValue: '创建时间' })}</TableHead>
                <TableHead className="text-gray-600 font-medium">{t('settings.tokens.expiresAt', { defaultValue: '过期时间' })}</TableHead>
                <TableHead className="w-[80px] text-right text-gray-600 font-medium">{t('settings.tokens.actions', { defaultValue: '操作' })}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => (
                <TokenTableRow
                  key={token.id}
                  token={token}
                  onRevoke={openRevokeDialog}
                  revokingId={revokeToken.isPending ? tokenToRevoke?.id ?? null : null}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <AlertDialogContent className="rounded-xl border-0 shadow-xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold">
              {t('settings.tokens.revokeConfirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-gray-500">
              {t('settings.tokens.revokeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="rounded-lg">{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeConfirm}
              className="rounded-lg bg-red-600 text-white hover:bg-red-700"
            >
              {revokeToken.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('settings.tokens.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
