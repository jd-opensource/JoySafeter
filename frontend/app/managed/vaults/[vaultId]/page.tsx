import { redirect } from 'next/navigation'

export default async function VaultDetailRedirect({
  params,
}: {
  params: Promise<{ vaultId: string }>
}) {
  const { vaultId } = await params
  redirect(`/managed/credentials/mcp/${vaultId}`)
}
