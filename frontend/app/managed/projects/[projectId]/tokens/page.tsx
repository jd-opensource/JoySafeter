import ApiKeysPage from '@/app/managed/api-keys/page'

export default async function ProjectTokensRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ApiKeysPage projectId={projectId} />
}
