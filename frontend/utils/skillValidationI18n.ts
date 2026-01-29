/**
 * Map backend skill validation errors (validators.py / skill_service) to i18n messages.
 * Used when save/import fails with 400 and we show toast description.
 */

import type { TFunction } from 'i18next'

import { ApiError } from '@/lib/api-client'

const GOT_RE = /\(got:\s*['"]([^'"]*)['"]\)/
const NAME_MATCH_DIR_RE = /name\s+['"]([^'"]*)['"]\s+must\s+match\s+directory\s+name\s+['"]([^'"]*)['"]/

function extractGot(detail: string): string | undefined {
  const m = detail.match(GOT_RE)
  return m ? m[1] : undefined
}

function extractNameMatchDirectory(detail: string): { name: string; directory: string } | null {
  const m = detail.match(NAME_MATCH_DIR_RE)
  return m ? { name: m[1], directory: m[2] } : null
}

/**
 * Map API error to localized skill validation message.
 * Matches backend strings from validators.py and skill_service.
 *
 * @param error - Caught error (typically ApiError from save/import)
 * @param t - i18n t function
 * @returns Localized message, or empty string if not a skill validation error / no detail
 */
export function getSkillValidationMessage(error: unknown, t: TFunction): string {
  if (!(error instanceof ApiError) || !error.detail) {
    return ''
  }

  const d = error.detail

  if (d.includes('name is required')) {
    return t('skills.validationErrors.nameRequired')
  }

  if (d.includes('name exceeds 64 characters')) {
    const name = extractGot(d) ?? '?'
    return t('skills.validationErrors.nameTooLong', { max: 64, name })
  }

  if (d.includes('name must be lowercase alphanumeric')) {
    const name = extractGot(d) ?? '?'
    return t('skills.validationErrors.nameFormat', { name })
  }

  const nm = extractNameMatchDirectory(d)
  if (nm) {
    return t('skills.validationErrors.nameMatchDirectory', {
      name: nm.name,
      directory: nm.directory,
    })
  }

  if (d.includes('description is required')) {
    return t('skills.validationErrors.descriptionRequired')
  }

  if (d.includes('description exceeds 1024 characters')) {
    return t('skills.validationErrors.descriptionTooLong', { max: 1024 })
  }

  if (d.includes('compatibility exceeds 500 characters')) {
    return t('skills.validationErrors.compatibilityTooLong', { max: 500 })
  }

  if (d.includes('already exists for this owner')) {
    return t('skills.validationErrors.nameExists')
  }

  return t('skills.validationErrors.generic')
}
