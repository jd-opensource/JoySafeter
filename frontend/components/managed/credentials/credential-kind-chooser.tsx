'use client'

import { KeyRound, Lock, Zap } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'

export type CredentialKindChoice = 'model' | 'service' | 'credential-group'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onChoose: (kind: CredentialKindChoice) => void
}

export function CredentialKindChooser({ open, onOpenChange, onChoose }: Props) {
  const { t } = useTranslation()
  const choose = (kind: CredentialKindChoice) => {
    onChoose(kind)
    onOpenChange(false)
  }
  const options: Array<{
    kind: CredentialKindChoice
    icon: typeof Zap
    label: string
    description: string
  }> = [
    {
      kind: 'model',
      icon: Zap,
      label: t('managed.credentials.chooser.model'),
      description: t('managed.credentials.chooser.modelDescription'),
    },
    {
      kind: 'service',
      icon: Lock,
      label: t('managed.credentials.chooser.service'),
      description: t('managed.credentials.chooser.serviceDescription'),
    },
    {
      kind: 'credential-group',
      icon: KeyRound,
      label: t('managed.credentials.chooser.credentialGroup'),
      description: t('managed.credentials.chooser.credentialGroupDescription'),
    },
  ]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('managed.credentials.chooser.title')}</DialogTitle>
          <DialogDescription>{t('managed.credentials.chooser.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          {options.map((o) => (
            <Button
              key={o.kind}
              type="button"
              variant="outline"
              className="h-auto justify-start gap-3 p-4 text-left"
              onClick={() => choose(o.kind)}
            >
              <o.icon className="h-5 w-5 shrink-0" />
              <span className="flex flex-col">
                <span className="font-medium">{o.label}</span>
                <span className="text-xs text-muted-foreground">{o.description}</span>
              </span>
            </Button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
