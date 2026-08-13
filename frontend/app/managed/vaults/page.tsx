import { redirect } from 'next/navigation'

import { resolveVaultsRedirect } from '@/lib/managed/credential-redirects'

export default async function VaultsRedirect({
  searchParams,
}: {
  searchParams: Promise<{ create?: string }>
}) {
  const { create } = await searchParams
  redirect(resolveVaultsRedirect(create ?? null))
}
