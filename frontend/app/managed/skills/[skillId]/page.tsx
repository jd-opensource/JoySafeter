'use client'

import React from 'react'

import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseSkillId } from '@/types/entity-id'

import { SkillManagerPageContent } from '../page'

function SkillDetailPageInner({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId: rawSkillId } = React.use(params)
  return <SkillManagerPageContent initialSkillId={parseSkillId(rawSkillId)} />
}

export default withEntityRouteGuard(SkillDetailPageInner, {
  kind: 'skill',
  paramKey: 'skillId',
  backTo: '/managed/skills',
})
