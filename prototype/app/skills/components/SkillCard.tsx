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
    Globe
} from 'lucide-react'
import React from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
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

export const SkillCard: React.FC<SkillCardProps> = ({
    skill,
    onView,
    onCopy,
    isOwner = false,
    variant = 'grid'
}) => {
    const { t } = useTranslation()
    const fileCount = skill.files?.length || 0

    if (variant === 'list') {
        // List variant - similar to Memory page cards
        return (
            <Card className="group flex items-start justify-between p-4 bg-white border-gray-200 hover:shadow-md transition-all hover:border-emerald-200">
                <div className="flex items-start gap-4 flex-1 min-w-0">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center border bg-emerald-50 border-emerald-100 text-emerald-600 flex-shrink-0">
                        <ShieldCheck size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                            <h3 className="text-sm font-semibold text-gray-900 truncate cursor-default" title={skill.name}>{skill.name}</h3>
                            {isOwner && (
                                <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-emerald-50 text-emerald-600 border-emerald-100">
                                    {t('skills.yours')}
                                </Badge>
                            )}
                            {skill.license && (
                                <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-gray-50 text-gray-500 border-gray-200">
                                    {skill.license}
                                </Badge>
                            )}
                        </div>
                        <p className="text-xs text-gray-500 leading-relaxed line-clamp-2 mb-2">
                            {skill.description || t('skills.noDescription')}
                        </p>
                        <div className="flex items-center gap-3 flex-wrap">
                            {skill.tags && skill.tags.length > 0 && (
                                <div className="flex items-center gap-1.5 flex-wrap">
                                    {skill.tags.slice(0, 3).map((tag, i) => (
                                        <Badge
                                            key={i}
                                            variant="outline"
                                            className="text-[9px] px-1.5 py-0 bg-gray-50 text-gray-600 border-gray-200"
                                        >
                                            {tag}
                                        </Badge>
                                    ))}
                                    {skill.tags.length > 3 && (
                                        <span className="text-[9px] text-gray-400">+{skill.tags.length - 3}</span>
                                    )}
                                </div>
                            )}
                            <div className="flex items-center gap-2 text-[10px] text-gray-400">
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
                <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-3 text-xs text-gray-600 hover:text-emerald-600"
                        onClick={() => onView?.(skill)}
                    >
                        <Eye size={14} className="mr-1" />
                        {t('skills.viewDetails')}
                    </Button>
                    {!isOwner && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 px-3 text-xs text-emerald-600 hover:bg-emerald-50"
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
        <Card className={cn(
            "group relative bg-white border-gray-200 overflow-hidden",
            "transition-all duration-200 hover:shadow-lg hover:border-emerald-200",
            "flex flex-col h-full"
        )}>
            {/* Card content */}
            <div className="p-4 flex flex-col flex-1">
                {/* Header: Icon + Name + License */}
                <div className="flex items-start gap-3 mb-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center border bg-emerald-50 border-emerald-100 text-emerald-600 flex-shrink-0">
                        <ShieldCheck size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <h3 className="text-sm font-semibold text-gray-900 truncate cursor-default" title={skill.name}>
                                {skill.name}
                            </h3>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                            {skill.license && (
                                <div className="flex items-center gap-1">
                                    <Scale size={10} className="text-gray-400" />
                                    <span className="text-[10px] text-gray-500">{skill.license}</span>
                                </div>
                            )}
                            {isOwner && (
                                <Badge variant="outline" className="text-[8px] px-1 py-0 h-3.5 bg-emerald-50 text-emerald-600 border-emerald-100">
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
                                className="h-7 w-7 text-gray-400 hover:text-gray-900 opacity-0 group-hover:opacity-100 transition-opacity"
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
                <p className="text-xs text-gray-500 line-clamp-2 mb-3 flex-1 leading-relaxed">
                    {skill.description || t('skills.noDescription')}
                </p>

                {/* Tags */}
                {skill.tags && skill.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                        {skill.tags.slice(0, 3).map((tag, index) => (
                            <Badge
                                key={index}
                                variant="outline"
                                className="text-[9px] px-1.5 py-0 bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100"
                            >
                                {tag}
                            </Badge>
                        ))}
                        {skill.tags.length > 3 && (
                            <Badge
                                variant="outline"
                                className="text-[9px] px-1.5 py-0 bg-gray-50 text-gray-400 border-gray-200"
                            >
                                +{skill.tags.length - 3}
                            </Badge>
                        )}
                    </div>
                )}

                {/* Meta info row */}
                <div className="flex items-center gap-3 text-[10px] text-gray-400 pt-3 border-t border-gray-100">
                    {skill.owner_id && (
                        <div className="flex items-center gap-1">
                            <User size={10} />
                            <span className="truncate max-w-[60px]">
                                {skill.owner_id.slice(0, 8)}...
                            </span>
                        </div>
                    )}
                    <div className="flex items-center gap-1">
                        <FileText size={10} />
                        <span>{fileCount} {t('skills.files')}</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <Clock size={10} />
                        <span>{formatRelativeTime(skill.updated_at)}</span>
                    </div>
                </div>
            </div>

            {/* Quick action footer */}
            <div className="px-4 py-3 bg-gray-50/50 border-t border-gray-100 flex gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 h-8 text-xs gap-1.5 hover:bg-white"
                    onClick={() => onView?.(skill)}
                >
                    <Eye size={12} />
                    {t('skills.viewDetails')}
                </Button>
                {!isOwner && (
                    <Button
                        variant="default"
                        size="sm"
                        className="flex-1 h-8 text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-700"
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
