'use client'

import React from 'react'

import { ResourceErrorState } from '@/components/managed/shared'
import { isEntityId, parseSkillId } from '@/types/entity-id'

import { SkillManagerPageContent } from '../page'

export default function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId: rawSkillId } = React.use(params)
  if (!isEntityId(rawSkillId, 'skill')) {
    return (
      <ResourceErrorState
        resource="skill"
        error={{ status: 404 }}
        onBack={() => window.history.back()}
      />
    )
  }
  const skillId = parseSkillId(rawSkillId)
  return <SkillManagerPageContent initialSkillId={skillId} />
}
