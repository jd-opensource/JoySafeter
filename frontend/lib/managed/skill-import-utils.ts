/**
 * Client-side utilities for importing skills from a local directory.
 *
 * These functions are pure browser-side helpers (no API calls) — they parse
 * SKILL.md frontmatter, validate the import structure, and convert
 * `FileList` entries into the shape `lib/managed/skill-import.ts` hands to
 * the managed `/api/v1/skills/import-zip` flow.
 *
 * Originally lived alongside an `apiClient`-driven `skillService` object in
 * `frontend/services/skillService.ts`. That object talked to v1/skills and
 * had ~10 dead methods; this file extracts only what `managed/skills/page.tsx`
 * still actually needs.
 */

import type { ImportedSkillFile, SkillFrontmatter, ParsedSkillMd } from '@/types'
import { COMMON_EXTENSIONS, WARNED_EXTENSIONS } from '@/types'

// ---------------------------------------------------------------------------
// SKILL.md parsing
// ---------------------------------------------------------------------------

/**
 * Parse SKILL.md content to extract YAML frontmatter and markdown body.
 *
 * Expected format:
 * ---
 * name: skill-name
 * description: Skill description
 * ---
 *
 * # Markdown content here
 */
export function parseSkillMd(content: string): ParsedSkillMd {
  const normalizedContent = content.replace(/^﻿/, '')
  const defaultResult: ParsedSkillMd = {
    frontmatter: { name: '', description: '' },
    body: normalizedContent || '',
  }

  if (!normalizedContent) {
    return defaultResult
  }

  // Match YAML frontmatter: starts with ---, ends with ---
  const frontmatterRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/
  const match = normalizedContent.match(frontmatterRegex)

  if (!match) {
    return defaultResult
  }

  const yamlContent = match[1]
  const body = normalizedContent.slice(match[0].length)

  // Simple YAML parser for frontmatter (handles basic key: value pairs)
  const frontmatter: SkillFrontmatter = { name: '', description: '' }
  const lines = yamlContent.split('\n')
  let currentKey = ''
  let isMultiline = false
  let multilineValue = ''

  for (const line of lines) {
    // Check for multiline continuation
    if (isMultiline) {
      if (line.startsWith('  ')) {
        multilineValue += (multilineValue ? '\n' : '') + line.slice(2)
        continue
      } else {
        // End of multiline
        ;(frontmatter as Record<string, unknown>)[currentKey] = multilineValue
        isMultiline = false
        multilineValue = ''
      }
    }

    // Parse key: value
    const colonIndex = line.indexOf(':')
    if (colonIndex === -1) continue

    const key = line.slice(0, colonIndex).trim()
    const value = line.slice(colonIndex + 1).trim()

    if (!key) continue

    // Handle multiline values (key: |)
    if (value === '|' || value === '>') {
      currentKey = key
      isMultiline = true
      multilineValue = ''
      continue
    }

    // Handle quoted strings
    let cleanValue = value
    if (
      (cleanValue.startsWith('"') && cleanValue.endsWith('"')) ||
      (cleanValue.startsWith("'") && cleanValue.endsWith("'"))
    ) {
      cleanValue = cleanValue.slice(1, -1)
    }

    // Handle arrays (basic: [a, b, c])
    if (cleanValue.startsWith('[') && cleanValue.endsWith(']')) {
      ;(frontmatter as Record<string, unknown>)[key] = cleanValue
        .slice(1, -1)
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    } else {
      ;(frontmatter as Record<string, unknown>)[key] = cleanValue
    }
  }

  // Finalize any pending multiline value
  if (isMultiline && currentKey) {
    ;(frontmatter as Record<string, unknown>)[currentKey] = multilineValue
  }

  return { frontmatter, body }
}

// ---------------------------------------------------------------------------
// Compliance + system-file rules
// ---------------------------------------------------------------------------

/**
 * Compliance configuration for skill file imports
 */
