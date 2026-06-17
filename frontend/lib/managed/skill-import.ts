import {
  convertFilesToSkillFiles,
  extractRelativePath,
  parseSkillMd,
  processLocalDirectoryFiles,
  type ValidationResult,
} from '@/services/skillService'
import type { SkillFileRecord } from '@/types/managed'

export interface ManagedSkillImportResult {
  valid: boolean
  skillData?: {
    name: string
    description: string
    content: string
    tags: string[]
    license: string
    source_type: string
    files: Array<Pick<SkillFileRecord, 'path' | 'file_name' | 'file_type' | 'content' | 'size'>>
  }
  validation: ValidationResult
  fileCount: number
  rejectedFiles: Array<{ path: string; reason: string }>
}

type ManagedSkillImportApiErrorData = {
  validation_error?: string
  name?: string
  path?: string
  score?: number | null
  severity?: string | null
  recommendation?: string | null
  issues_count?: number
  error_message?: string
  max_files?: number
  max_bytes?: number
  files?: string[]
  total_members?: number
  skipped_directories?: number
  skipped_system_files?: number
  skipped_empty_names?: number
  sample_members?: string[]
  sample_skipped_system_files?: string[]
}

export function getManagedSkillImportErrorMessage(
  errorCode: string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const keyByCode: Record<string, string> = {
    ALL_FILES_REJECTED: 'managed.skills.allFilesBinary',
    'SKILL.md_REQUIRED': 'managed.skills.importSkillMdRequired',
    SKILL_NAME_REQUIRED: 'managed.skills.validationErrors.nameRequired',
    'SKILL.md_BINARY': 'managed.skills.skillMdBinary',
    'SKILL.md_READ_ERROR': 'managed.skills.binaryFileReadError',
  }
  return t(keyByCode[errorCode] || 'managed.skills.importValidationFailed')
}

export async function buildManagedSkillImportFromDirectory(
  fileList: FileList | File[],
): Promise<ManagedSkillImportResult> {
  const filesSnapshot = Array.from(fileList)
  const { files, validation } = await processLocalDirectoryFiles(filesSnapshot)
  const fileCount = files.length

  const { skillFiles, rejectedFiles } = await convertFilesToSkillFiles(files)
  let importableFiles = skillFiles.filter((file) => Boolean(file.content || file.file_name))
  importableFiles = stripCommonImportRoot(importableFiles)

  const skillMdFile = importableFiles.find((file) => file.path === 'SKILL.md')

  if (!validation.valid && !skillMdFile?.content) {
    return {
      valid: false,
      validation,
      fileCount,
      rejectedFiles: validation.rejectedFiles || [],
    }
  }

  if (importableFiles.length === 0) {
    return {
      valid: false,
      validation: {
        ...validation,
        valid: false,
        errors: [...validation.errors, 'ALL_FILES_REJECTED'],
        rejectedFiles,
      },
      fileCount,
      rejectedFiles,
    }
  }

  if (!skillMdFile?.content) {
    return {
      valid: false,
      validation: {
        ...validation,
        valid: false,
        errors: [...validation.errors, 'SKILL.md_REQUIRED'],
        rejectedFiles,
      },
      fileCount,
      rejectedFiles,
    }
  }

  const parsed = parseSkillMd(skillMdFile.content)
  const skillName = normalizeSkillName(parsed.frontmatter.name || getSelectedRootName(fileList))

  return {
    valid: true,
    validation: { ...validation, rejectedFiles },
    fileCount,
    rejectedFiles,
    skillData: {
      name: skillName,
      description: parsed.frontmatter.description || '',
      content: parsed.body || '',
      tags: parsed.frontmatter.tags || [],
      license: parsed.frontmatter.license || '',
      source_type: 'local',
      files: importableFiles.map((file) => ({
        path: file.path === 'SKILL.md' ? '' : file.path.slice(0, -file.file_name.length),
        file_name: file.file_name,
        file_type: file.file_type,
        content: file.content || '',
        size: file.size,
      })),
    },
  }
}

