import { redirect } from 'next/navigation'

export default async function LegacyProjectMembersRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  redirect(`/managed/projects/${projectId}/access`)
}
