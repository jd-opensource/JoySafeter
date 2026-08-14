import { redirect } from 'next/navigation'

export default async function SecretDetailRedirect({
  params,
}: {
  params: Promise<{ secretId: string }>
}) {
  const { secretId } = await params
  redirect(`/managed/credentials/${secretId}`)
}
