'use client'

import { ChevronDown } from 'lucide-react'
import { FileText } from 'lucide-react'
import { UseFormReturn } from 'react-hook-form'

import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import {
  MAX_SKILL_NAME_LENGTH,
  MAX_SKILL_DESCRIPTION_LENGTH,
  MAX_COMPATIBILITY_LENGTH,
} from '@/utils/skillValidators'

import { SkillFormData } from '../schemas/skillFormSchema'

interface SkillFormProps {
  form: UseFormReturn<SkillFormData>
  showAdvancedFields: boolean
  onToggleAdvancedFields: () => void
}

export function SkillForm({ form, showAdvancedFields, onToggleAdvancedFields }: SkillFormProps) {
  const { t } = useTranslation()

  const name = form.watch('name')
  const description = form.watch('description')
  const compatibility = form.watch('compatibility')

  return (
    <div className="rounded-xl border border-[var(--border-muted)] bg-[var(--surface-1)] p-4">
      <div className="mb-4 flex items-center gap-2">
        <FileText size={16} className="text-[var(--skill-brand)]" />
        <span className="text-xs font-bold text-[var(--text-secondary)]">
          SKILL.md Metadata (YAML Frontmatter)
        </span>
      </div>

      <Form {...form}>
        <div className="grid gap-4">
          {/* Name Field */}
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                    {t('skills.name') || 'Name'} *
                  </FormLabel>
                  <span
                    className={`text-[10px] ${
                      (name?.length || 0) > MAX_SKILL_NAME_LENGTH
                        ? 'text-red-500'
                        : (name?.length || 0) > 50
                          ? 'text-amber-500'
                          : 'text-[var(--text-muted)]'
                    }`}
                  >
                    {name?.length || 0}/{MAX_SKILL_NAME_LENGTH}
                  </span>
                </div>
                <FormControl>
                  <Input
                    {...field}
                    className="h-9 text-xs"
                    placeholder="skill-name (kebab-case recommended)"
                    maxLength={MAX_SKILL_NAME_LENGTH}
                  />
                </FormControl>
                <FormMessage className="text-[10px]" />
              </FormItem>
            )}
          />

          {/* Description Field */}
          <FormField
            control={form.control}
            name="description"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                    {t('skills.description') || 'Description'} *
                  </FormLabel>
                  <span
                    className={`text-[10px] ${
                      (description?.length || 0) > MAX_SKILL_DESCRIPTION_LENGTH
                        ? 'text-red-500'
                        : (description?.length || 0) > 900
                          ? 'text-amber-500'
                          : 'text-[var(--text-muted)]'
                    }`}
                  >
                    {description?.length || 0}/{MAX_SKILL_DESCRIPTION_LENGTH}
                  </span>
                </div>
                <FormControl>
                  <Textarea
                    {...field}
                    className="min-h-[60px] resize-none text-xs"
                    placeholder="Brief description of what this skill does"
                    maxLength={MAX_SKILL_DESCRIPTION_LENGTH}
                  />
                </FormControl>
                <FormMessage className="text-[10px]" />
              </FormItem>
            )}
          />

          {/* License Field */}
          <FormField
            control={form.control}
            name="license"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                  {t('skills.license') || 'License'}
                </FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    value={field.value || ''}
                    className="h-9 text-xs"
                    placeholder="MIT, Apache-2.0, Proprietary, etc."
                  />
                </FormControl>
                <FormMessage className="text-[10px]" />
              </FormItem>
            )}
          />

          {/* Advanced Fields Toggle */}
          <button
            type="button"
            onClick={onToggleAdvancedFields}
            className="mt-2 flex items-center gap-2 text-[10px] text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
          >
            <ChevronDown
              size={12}
              className={`transition-transform ${showAdvancedFields ? 'rotate-180' : ''}`}
            />
            <span>Advanced Options (Agent Skills Spec)</span>
          </button>

          {/* Advanced Fields (Collapsible) */}
          {showAdvancedFields && (
            <div className="space-y-4 border-t border-[var(--border)] pt-2">
              {/* Compatibility Field */}
              <FormField
                control={form.control}
                name="compatibility"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between">
                      <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                        Compatibility
                        <span className="ml-1 font-normal text-[var(--text-muted)]">(optional)</span>
                      </FormLabel>
                      <span
                        className={`text-[10px] ${
                          (compatibility?.length || 0) > MAX_COMPATIBILITY_LENGTH
                            ? 'text-red-500'
                            : (compatibility?.length || 0) > 450
                              ? 'text-amber-500'
                              : 'text-[var(--text-muted)]'
                        }`}
                      >
                        {compatibility?.length || 0}/{MAX_COMPATIBILITY_LENGTH}
                      </span>
                    </div>
                    <FormControl>
                      <Input
                        {...field}
                        value={field.value || ''}
                        className="h-9 text-xs"
                        placeholder="Python 3.8+, Node.js 18+, etc."
                        maxLength={MAX_COMPATIBILITY_LENGTH}
                      />
                    </FormControl>
                    <FormDescription className="text-[10px] text-[var(--text-tertiary)]">
                      Environment requirements (max {MAX_COMPATIBILITY_LENGTH} chars)
                    </FormDescription>
                    <FormMessage className="text-[10px]" />
                  </FormItem>
                )}
              />

              {/* Allowed Tools Field */}
              <FormField
                control={form.control}
                name="allowed_tools"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                      Allowed Tools
                      <span className="ml-1 font-normal text-[var(--text-muted)]">
                        (optional, experimental)
                      </span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        value={field.value?.join(' ') || ''}
                        onChange={(e) => {
                          const value = e.target.value.trim()
                          const tools = value ? value.split(/\s+/).filter((t) => t.trim()) : []
                          field.onChange(tools.length > 0 ? tools : [])
                        }}
                        className="h-9 text-xs"
                        placeholder="search read write (space-separated)"
                      />
                    </FormControl>
                    <FormDescription className="text-[10px] text-[var(--text-tertiary)]">
                      Space-delimited list of pre-approved tools
                    </FormDescription>
                    <FormMessage className="text-[10px]" />
                  </FormItem>
                )}
              />

              {/* Metadata Field (JSON) */}
              <FormField
                control={form.control}
                name="metadata"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-[10px] font-bold uppercase text-[var(--text-muted)]">
                      Metadata
                      <span className="ml-1 font-normal text-[var(--text-muted)]">(optional, JSON)</span>
                    </FormLabel>
                    <FormControl>
                      <Textarea
                        value={field.value ? JSON.stringify(field.value, null, 2) : ''}
                        onChange={(e) => {
                          const value = e.target.value.trim()
                          try {
                            const parsed = value ? JSON.parse(value) : {}
                            if (typeof parsed === 'object' && !Array.isArray(parsed)) {
                              // Ensure all values are strings (per spec)
                              const metadata: Record<string, string> = {}
                              for (const [k, v] of Object.entries(parsed)) {
                                if (typeof k === 'string') {
                                  metadata[k] = String(v)
                                }
                              }
                              field.onChange(Object.keys(metadata).length > 0 ? metadata : {})
                            }
                          } catch {
                            // Invalid JSON, keep as is for now
                          }
                        }}
                        className="min-h-[80px] resize-none font-mono text-xs"
                        placeholder='{\n  "version": "1.0",\n  "author": "team-name"\n}'
                      />
                    </FormControl>
                    <FormDescription className="text-[10px] text-[var(--text-tertiary)]">
                      Key-value pairs (all values must be strings)
                    </FormDescription>
                    <FormMessage className="text-[10px]" />
                  </FormItem>
                )}
              />
            </div>
          )}
        </div>
      </Form>
    </div>
  )
}
