'use client'

import { X } from 'lucide-react'
import * as React from 'react'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

interface UnifiedDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 对话框最大宽度，默认 max-w-lg */
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl'
  /** 对话框标题 */
  title: React.ReactNode
  /** 对话框描述（可选） */
  description?: React.ReactNode
  /** 标题图标（可选） */
  icon?: React.ReactNode
  /** 图标背景色，默认 bg-blue-50 */
  iconBgColor?: string
  /** 图标颜色，默认 text-blue-600 */
  iconColor?: string
  /** 对话框内容 */
  children: React.ReactNode
  /** Footer 内容（可选） */
  footer?: React.ReactNode
  /** 内容区域的 className */
  contentClassName?: string
  /** 是否显示内容区域背景色，默认 true */
  showContentBg?: boolean
}

const maxWidthClasses = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
  '3xl': 'max-w-3xl',
  '4xl': 'max-w-4xl',
}

export function UnifiedDialog({
  open,
  onOpenChange,
  maxWidth = 'lg',
  title,
  description,
  icon,
  iconBgColor = 'bg-blue-50',
  iconColor = 'text-blue-600',
  children,
  footer,
  contentClassName,
  showContentBg = true,
}: UnifiedDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideCloseButton
        className={cn(
          'flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-2xl',
          maxWidthClasses[maxWidth],
        )}
      >
        {/* Header */}
        <DialogHeader className="flex shrink-0 flex-row items-center justify-between border-b border-[var(--border-muted)] px-6 py-4">
          <div className="flex items-center gap-3 overflow-hidden">
            {icon && (
              <div className={cn('shrink-0 rounded-lg p-2', iconBgColor, iconColor)}>{icon}</div>
            )}
            <div className="flex min-w-0 flex-col">
              <DialogTitle className="text-sm font-bold leading-tight text-[var(--text-primary)]">
                {title}
              </DialogTitle>
              {description && (
                <DialogDescription className="mt-0.5 text-xs text-[var(--text-tertiary)]">
                  {description}
                </DialogDescription>
              )}
            </div>
          </div>
          <button
            onClick={() => onOpenChange(false)}
            className="shrink-0 rounded-full p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-gray-600"
          >
            <X size={16} />
          </button>
        </DialogHeader>

        {/* Content */}
        <div
          className={cn(
            'custom-scrollbar flex-1 space-y-4 overflow-y-auto p-6',
            showContentBg && 'bg-[var(--surface-1)]',
            contentClassName,
          )}
        >
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <DialogFooter className="shrink-0 gap-3 border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] px-6 py-4 sm:gap-3">
            {footer}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** 统一的验证提示框样式 */
interface ValidationBoxProps {
  type: 'error' | 'warning' | 'success' | 'info'
  icon?: React.ReactNode
  title: React.ReactNode
  items?: React.ReactNode[]
  children?: React.ReactNode
}

const validationStyles = {
  error: {
    container: 'bg-red-50 border-red-100',
    title: 'text-red-700',
    list: 'text-red-600',
  },
  warning: {
    container: 'bg-amber-50 border-amber-100',
    title: 'text-amber-700',
    list: 'text-amber-600',
  },
  success: {
    container: 'bg-emerald-50 border-emerald-100',
    title: 'text-emerald-700',
    list: 'text-emerald-600',
  },
  info: {
    container: 'bg-blue-50 border-blue-100',
    title: 'text-blue-700',
    list: 'text-blue-600',
  },
}

export function ValidationBox({ type, icon, title, items, children }: ValidationBoxProps) {
  const styles = validationStyles[type]

  return (
    <div className={cn('rounded-xl border p-4', styles.container)}>
      <div className={cn('flex items-center gap-2 text-sm font-semibold', styles.title)}>
        {icon}
        {title}
      </div>
      {items && items.length > 0 && (
        <ul className={cn('mt-2 list-inside list-disc space-y-1.5 text-xs', styles.list)}>
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
      {children}
    </div>
  )
}

/** 统一的文件列表预览框 */
interface FileListBoxProps {
  title: React.ReactNode
  files: { name: string; size?: number; icon?: React.ReactNode }[]
  maxShow?: number
  moreText?: (count: number) => React.ReactNode
}

export function FileListBox({ title, files, maxShow = 20, moreText }: FileListBoxProps) {
  return (
    <div className="custom-scrollbar max-h-48 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
      <div className="mb-3 text-xs font-semibold text-[var(--text-secondary)]">{title}</div>
      <div className="space-y-2">
        {files.slice(0, maxShow).map((file, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-gray-600">
            {file.icon && <span className="shrink-0 text-[var(--text-muted)]">{file.icon}</span>}
            <span className="truncate font-mono">{file.name}</span>
            {file.size !== undefined && (
              <span className="shrink-0 text-[var(--text-muted)]">({(file.size / 1024).toFixed(1)} KB)</span>
            )}
          </div>
        ))}
        {files.length > maxShow && (
          <div className="pt-1 text-xs text-[var(--text-muted)]">
            {moreText
              ? moreText(files.length - maxShow)
              : `... and ${files.length - maxShow} more files`}
          </div>
        )}
      </div>
    </div>
  )
}

export { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter }
