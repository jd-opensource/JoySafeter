import type { ReactNode } from 'react'

import { ProjectSettingsShell } from '@/components/managed/projects/project-settings-shell'

export default async function ProjectSettingsLayout({
  children,
  params,
}: {
  children: ReactNode
  params: Promise<{ projectId: string }>
}) {
  const { projectId } = await params
  return <ProjectSettingsShell projectId={projectId}>{children}</ProjectSettingsShell>
}
