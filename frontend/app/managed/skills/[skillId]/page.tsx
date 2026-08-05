'use client'

import React from 'react'

import { SkillManagerPageContent } from '../page'

export default function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = React.use(params)
  return <SkillManagerPageContent initialSkillId={skillId} />
}
