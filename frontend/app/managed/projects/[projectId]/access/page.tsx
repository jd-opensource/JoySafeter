import { ProjectAccessPage } from '@/components/managed/projects/project-access-page'

export default async function ProjectAccessRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectAccessPage projectId={projectId} />
}
