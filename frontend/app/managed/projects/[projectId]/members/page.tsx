import { redirect } from 'next/navigation'

import { parseProjectId } from '@/types/entity-id'

export default async function LegacyProjectMembersRoute({
  params,
}: {
  params: Promise<{ projectId: string }>
}) {
  const projectId = parseProjectId((await params).projectId)
  redirect(`/managed/projects/${projectId}/access`)
}
