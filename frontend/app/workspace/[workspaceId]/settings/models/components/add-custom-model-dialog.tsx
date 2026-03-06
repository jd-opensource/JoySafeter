'use client'

import { Loader2 } from 'lucide-react'
import React, { useState } from 'react'

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
import { Label } from '@/components/ui/label'
import { useCreateModelInstance } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspaceId?: string
}

export function AddCustomModelDialog({
  open,
  onOpenChange,
  workspaceId,
}: AddCustomModelDialogProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const createInstance = useCreateModelInstance()
  const [modelName, setModelName] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = modelName.trim()
    if (!name) {
      toast({
        variant: 'destructive',
        description: t('settings.customModelNameRequired', { defaultValue: '请输入模型名称' }),
      })
      return
    }
    try {
      await createInstance.mutateAsync({
        provider_name: 'custom',
        model_name: name,
        model_type: 'chat',
        workspaceId,
        is_default: false,
      })
      toast({
        variant: 'success',
        description: t('settings.customModelAdded', { defaultValue: '已添加自定义模型' }),
      })
      setModelName('')
      onOpenChange(false)
    } catch (error) {
      toast({
        variant: 'destructive',
        title: t('settings.error'),
        description: error instanceof Error ? error.message : t('settings.failedToAddCustomModel', { defaultValue: '添加失败' }),
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md p-0 gap-0 overflow-hidden bg-white border border-gray-200 rounded-2xl shadow-2xl">
        <DialogHeader className="px-6 py-4 border-b border-gray-100">
          <DialogTitle className="font-bold text-sm">
            {t('settings.addCustomModel', { defaultValue: '添加自定义模型' })}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            {t('settings.addCustomModelDescription', {
              defaultValue: '输入模型名称，例如 gpt-4o-mini、claude-3-5-sonnet、gemini-1.5-flash',
            })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col">
          <div className="px-6 py-4 space-y-4">
            <div>
              <Label htmlFor="custom-model-name">
                {t('settings.modelName', { defaultValue: '模型名称' })}
                <span className="text-destructive ml-1">*</span>
              </Label>
              <Input
                id="custom-model-name"
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="gpt-4o-mini"
                required
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter className="border-t border-gray-100 px-6 py-4 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('settings.cancel')}
            </Button>
            <Button type="submit" disabled={createInstance.isPending || !modelName.trim()}>
              {createInstance.isPending && <Loader2 className="mr-2 w-4 h-4 animate-spin" />}
              {t('settings.add', { defaultValue: '添加' })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
