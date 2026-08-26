import { ProjectOverviewPage } from '@/components/managed/projects/project-overview-page'
import { parseProjectId } from '@/types/entity-id'

export default async function ProjectOverviewRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectOverviewPage projectId={parseProjectId(projectId)} />
}
