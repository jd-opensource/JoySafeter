'use client'

import Link from 'next/link'

import { useTranslation } from '@/lib/i18n'
import type {
  CredentialReferenceItem,
  CredentialReferenceResourceType,
  CredentialReferences as CredentialReferencesData,
} from '@/hooks/managed/use-credential-references'

const ROUTE: Record<CredentialReferenceResourceType, string> = {
  agent: '/managed/agents',
  trigger: '/managed/triggers',
  environment: '/managed/environments',
  session: '/managed/sessions',
}

const SURFACE_LABEL_KEY: Record<string, string> = {
  agent_model_binding: 'managed.credentials.references.surfaceAgentModelBinding',
  trigger_webhook_auth: 'managed.credentials.references.surfaceTriggerWebhookAuth',
  environment_injection: 'managed.credentials.references.surfaceEnvironmentInjection',
  active_session_snapshot: 'managed.credentials.references.surfaceActiveSessionSnapshot',
}

export function CredentialReferences({
  data,
  variant,
}: {
  data: CredentialReferencesData
  variant: 'informational' | 'blocker'
}) {
  const { t } = useTranslation()
  if (data.references.length === 0 && data.otherCount === 0) return null

  const groups = new Map<string, CredentialReferenceItem[]>()
  for (const item of data.references) {
    const list = groups.get(item.surface) ?? []
    list.push(item)
    groups.set(item.surface, list)
  }

  const titleKey =
    variant === 'blocker'
      ? 'managed.credentials.references.blockerTitle'
      : 'managed.credentials.references.informationalTitle'

  return (
    <div className="space-y-3 rounded-md border p-3 text-sm">
      <p className="font-medium">{t(titleKey)}</p>
      {[...groups.entries()].map(([surface, items]) => (
        <div key={surface} className="space-y-1">
          <p className="text-muted-foreground">
            {t(SURFACE_LABEL_KEY[surface] ?? surface)} · {items.length}
          </p>
          <ul className="space-y-0.5">
            {items.map((item) => (
              <li key={`${item.resourceType}:${item.id}`}>
                <Link
                  className="text-primary hover:underline"
                  href={`${ROUTE[item.resourceType]}/${item.id}`}
                >
                  {item.name ?? t('managed.credentials.references.sessionFallback', { id: item.id })}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {data.otherCount > 0 && (
        <p className="text-muted-foreground">
          {t('managed.credentials.references.otherCount', { count: data.otherCount })}
        </p>
      )}
    </div>
  )
}
