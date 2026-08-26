import { ProjectLifecyclePage } from '@/components/managed/projects/project-lifecycle-page'
import { parseProjectId } from '@/types/entity-id'

export default async function ProjectLifecycleRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectLifecyclePage projectId={parseProjectId(projectId)} />
}
