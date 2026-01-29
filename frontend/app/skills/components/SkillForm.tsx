'use client'

import { ChevronDown } from 'lucide-react'
import { FileText } from 'lucide-react'
import React from 'react'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import { MAX_SKILL_NAME_LENGTH, MAX_SKILL_DESCRIPTION_LENGTH, MAX_COMPATIBILITY_LENGTH } from '@/utils/skillValidators'

import { SkillFormData } from '../schemas/skillFormSchema'


interface SkillFormProps {
  form: UseFormReturn<SkillFormData>
  showAdvancedFields: boolean
  onToggleAdvancedFields: () => void
}

export const SkillForm: React.FC<SkillFormProps> = ({
  form,
  showAdvancedFields,
  onToggleAdvancedFields,
}) => {
  const { t } = useTranslation()
  
  const name = form.watch('name')
  const description = form.watch('description')
  const compatibility = form.watch('compatibility')

  return (
    <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
      <div className="flex items-center gap-2 mb-4">
        <FileText size={16} className="text-emerald-500" />
        <span className="text-xs font-bold text-gray-600">SKILL.md Metadata (YAML Frontmatter)</span>
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
                  <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
                    {t('skills.name') || 'Name'} *
                  </FormLabel>
                  <span className={`text-[10px] ${
                    (name?.length || 0) > MAX_SKILL_NAME_LENGTH 
                      ? 'text-red-500' 
                      : (name?.length || 0) > 50 
                        ? 'text-amber-500' 
                        : 'text-gray-400'
                  }`}>
                    {(name?.length || 0)}/{MAX_SKILL_NAME_LENGTH}
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
                  <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
                    {t('skills.description') || 'Description'} *
                  </FormLabel>
                  <span className={`text-[10px] ${
                    (description?.length || 0) > MAX_SKILL_DESCRIPTION_LENGTH 
                      ? 'text-red-500' 
                      : (description?.length || 0) > 900 
                        ? 'text-amber-500' 
                        : 'text-gray-400'
                  }`}>
                    {(description?.length || 0)}/{MAX_SKILL_DESCRIPTION_LENGTH}
                  </span>
                </div>
                <FormControl>
                  <Textarea
                    {...field}
                    className="min-h-[60px] text-xs resize-none"
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
                <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
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
            className="flex items-center gap-2 text-[10px] text-gray-500 hover:text-gray-700 transition-colors mt-2"
          >
            <ChevronDown 
              size={12} 
              className={`transition-transform ${showAdvancedFields ? 'rotate-180' : ''}`}
            />
            <span>Advanced Options (Agent Skills Spec)</span>
          </button>
          
          {/* Advanced Fields (Collapsible) */}
          {showAdvancedFields && (
            <div className="space-y-4 pt-2 border-t border-gray-200">
              {/* Compatibility Field */}
              <FormField
                control={form.control}
                name="compatibility"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between">
                      <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
                        Compatibility
                        <span className="ml-1 text-gray-400 font-normal">(optional)</span>
                      </FormLabel>
                      <span className={`text-[10px] ${
                        (compatibility?.length || 0) > MAX_COMPATIBILITY_LENGTH 
                          ? 'text-red-500' 
                          : (compatibility?.length || 0) > 450 
                            ? 'text-amber-500' 
                            : 'text-gray-400'
                      }`}>
                        {(compatibility?.length || 0)}/{MAX_COMPATIBILITY_LENGTH}
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
                    <FormDescription className="text-[10px] text-gray-500">
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
                    <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
                      Allowed Tools
                      <span className="ml-1 text-gray-400 font-normal">(optional, experimental)</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        value={field.value?.join(' ') || ''}
                        onChange={(e) => {
                          const value = e.target.value.trim()
                          const tools = value ? value.split(/\s+/).filter(t => t.trim()) : []
                          field.onChange(tools.length > 0 ? tools : [])
                        }}
                        className="h-9 text-xs"
                        placeholder="search read write (space-separated)"
                      />
                    </FormControl>
                    <FormDescription className="text-[10px] text-gray-500">
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
                    <FormLabel className="text-[10px] font-bold text-gray-400 uppercase">
                      Metadata
                      <span className="ml-1 text-gray-400 font-normal">(optional, JSON)</span>
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
                        className="min-h-[80px] text-xs font-mono resize-none"
                        placeholder='{\n  "version": "1.0",\n  "author": "team-name"\n}'
                      />
                    </FormControl>
                    <FormDescription className="text-[10px] text-gray-500">
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
