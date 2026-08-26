import { ProjectAccessPage } from '@/components/managed/projects/project-access-page'
import { parseProjectId } from '@/types/entity-id'

export default async function ProjectAccessRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectAccessPage projectId={parseProjectId(projectId)} />
}
