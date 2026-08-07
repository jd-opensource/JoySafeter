'use client'

import React from 'react'

import { parseSkillId } from '@/types/entity-id'

import { SkillManagerPageContent } from '../page'

export default function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId: rawSkillId } = React.use(params)
  const skillId = parseSkillId(rawSkillId)
  return <SkillManagerPageContent initialSkillId={skillId} />
}
