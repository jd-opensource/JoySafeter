import { ProjectLifecyclePage } from '@/components/managed/projects/project-lifecycle-page'

export default async function ProjectLifecycleRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectLifecyclePage projectId={projectId} />
}
