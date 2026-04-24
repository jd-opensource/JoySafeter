'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'

import { Button } from '@/components/ui/button'

export interface SkillPreviewData {
  skill_name: string
  files: Array<{
    path: string
    content: string
    file_type: string
    size: number
  }>
  validation: {
    valid: boolean
    errors: string[]
    warnings: string[]
  }
}

export default function SkillCreatorPage() {
  return (
    <div className="flex h-screen flex-col bg-[var(--bg)]">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-[var(--border-muted)] px-4 py-2.5">
        <Link href="/skills">
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <ArrowLeft size={14} />
            <span className="text-xs">Skills</span>
          </Button>
        </Link>
        <div className="h-4 w-px bg-[var(--border)]" />
        <h1 className="text-sm font-semibold text-[var(--text-primary)]">Create Skill</h1>
      </div>

      <div className="flex flex-1 items-center justify-center text-sm text-[var(--text-muted)]">
        Skill Creator is being migrated to the execution-centric architecture.
      </div>
    </div>
  )
}
