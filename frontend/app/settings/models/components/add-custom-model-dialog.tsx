'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateCredential } from '@/hooks/queries/models'
import type { ModelProvider } from '@/types/models'

interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  provider: ModelProvider
}

export function AddCustomModelDialog({ open, onOpenChange, provider }: AddCustomModelDialogProps) {
  const createCredential = useCreateCredential()
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')

  const handleAdd = async () => {
    if (!modelName.trim()) return
    await createCredential.mutateAsync({
      provider_name: provider.provider_name,
      credentials: {
        ...(apiKey ? { api_key: apiKey } : {}),
        ...(baseUrl ? { base_url: baseUrl } : {}),
      },
      model_name: modelName.trim(),
      validate: true,
    })
    setModelName('')
    setBaseUrl('')
    setApiKey('')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>添加自定义模型</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">模型名称</Label>
            <Input
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="例如：gpt-4o, claude-3-5-sonnet"
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm font-medium">API Base URL</Label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm font-medium">API Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              autoComplete="off"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleAdd}
            disabled={createCredential.isPending || !modelName.trim()}
          >
            {createCredential.isPending ? '添加中...' : '添加'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
