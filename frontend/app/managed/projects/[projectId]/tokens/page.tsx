import ApiKeysPage from '@/app/managed/api-keys/page'
import { parseProjectId } from '@/types/entity-id'

export default async function ProjectTokensRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ApiKeysPage projectId={parseProjectId(projectId)} />
}