function normalizeSkillName(name: string): string {
  const normalized = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
    .slice(0, 64)
    .replace(/-+$/g, '')
  return normalized || `skill-${Date.now().toString(36)}`
}

function stripCommonImportRoot<T extends { path: string; file_name: string }>(files: T[]): T[] {
  if (files.some((file) => file.path === 'SKILL.md')) {
    return files
  }

  const firstSegments = files
    .map((file) => file.path.split('/').filter(Boolean)[0])
    .filter(Boolean)

  if (firstSegments.length !== files.length) {
    return files
  }

  const commonRoot = firstSegments[0]
  if (!commonRoot || firstSegments.some((segment) => segment !== commonRoot)) {
    return files
  }

  const stripped = files.map((file) => ({
    ...file,
    path: file.path.slice(commonRoot.length + 1),
  }))

  return stripped.some((file) => file.path === 'SKILL.md') ? stripped : files
}

export function getManagedSkillImportValidationMessage(
  validation: ValidationResult,
  fileList: FileList | File[],
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const errors = Array.isArray(validation.errors) ? validation.errors : []
  const firstError = errors[0]
  if (!firstError) {
    const skillMdPath = findSkillMdPath(fileList)
    return skillMdPath
      ? t('managed.skills.importValidationUnknownWithSkillMd', { path: skillMdPath })
      : t('managed.skills.importSkillMdRequiredWithRoot', { folder: getSelectedRootName(fileList) || '-' })
  }

  const selectedRoot = getSelectedRootName(fileList)
  if (firstError.includes('SKILL.md is required')) {
    return selectedRoot
      ? t('managed.skills.importSkillMdRequiredWithRoot', { folder: selectedRoot })
      : t('managed.skills.importSkillMdRequired')
  }
  if (firstError.includes('missing required "name"')) {
    return t('managed.skills.validationErrors.nameRequired')
  }
  if (firstError.includes('missing required "description"')) {
    return t('managed.skills.validationErrors.descriptionRequired')
  }
  if (firstError.startsWith('Total size')) {
    return firstError
  }
  if (firstError.startsWith('File "')) {
    return firstError
  }

  const mapped = getManagedSkillImportErrorMessage(firstError, t)
  return mapped === t('managed.skills.importValidationFailed') ? firstError : mapped
}