const COMPLIANCE_CONFIG = {
  maxFileSize: 1024 * 1024, // 1MB per file
  maxTotalSize: 10 * 1024 * 1024, // 10MB total
  allowedExtensions: [
    '.md',
    '.txt',
    '.rst',
    '.py',
    '.js',
    '.ts',
    '.jsx',
    '.tsx',
    '.sh',
    '.bash',
    '.zsh',
    '.json',
    '.yaml',
    '.yml',
    '.toml',
    '.html',
    '.css',
    '.scss',
    '.svg',
    '.xml',
  ],
  requiredFiles: ['SKILL.md'],
}

/**
 * System files that should be automatically filtered (not shown to users)
 */
const SYSTEM_FILES = [
  '.DS_Store', // macOS
  'Thumbs.db', // Windows
  '.gitkeep', // Git
  '.gitignore', // Git
  'desktop.ini', // Windows
  '.Spotlight-V100', // macOS
  '.Trashes', // macOS
  '__MACOSX', // macOS (zip extraction artifact)
]

export interface RejectedFile {
  path: string
  reason: string
}

export interface ValidationResult {
  valid: boolean
  errors: string[]
  warnings: string[]
  rejectedFiles?: RejectedFile[]
}

// ---------------------------------------------------------------------------
// Filename / path helpers
// ---------------------------------------------------------------------------

function getFilenameFromPath(path: string): string {
  if (!path.includes('/')) {
    return path
  }
  return path.split('/').pop() || path
}

function getFileExtension(filename: string): string {
  const lastDot = filename.lastIndexOf('.')
  if (lastDot === -1) return ''
  return filename.slice(lastDot).toLowerCase()
}

function getFileTypeFromExtension(ext: string): string {
  const extMap: Record<string, string> = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.md': 'markdown',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.sh': 'bash',
    '.bash': 'bash',
    '.zsh': 'bash',
    '.html': 'html',
    '.css': 'css',
    '.scss': 'css',
    '.txt': 'text',
    '.rst': 'text',
    '.toml': 'toml',
    '.xml': 'xml',
    '.svg': 'xml',
  }
  return extMap[ext.toLowerCase()] || 'text'
}

function validateFileExtension(path: string): { isCommon: boolean; warning?: string } {
  if (!path) {
    return { isCommon: false, warning: 'File path cannot be empty' }
  }

  const ext = getFileExtension(path)
  if (!ext) {
    return { isCommon: true } // No extension is OK
  }

  if (WARNED_EXTENSIONS.has(ext)) {
    return {
      isCommon: false,
      warning: `File '${path}' has extension '${ext}' which may be binary or unsafe`,
    }
  }

  const isCommon = COMMON_EXTENSIONS.has(ext)
  if (!isCommon) {
    return { isCommon: false, warning: `File '${path}' has uncommon extension '${ext}'` }
  }
  return { isCommon: true }
}

/**
 * Extract relative path from webkitRelativePath (removes root folder name).
 * Used when importing from local directory via browser file picker.
 */
export function extractRelativePath(webkitRelativePath: string): string {
  const parts = webkitRelativePath.split('/')
  // Remove the first part (root folder name) to get the relative path
  return parts.slice(1).join('/')
}

function findCommonSkillImportRoot(relativePaths: string[]): string {
  if (relativePaths.some((path) => path === 'SKILL.md')) return ''

  const firstSegments = relativePaths
    .map((path) => path.split('/').filter(Boolean)[0])
    .filter(Boolean)

  if (firstSegments.length !== relativePaths.length) return ''

  const commonRoot = firstSegments[0]
  if (!commonRoot || firstSegments.some((segment) => segment !== commonRoot)) return ''

  return relativePaths.some((path) => path === `${commonRoot}/SKILL.md`) ? commonRoot : ''
}

function normalizeImportedRelativePath(file: File, commonRoot = ''): string {
  const relativePath = extractRelativePath(file.webkitRelativePath || file.name)
  return commonRoot && relativePath.startsWith(`${commonRoot}/`)
    ? relativePath.slice(commonRoot.length + 1)
    : relativePath
}

function getCommonSkillImportRoot(files: File[]): string {
  return findCommonSkillImportRoot(
    files
      .map((file) => extractRelativePath(file.webkitRelativePath || file.name))
      .filter((path) => {
        const filename = getFilenameFromPath(path) || path
        return Boolean(path) && !isSystemFile(filename)
      }),
  )
}

function isSystemFile(filename: string): boolean {
  const name = filename.toLowerCase()
  if (SYSTEM_FILES.some((sysFile) => name === sysFile.toLowerCase())) {
    return true
  }
  if (name.startsWith('.ds_store') || name.endsWith('.ds_store')) {
    return true
  }
  if (name.includes('__macosx')) {
    return true
  }
  return false
}

function isBinaryFile(content: string): boolean {
  // Check for NULL bytes (0x00)
  if (content.includes('\x00')) {
    return true
  }
  // High ratio of non-printable characters → likely binary.
  const nonPrintableCount = (content.match(/[\x00-\x08\x0E-\x1F\x7F-\x9F]/g) || []).length
  const totalChars = content.length
  if (totalChars > 0 && nonPrintableCount / totalChars > 0.05) {
    return true
  }
  return false
}

function readFileAsText(file: File): Promise<{ content: string; isBinary: boolean }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const content = reader.result as string
      const isBinary = isBinaryFile(content)
      resolve({ content, isBinary })
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file, 'UTF-8')
  })
}

// ---------------------------------------------------------------------------
// File validation
// ---------------------------------------------------------------------------

