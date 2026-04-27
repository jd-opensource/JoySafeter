/**
 * Map backend skill validation errors (validators.py / skill_service) to i18n messages.
 * Used when save/import fails with 400 and we show toast description.
 */

import type { TFunction } from 'i18next'

import { ApiError } from '@/lib/api-client'

const GOT_RE = /\(got:\s*['"]([^'"]*)['"]\)/
const NAME_MATCH_DIR_RE =
  /name\s+['"]([^'"]*)['"]\s+must\s+match\s+directory\s+name\s+['"]([^'"]*)['"]/

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
  if (!(error instanceof ApiError)) {
    return ''
  }

  const code = error.code
  const validationError =
    typeof error.data?.validation_error === 'string' ? error.data.validation_error : null

  if (code === 'SKILL_NAME_ALREADY_EXISTS') {
    return t('skills.validationErrors.nameExists')
  }

  if (code !== 'SKILL_NAME_INVALID' || !validationError) {
    return code ? t('skills.validationErrors.generic') : ''
  }

  if (validationError.includes('name is required')) {
    return t('skills.validationErrors.nameRequired')
  }

  if (validationError.includes('name exceeds 64 characters')) {
    const name = extractGot(validationError) ?? '?'
    return t('skills.validationErrors.nameTooLong', { max: 64, name })
  }

  if (validationError.includes('name must be lowercase alphanumeric')) {
    const name = extractGot(validationError) ?? '?'
    return t('skills.validationErrors.nameFormat', { name })
  }

  const nm = extractNameMatchDirectory(validationError)
  if (nm) {
    return t('skills.validationErrors.nameMatchDirectory', {
      name: nm.name,
      directory: nm.directory,
    })
  }

  return t('skills.validationErrors.generic')
}
