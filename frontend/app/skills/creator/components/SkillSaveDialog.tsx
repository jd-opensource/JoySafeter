'use client'

import { Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react'
import React, { useState, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { API_BASE } from '@/lib/api-client'
import { toastSuccess, toastError } from '@/lib/utils/toast'
import { getFilenameFromPath } from '@/services/skillService'

import type { SkillPreviewData } from '../page'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillSaveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  previewData: SkillPreviewData | null
  /** When editing an existing skill, pass its id to PUT instead of POST. */
  editSkillId?: string | null
  /** Called after a successful save with the skill id. */
  onSaved?: (skillId: string) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SkillSaveDialog({
  open,
  onOpenChange,
  previewData,
  editSkillId,
  onSaved,
}: SkillSaveDialogProps) {
  const [name, setName] = useState(previewData?.skill_name || '')
  const [description, setDescription] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Sync name with preview data when dialog opens
  React.useEffect(() => {
    if (open && previewData) {
      setName(previewData.skill_name || '')
      setDescription('')
    }
  }, [open, previewData])

  const handleSave = useCallback(async () => {
    if (!name.trim()) return

    setIsSaving(true)
    try {
      if (!previewData) return

      // previewData.files already contains correct relative paths and content
      // from the preview_skill tool output — use it directly.
      const files = previewData.files.map((f) => ({
        path: f.path,
        file_name: getFilenameFromPath(f.path),
        file_type: f.file_type,
        content: f.content,
        storage_type: 'database' as const,
        storage_key: null,
        size: f.size,
      }))

      const skillMdContent = files.find(f => f.path === 'SKILL.md')?.content
      const effectiveDescription =
        description.trim() || extractDescription(skillMdContent) || name

      const body = {
        name: name.trim(),
        description: effectiveDescription,
        content: skillMdContent || '',
        tags: [],
        is_public: false,
        files,
      }

      const url = editSkillId ? `${API_BASE}/skills/${editSkillId}` : `${API_BASE}/skills`
      const method = editSkillId ? 'PUT' : 'POST'

      const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })

      if (!resp.ok) {
        const errText = await resp.text()
        throw new Error(errText || `HTTP ${resp.status}`)
      }

      const result = await resp.json()
      const skillId = result?.data?.id || result?.id || editSkillId || ''

      toastSuccess(editSkillId ? 'Skill updated successfully' : 'Skill saved to library')
      onOpenChange(false)
      onSaved?.(skillId)
    } catch (err: unknown) {
      console.error('Failed to save skill:', err)
      toastError(err instanceof Error ? err.message : 'Failed to save skill')
    } finally {
      setIsSaving(false)
    }
  }, [previewData, name, description, editSkillId, onOpenChange, onSaved])

  const validation = previewData?.validation
  const hasErrors = !!(validation && !validation.valid)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{editSkillId ? 'Update Skill' : 'Save to Library'}</DialogTitle>
          <DialogDescription>
            {editSkillId
              ? 'Update the existing skill with the generated files.'
              : 'Save the generated skill to your skill library.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Validation status */}
          {validation && (
            <div className="space-y-2">
              {hasErrors && (
                <div className="flex items-start gap-2 rounded-lg bg-[var(--status-error-bg)] p-3 text-sm text-[var(--status-error)]">
                  <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Validation errors:</p>
                    <ul className="ml-4 mt-1 list-disc text-xs">
                      {validation.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              {validation.warnings.length > 0 && (
                <div className="flex items-start gap-2 rounded-lg bg-[var(--status-warning-bg)] p-3 text-sm text-[var(--status-warning)]">
                  <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Warnings:</p>
                    <ul className="ml-4 mt-1 list-disc text-xs">
                      {validation.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              {validation.valid && validation.warnings.length === 0 && (
                <div className="flex items-center gap-2 rounded-lg bg-[var(--status-success-bg)] p-3 text-sm text-[var(--status-success)]">
                  <CheckCircle2 size={16} />
                  <span>All validation checks passed</span>
                </div>
              )}
            </div>
          )}

          {/* Name input */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[var(--text-secondary)]">Skill Name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter skill name"
              disabled={isSaving}
            />
          </div>

          {/* Description input */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[var(--text-secondary)]">
              Description <span className="font-normal text-[var(--text-muted)]">(optional)</span>
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short description of this skill"
              disabled={isSaving}
            />
          </div>

          {/* File count */}
          {previewData && (
            <p className="text-xs text-[var(--text-tertiary)]">
              {previewData.files.length} file{previewData.files.length !== 1 ? 's' : ''} will be saved.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isSaving || !name.trim() || hasErrors}
            className="bg-[var(--skill-brand-600)] text-white hover:bg-[var(--skill-brand-700)]"
          >
            {isSaving ? (
              <>
                <Loader2 size={14} className="mr-1 animate-spin" />
                Saving...
              </>
            ) : editSkillId ? (
              'Update Skill'
            ) : (
              'Save to Library'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract description from SKILL.md YAML frontmatter (simple regex).
 */
function extractDescription(content?: string | null): string {
  if (!content) return ''
  const match = content.match(/^---[\s\S]*?description:\s*(.+?)$/m)
  return match?.[1]?.trim().replace(/^["']|["']$/g, '') || ''
}