export function getManagedSkillImportApiErrorMessage(
  error: unknown,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const apiError = error as {
    code?: string
    message?: string
    payload?: { message?: string; data?: ManagedSkillImportApiErrorData | null }
    data?: ManagedSkillImportApiErrorData | null
  }
  const code = apiError?.code || ''
  const message = apiError?.message || apiError?.payload?.message || ''
  const data = apiError?.data || apiError?.payload?.data || null
  const validationError = apiError?.data?.validation_error || apiError?.payload?.data?.validation_error || ''

  if (code === 'SKILL_SECURITY_SCAN_REJECTED') {
    return t('managed.errors.skillSecurityRejected', {
      score: data?.score ?? '-',
      severity: data?.severity ?? '-',
      recommendation: data?.recommendation ?? '-',
      issues: data?.issues_count ?? 0,
    })
  }

  if (code === 'SKILL_SECURITY_SCAN_FAILED') {
    return t('managed.errors.skillSecurityScanFailed', {
      error: data?.error_message || '',
    })
  }

  const zipKeyByCode: Record<string, string> = {
    SKILL_IMPORT_ZIP_ONLY: 'managed.skills.zipErrors.onlyZip',
    SKILL_IMPORT_ZIP_TOO_LARGE: 'managed.skills.zipErrors.zipTooLarge',
    SKILL_IMPORT_ZIP_INVALID: 'managed.skills.zipErrors.invalidZip',
    SKILL_IMPORT_ZIP_EMPTY: 'managed.skills.zipErrors.emptyZip',
    SKILL_IMPORT_ZIP_TOO_MANY_FILES: 'managed.skills.zipErrors.tooManyFiles',
    SKILL_IMPORT_ZIP_PATH_UNSAFE: 'managed.skills.zipErrors.pathUnsafe',
    SKILL_IMPORT_FILE_TOO_LARGE: 'managed.skills.zipErrors.fileTooLarge',
    SKILL_IMPORT_TOTAL_TOO_LARGE: 'managed.skills.zipErrors.totalTooLarge',
    SKILL_IMPORT_BINARY_FILE: 'managed.skills.zipErrors.binaryFile',
    SKILL_IMPORT_SKILL_MD_REQUIRED: 'managed.skills.importSkillMdRequired',
    SKILL_IMPORT_NAME_REQUIRED: 'managed.skills.validationErrors.nameRequired',
    SKILL_IMPORT_FILES_INVALID: 'managed.skills.zipErrors.invalidFiles',
  }

  if (code === 'SKILL_IMPORT_ZIP_EMPTY' && data) {
    const samples = Array.isArray(data.sample_members) ? data.sample_members.filter(Boolean).join(', ') : ''
    const skippedSystemSamples = Array.isArray(data.sample_skipped_system_files)
      ? data.sample_skipped_system_files.filter(Boolean).join(', ')
      : ''

    return t('managed.skills.zipErrors.emptyZipWithDetails', {
      total: data.total_members ?? 0,
      directories: data.skipped_directories ?? 0,
      systemFiles: data.skipped_system_files ?? 0,
      emptyNames: data.skipped_empty_names ?? 0,
      samples: samples || '-',
      skippedSamples: skippedSystemSamples || '-',
    })
  }

  if (code === 'SKILL_IMPORT_SKILL_MD_REQUIRED' && Array.isArray(data?.files) && data.files.length > 0) {
    return t('managed.skills.zipErrors.skillMdRequiredWithFiles', {
      files: data.files.join(', '),
    })
  }

  if (zipKeyByCode[code]) {
    return t(zipKeyByCode[code], {
      path: data?.path || '',
      maxFiles: data?.max_files || '',
      maxSize: formatBytes(Number(data?.max_bytes || 0)),
      files: Array.isArray(data?.files) ? data.files.join(', ') : '',
    })
  }

  if (code === 'SKILL_NAME_ALREADY_EXISTS') {
    return t('managed.skills.validationErrors.nameExists')
  }
  if (code === 'SKILL_NAME_INVALID' || validationError) {
    if (validationError.includes('name must be lowercase alphanumeric')) {
      return t('managed.skills.validationErrors.nameFormat', {
        name: data?.name || '',
      })
    }
    if (validationError.includes('name is required')) {
      return t('managed.skills.validationErrors.nameRequired')
    }
    return validationError || message || t('managed.skills.validationErrors.generic')
  }

  return message || t('managed.skills.importFailed')
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / 1024 / 1024)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

function getSelectedRootName(fileList: FileList | File[]): string {
  const first = Array.from(fileList)[0]
  const relativePath = first ? first.webkitRelativePath || first.name : ''
  return extractRelativePath(relativePath) ? relativePath.split('/')[0] : ''
}

export function getManagedSkillImportDebugInfo(fileList: FileList | File[]) {
  const files = Array.from(fileList).map((file) => ({
    name: file.name,
    path: file.webkitRelativePath || file.name,
    size: file.size,
    type: file.type,
  }))
  return {
    count: files.length,
    skillMdPath: findSkillMdPath(fileList),
    firstFiles: files.slice(0, 20),
  }
}

function findSkillMdPath(fileList: FileList | File[]): string {
  const file = Array.from(fileList).find((item) => {
    const path = item.webkitRelativePath || item.name
    return path.split('/').pop() === 'SKILL.md'
  })
  return file?.webkitRelativePath || file?.name || ''
}