function validateImportedFiles(files: File[]): ValidationResult {
  const errors: string[] = []
  const warnings: string[] = []
  const rejectedFiles: RejectedFile[] = []
  const commonRoot = getCommonSkillImportRoot(files)

  if (files.length === 0) {
    errors.push('No files selected')
    return { valid: false, errors, warnings, rejectedFiles }
  }

  // Filter out system files first (they won't be counted in validation)
  const validFiles: File[] = []
  for (const file of files) {
    const relativePath = normalizeImportedRelativePath(file, commonRoot)
    const filename = getFilenameFromPath(relativePath) || file.name
    if (isSystemFile(filename)) continue
    validFiles.push(file)
  }

  const totalSize = validFiles.reduce((sum, f) => sum + f.size, 0)
  if (totalSize > COMPLIANCE_CONFIG.maxTotalSize) {
    warnings.push(
      `Total size ${(totalSize / 1024 / 1024).toFixed(2)}MB exceeds limit of ${COMPLIANCE_CONFIG.maxTotalSize / 1024 / 1024}MB`,
    )
  }

  const hasSkillMd = validFiles.some((f) => {
    const relativePath = normalizeImportedRelativePath(f, commonRoot)
    return relativePath === 'SKILL.md'
  })
  if (!hasSkillMd) {
    errors.push('SKILL.md is required but not found in the directory')
  }

  for (const file of validFiles) {
    const relativePath = normalizeImportedRelativePath(file, commonRoot)
    const filename = getFilenameFromPath(relativePath) || file.name
    const ext = getFileExtension(filename)

    if (file.size === 0 && !ext) continue

    if (file.size > COMPLIANCE_CONFIG.maxFileSize) {
      warnings.push(
        `File "${relativePath}" (${(file.size / 1024 / 1024).toFixed(2)}MB) exceeds max size of ${COMPLIANCE_CONFIG.maxFileSize / 1024 / 1024}MB`,
      )
    }

    const extValidation = validateFileExtension(relativePath)
    if (extValidation.warning) {
      warnings.push(extValidation.warning)
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    rejectedFiles,
  }
}

function validateSkillMdContent(content: string): ValidationResult {
  const errors: string[] = []
  const warnings: string[] = []

  const parsed = parseSkillMd(content)

  if (!parsed.frontmatter.name || parsed.frontmatter.name.trim() === '') {
    warnings.push('SKILL.md frontmatter is missing optional "name" field; folder name will be used')
  }

  if (!parsed.frontmatter.description || parsed.frontmatter.description.trim() === '') {
    warnings.push('SKILL.md frontmatter is missing optional "description" field')
  }

  if (!parsed.body || parsed.body.trim() === '') {
    warnings.push('SKILL.md has no content body after frontmatter')
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
}

// ---------------------------------------------------------------------------
// Public entry points used by lib/managed/skill-import.ts
// ---------------------------------------------------------------------------

/**
 * Process files from a local directory selection — validates structure,
 * filters system files, detects binary files, and validates SKILL.md.
 */
export async function processLocalDirectoryFiles(fileList: FileList | File[]): Promise<{
  files: File[]
  validation: ValidationResult
}> {
  const files = Array.from(fileList)
  const commonRoot = getCommonSkillImportRoot(files)

  const validation = validateImportedFiles(files)

  const validFiles = files.filter((file) => {
    const relativePath = normalizeImportedRelativePath(file, commonRoot)
    const filename = getFilenameFromPath(relativePath) || file.name
    return !isSystemFile(filename)
  })

  const rejectedFiles: RejectedFile[] = []
  for (const file of validFiles) {
    const relativePath = normalizeImportedRelativePath(file, commonRoot)
    if (file.size === 0) continue
    try {
      const { isBinary } = await readFileAsText(file)
      if (isBinary) {
        rejectedFiles.push({ path: relativePath, reason: 'binary' })
      }
    } catch (e) {
      rejectedFiles.push({
        path: relativePath,
        reason: `Failed to read file: ${e instanceof Error ? e.message : 'unknown error'}`,
      })
    }
  }

  validation.rejectedFiles = rejectedFiles

  if (!validation.valid) {
    return { files: validFiles, validation }
  }

  const skillMdFile = validFiles.find((f) => {
    const relativePath = normalizeImportedRelativePath(f, commonRoot)
    return relativePath === 'SKILL.md' && !rejectedFiles.some((rf) => rf.path === relativePath)
  })

  if (skillMdFile) {
    try {
      const { content, isBinary } = await readFileAsText(skillMdFile)
      if (isBinary) {
        validation.errors.push('SKILL.md_BINARY')
        validation.valid = false
      } else {
        const contentValidation = validateSkillMdContent(content)
        validation.errors.push(...contentValidation.errors)
        validation.warnings.push(...contentValidation.warnings)
        validation.valid = validation.errors.length === 0
      }
    } catch {
      validation.errors.push('SKILL.md_READ_ERROR')
      validation.valid = false
    }
  }

  return { files: validFiles, validation }
}

/**
 * Convert imported files to the pre-persistence import format.
 */
export async function convertFilesToSkillFiles(
  files: File[],
): Promise<{ skillFiles: ImportedSkillFile[]; rejectedFiles: RejectedFile[] }> {
  const skillFiles: ImportedSkillFile[] = []
  const rejectedFiles: RejectedFile[] = []
  const commonRoot = getCommonSkillImportRoot(files)

  for (const file of files) {
    const relativePath = normalizeImportedRelativePath(file, commonRoot)
    const filename = getFilenameFromPath(relativePath) || file.name
    const ext = getFileExtension(filename)

    if (isSystemFile(filename)) continue
    if (file.size === 0 && !ext) continue

    try {
      const { content, isBinary } = await readFileAsText(file)

      if (isBinary) {
        rejectedFiles.push({ path: relativePath, reason: 'binary' })
        continue
      }

      const fileType = getFileTypeFromExtension(ext)

      skillFiles.push({
        path: relativePath,
        file_name: filename,
        file_type: fileType,
        content,
        size: content.length,
      })
    } catch (e) {
      rejectedFiles.push({ path: relativePath, reason: 'read_error' })
      console.error(`Failed to read file ${relativePath}:`, e)
    }
  }

  return { skillFiles, rejectedFiles }
}
