'use client'

import type { ReactNode } from 'react'

import { CopyButton } from '@/components/managed/shared/copy-button'
import { MonoId } from '@/components/managed/shared/mono-id'
import { useTranslation } from '@/lib/i18n'

interface CredentialIdentityProps {
  name: string
  publicId: string
  subtitle?: ReactNode
  badges?: ReactNode
}

export function CredentialIdentity({ name, publicId, subtitle, badges }: CredentialIdentityProps) {
  const { t } = useTranslation()

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="truncate font-medium text-foreground">{name}</span>
        {badges}
      </div>
      {subtitle ? <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div> : null}
      <div
        className="pointer-events-auto mt-1 flex min-w-0 items-center gap-1"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <MonoId id={publicId} />
        <CopyButton
          value={publicId}
          title={t('managed.credentials.copyPublicId')}
          className="-my-1"
        />
      </div>
    </div>
  )
}
