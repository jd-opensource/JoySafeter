import { redirect } from 'next/navigation'

import { resolveSecretsRedirect } from '@/lib/managed/credential-redirects'

export default async function SecretsRedirect({
  searchParams,
}: {
  searchParams: Promise<{ create?: string }>
}) {
  const { create } = await searchParams
  redirect(resolveSecretsRedirect(create ?? null))
}
