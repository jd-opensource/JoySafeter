'use client'

import {
  ShieldCheck,
  FileText,
  Clock,
  User,
  Scale,
  Copy,
  Eye,
  MoreHorizontal,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { Skill } from '@/types'

interface SkillCardProps {
  skill: Skill
  onView?: (skill: Skill) => void
  onCopy?: (skill: Skill) => void
  isOwner?: boolean
  variant?: 'grid' | 'list'
}

// Format relative time
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 30) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

export function SkillCard({
  skill,
  onView,
  onCopy,
  isOwner = false,
  variant = 'grid',
}: SkillCardProps) {
  const { t } = useTranslation()
  const fileCount = skill.files?.length || 0

  if (variant === 'list') {
    // List variant - similar to Memory page cards
    return (
      <Card className="group flex items-start justify-between border-[var(--border)] bg-[var(--surface-1)] p-4 transition-all hover:border-[var(--skill-brand-200)] hover:shadow-md">
        <div className="flex min-w-0 flex-1 items-start gap-4">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]">
            <ShieldCheck size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2">
              <h3
                className="cursor-default truncate text-sm font-semibold text-[var(--text-primary)]"
                title={skill.name}
              >
                {skill.name}
              </h3>
              {isOwner && (
                <Badge
                  variant="outline"
                  className="border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] px-1.5 py-0 text-xs text-[var(--skill-brand-600)]"
                >
                  {t('skills.yours')}
                </Badge>
              )}
              {skill.license && (
                <Badge
                  variant="outline"
                  className="border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0 text-xs text-[var(--text-muted)]"
                >
                  {skill.license}
                </Badge>
              )}
            </div>
            <p className="mb-2 line-clamp-2 text-xs leading-relaxed text-[var(--text-muted)]">
              {skill.description || t('skills.noDescription')}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {skill.tags && skill.tags.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {skill.tags.slice(0, 3).map((tag, i) => (
                    <Badge
                      key={i}
                      variant="outline"
                      className="border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0 text-xs text-[var(--text-secondary)]"
                    >
                      {tag}
                    </Badge>
                  ))}
                  {skill.tags.length > 3 && (
                    <span className="text-xs text-[var(--text-muted)]">+{skill.tags.length - 3}</span>
                  )}
                </div>
              )}
              <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                <span className="flex items-center gap-1">
                  <FileText size={10} />
                  {fileCount} {t('skills.files')}
                </span>
                <span className="flex items-center gap-1">
                  <Clock size={10} />
                  {formatRelativeTime(skill.updated_at)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-3 text-xs text-[var(--text-secondary)] hover:text-[var(--skill-brand)]"
            onClick={() => onView?.(skill)}
          >
            <Eye size={14} className="mr-1" />
            {t('skills.viewDetails')}
          </Button>
          {!isOwner && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-3 text-xs text-[var(--skill-brand-600)] hover:bg-[var(--skill-brand-50)]"
              onClick={() => onCopy?.(skill)}
            >
              <Copy size={14} className="mr-1" />
              {t('skills.copyToMine')}
            </Button>
          )}
        </div>
      </Card>
    )
  }

  // Grid variant - card style
  return (
    <Card
      className={cn(
        'group relative overflow-hidden border-[var(--border)] bg-[var(--surface-1)]',
        'transition-all duration-200 hover:border-[var(--skill-brand-200)] hover:shadow-lg',
        'flex h-full flex-col',
      )}
    >
      {/* Card content */}
      <div className="flex flex-1 flex-col p-4">
        {/* Header: Icon + Name + License */}
        <div className="mb-3 flex items-start gap-3">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]">
            <ShieldCheck size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3
                className="cursor-default truncate text-sm font-semibold text-[var(--text-primary)]"
                title={skill.name}
              >
                {skill.name}
              </h3>
            </div>
            <div className="mt-0.5 flex items-center gap-2">
              {skill.license && (
                <div className="flex items-center gap-1">
                  <Scale size={10} className="text-[var(--text-muted)]" />
                  <span className="text-xs text-[var(--text-muted)]">{skill.license}</span>
                </div>
              )}
              {isOwner && (
                <Badge
                  variant="outline"
                  className="h-3.5 border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] px-1 py-0 text-2xs text-[var(--skill-brand-600)]"
                >
                  {t('skills.yours')}
                </Badge>
              )}
            </div>
          </div>

          {/* More actions */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-[var(--text-muted)] opacity-0 transition-opacity hover:text-[var(--text-primary)] group-hover:opacity-100 focus-visible:opacity-100"
                aria-label={t('skills.moreOptions', { defaultValue: 'More options' })}
              >
                <MoreHorizontal size={14} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onView?.(skill)}>
                <Eye size={14} className="mr-2" />
                {t('skills.viewDetails')}
              </DropdownMenuItem>
              {!isOwner && (
                <DropdownMenuItem onClick={() => onCopy?.(skill)}>
                  <Copy size={14} className="mr-2" />
                  {t('skills.copyToMine')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Description */}
        <p className="mb-3 line-clamp-2 flex-1 text-xs leading-relaxed text-[var(--text-muted)]">
          {skill.description || t('skills.noDescription')}
        </p>

        {/* Tags */}
        {skill.tags && skill.tags.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {skill.tags.slice(0, 3).map((tag, index) => (
              <Badge
                key={index}
                variant="outline"
                className="border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-2)]"
              >
                {tag}
              </Badge>
            ))}
            {skill.tags.length > 3 && (
              <Badge
                variant="outline"
                className="border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0 text-xs text-[var(--text-muted)]"
              >
                +{skill.tags.length - 3}
              </Badge>
            )}
          </div>
        )}

        {/* Meta info row */}
        <div className="flex items-center gap-3 border-t border-[var(--border)] pt-3 text-xs text-[var(--text-muted)]">
          {skill.owner_id && (
            <div className="flex items-center gap-1">
              <User size={10} />
              <span className="max-w-[60px] truncate">{skill.owner_id.slice(0, 8)}...</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <FileText size={10} />
            <span>
              {fileCount} {t('skills.files')}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Clock size={10} />
            <span>{formatRelativeTime(skill.updated_at)}</span>
          </div>
        </div>
      </div>

      {/* Quick action footer */}
      <div className="flex gap-2 border-t border-[var(--border)] bg-[var(--surface-1)] px-4 py-3">
        <Button
          variant="outline"
          size="sm"
          className="h-8 flex-1 gap-1.5 text-xs hover:bg-[var(--surface-1)]"
          onClick={() => onView?.(skill)}
        >
          <Eye size={12} />
          {t('skills.viewDetails')}
        </Button>
        {!isOwner && (
          <Button
            variant="default"
            size="sm"
            className="h-8 flex-1 gap-1.5 bg-[var(--skill-brand-600)] text-xs hover:bg-[var(--skill-brand-700)]"
            onClick={() => onCopy?.(skill)}
          >
            <Copy size={12} />
            {t('skills.copyToMine')}
          </Button>
        )}
      </div>
    </Card>
  )
}

export default SkillCard
