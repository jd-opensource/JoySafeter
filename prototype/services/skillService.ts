import { API_BASE, apiGet, apiPost, apiPut, apiDelete, ApiResponse } from '@/lib/api-client';

import {
  Skill,
  SkillFile,
  SkillFrontmatter,
  ParsedSkillMd,
  FileTreeNode,
  COMMON_EXTENSIONS,
  WARNED_EXTENSIONS,
} from '../types';

const SKILLS_ENDPOINT = `${API_BASE}/skills`;

// ============================================================================
// YAML Frontmatter Utilities
// ============================================================================

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
  const defaultResult: ParsedSkillMd = {
    frontmatter: { name: '', description: '' },
    body: content || '',
  };

  if (!content) {
    return defaultResult;
  }

  // Match YAML frontmatter: starts with ---, ends with ---
  const frontmatterRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/;
  const match = content.match(frontmatterRegex);

  if (!match) {
    return defaultResult;
  }

  const yamlContent = match[1];
  const body = content.slice(match[0].length);

  // Simple YAML parser for frontmatter (handles basic key: value pairs)
  const frontmatter: SkillFrontmatter = { name: '', description: '' };
  const lines = yamlContent.split('\n');
  let currentKey = '';
  let isMultiline = false;
  let multilineValue = '';

  for (const line of lines) {
    // Check for multiline continuation
    if (isMultiline) {
      if (line.startsWith('  ')) {
        multilineValue += (multilineValue ? '\n' : '') + line.slice(2);
        continue;
      } else {
        // End of multiline
        (frontmatter as any)[currentKey] = multilineValue;
        isMultiline = false;
        multilineValue = '';
      }
    }

    // Parse key: value
    const colonIndex = line.indexOf(':');
    if (colonIndex === -1) continue;

    const key = line.slice(0, colonIndex).trim();
    let value = line.slice(colonIndex + 1).trim();

    // Check for multiline indicator |
    if (value === '|' || value === '>') {
      currentKey = key;
      isMultiline = true;
      multilineValue = '';
      continue;
    }

    // Handle quoted strings
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    // Handle arrays (simple format: [item1, item2])
    if (value.startsWith('[') && value.endsWith(']')) {
      const arrayContent = value.slice(1, -1);
      (frontmatter as any)[key] = arrayContent
        .split(',')
        .map(item => item.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean);
    } else {
      (frontmatter as any)[key] = value;
    }
  }

  // Handle any remaining multiline content
  if (isMultiline && currentKey) {
    (frontmatter as any)[currentKey] = multilineValue;
  }

  // Post-process frontmatter: handle allowed-tools (space-delimited string per spec)
  if (frontmatter['allowed-tools'] && typeof frontmatter['allowed-tools'] === 'string') {
    // Convert space-delimited string to array
    frontmatter.allowed_tools = (frontmatter['allowed-tools'] as string)
      .split(/\s+/)
      .filter(tool => tool.trim().length > 0);
  } else if (frontmatter.allowed_tools && !Array.isArray(frontmatter.allowed_tools)) {
    // If already an array, ensure it's properly formatted
    frontmatter.allowed_tools = Array.isArray(frontmatter.allowed_tools)
      ? frontmatter.allowed_tools
      : [];
  }

  // Ensure metadata is an object
  if (frontmatter.metadata && typeof frontmatter.metadata !== 'object') {
    try {
      frontmatter.metadata = typeof frontmatter.metadata === 'string'
        ? JSON.parse(frontmatter.metadata)
        : {};
    } catch {
      frontmatter.metadata = {};
    }
  }

  return { frontmatter, body };
}

/**
 * Generate SKILL.md content with YAML frontmatter.
 */
export function generateSkillMd(
  name: string,
  description: string,
  body: string = '',
  additionalFields?: Record<string, any>
): string {
  let frontmatter = `---\nname: ${name}\n`;

  // Handle description - use multiline format if it contains newlines
  if (description.includes('\n')) {
    frontmatter += `description: |\n  ${description.replace(/\n/g, '\n  ')}\n`;
  } else if (description.includes(':') || description.includes('#') || description.includes('"')) {
    // Quote if contains special characters
    frontmatter += `description: "${description.replace(/"/g, '\\"')}"\n`;
  } else {
    frontmatter += `description: ${description}\n`;
  }

  // Add additional fields
  if (additionalFields) {
    for (const [key, value] of Object.entries(additionalFields)) {
      if (value === undefined || value === null) continue;

      // Handle metadata (object -> YAML object)
      if (key === 'metadata' && typeof value === 'object' && !Array.isArray(value)) {
        const metadataObj = value as Record<string, any>;
        if (Object.keys(metadataObj).length > 0) {
          frontmatter += `metadata:\n`;
          for (const [k, v] of Object.entries(metadataObj)) {
            frontmatter += `  ${k}: "${String(v).replace(/"/g, '\\"')}"\n`;
          }
        }
      }
      // Handle arrays (tags, allowed_tools)
      else if (Array.isArray(value)) {
        if (value.length > 0) {
          frontmatter += `${key}: [${value.map(v => `"${v}"`).join(', ')}]\n`;
        }
      }
      // Handle strings (license, compatibility, allowed-tools as space-delimited)
      else if (typeof value === 'string') {
        // Handle multiline strings (compatibility might have newlines)
        if (value.includes('\n')) {
          frontmatter += `${key}: |\n  ${value.replace(/\n/g, '\n  ')}\n`;
        } else if (value.includes(':') || value.includes('#') || value.includes('"')) {
          // Quote if contains special characters
          frontmatter += `${key}: "${value.replace(/"/g, '\\"')}"\n`;
        } else {
          frontmatter += `${key}: ${value}\n`;
        }
      }
      // Handle other types (JSON stringify)
      else {
        frontmatter += `${key}: ${JSON.stringify(value)}\n`;
      }
    }
  }

  frontmatter += '---';

  return body ? `${frontmatter}\n\n${body}` : frontmatter;
}

// ============================================================================
// File Path Utilities
// ============================================================================

/**
 * Check if a file is at root level (not in any subdirectory).
 */
export function isRootLevelFile(path: string): boolean {
  return !path || !path.includes('/');
}

/**
 * Validate file path - just check it's not empty.
 * Any directory structure is now allowed.
 */
export function validateFilePath(path: string): { valid: boolean; error?: string } {
  if (!path) {
    return { valid: false, error: 'File path cannot be empty' };
  }
  return { valid: true };
}

/**
 * Validate file extension and return warning if needed.
 * Returns { isCommon, warning } - warning is only for logging, doesn't reject.
 */
export function validateFileExtension(path: string): { isCommon: boolean; warning?: string } {
  if (!path) {
    return { isCommon: false, warning: 'File path cannot be empty' };
  }

  const ext = getFileExtension(path);
  if (!ext) {
    return { isCommon: true };  // No extension is OK
  }

  if (WARNED_EXTENSIONS.has(ext)) {
    return { isCommon: false, warning: `File '${path}' has extension '${ext}' which may be binary or unsafe` };
  }

  const isCommon = COMMON_EXTENSIONS.has(ext);
  if (!isCommon) {
    return { isCommon: false, warning: `File '${path}' has uncommon extension '${ext}'` };
  }

  return { isCommon: true };
}

/**
 * Build a file tree from a flat list of skill files.
 * SKILL.md is placed at the top, other files are organized in a tree structure.
 */
export function buildFileTree(files: SkillFile[]): { skillMdFile: SkillFile | null; tree: FileTreeNode[] } {
  if (!files || files.length === 0) {
    return { skillMdFile: null, tree: [] };
  }

  // Separate SKILL.md from other files
  const skillMdFile = files.find(f => f.path === 'SKILL.md' || f.file_name === 'SKILL.md') || null;
  const otherFiles = files.filter(f => f.path !== 'SKILL.md' && f.file_name !== 'SKILL.md');

  // Build tree structure using a nested map approach
  const root: FileTreeNode[] = [];

  // Helper to find or create a node in an array
  const findOrCreateNode = (nodes: FileTreeNode[], name: string, path: string, isDirectory: boolean, file?: SkillFile): FileTreeNode => {
    let node = nodes.find(n => n.name === name);
    if (!node) {
      node = {
        name,
        path,
        isDirectory,
        children: isDirectory ? [] : undefined,
        file: isDirectory ? undefined : file,
      };
      nodes.push(node);
    }
    return node;
  };

  for (const file of otherFiles) {
    const parts = file.path.split('/');
    let currentNodes = root;
    let currentPath = '';

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const isLastPart = i === parts.length - 1;

      const node = findOrCreateNode(
        currentNodes,
        part,
        currentPath,
        !isLastPart,
        isLastPart ? file : undefined
      );

      if (!isLastPart) {
        // Move to next level (children of this directory)
        if (!node.children) {
          node.children = [];
        }
        currentNodes = node.children;
      }
    }
  }

  // Sort nodes recursively (directories first, then alphabetically)
  const sortNodes = (nodes: FileTreeNode[]): FileTreeNode[] => {
    return nodes.sort((a, b) => {
      // Directories first
      if (a.isDirectory && !b.isDirectory) return -1;
      if (!a.isDirectory && b.isDirectory) return 1;
      // Then alphabetically
      return a.name.localeCompare(b.name);
    }).map(node => ({
      ...node,
      children: node.children ? sortNodes(node.children) : undefined,
    }));
  };

  const tree = sortNodes(root);

  return { skillMdFile, tree };
}

/**
 * Flatten a file tree back to a flat list of paths.
 * Useful for getting all file paths from a tree.
 */
export function flattenFileTree(tree: FileTreeNode[]): string[] {
  const paths: string[] = [];

  const traverse = (nodes: FileTreeNode[]) => {
    for (const node of nodes) {
      if (node.file) {
        paths.push(node.path);
      }
      if (node.children) {
        traverse(node.children);
      }
    }
  };

  traverse(tree);
  return paths;
}

/**
 * Get the filename from a path (last segment after /).
 */
export function getFilenameFromPath(path: string): string {
  if (!path.includes('/')) {
    return path;
  }
  return path.split('/').pop() || path;
}

/**
 * Get file extension from filename (including the dot, lowercase).
 */
export function getFileExtension(filename: string): string {
  const lastDot = filename.lastIndexOf('.');
  if (lastDot === -1) return '';
  return filename.slice(lastDot).toLowerCase();
}

/**
 * Map file extension to file type/language.
 */
export function getFileTypeFromExtension(ext: string): string {
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
  };
  return extMap[ext.toLowerCase()] || 'text';
}

/**
 * Create a file path from directory and filename.
 * Pass null or empty string for root-level files.
 */
export function createFilePath(directory: string | null, filename: string): string {
  if (!directory) {
    return filename;
  }
  // Remove trailing slash if present
  const dir = directory.endsWith('/') ? directory.slice(0, -1) : directory;
  return `${dir}/${filename}`;
}

// Helper function to convert backend Skill to frontend Skill format
function normalizeSkill(backendSkill: any): Skill {
  return {
    id: backendSkill.id,
    name: backendSkill.name,
    description: backendSkill.description,
    content: backendSkill.content,
    tags: backendSkill.tags || [],
    source_type: backendSkill.source_type || 'local',
    source_url: backendSkill.source_url,
    root_path: backendSkill.root_path,
    owner_id: backendSkill.owner_id,
    created_by_id: backendSkill.created_by_id,
    is_public: backendSkill.is_public || false,
    license: backendSkill.license,
    created_at: backendSkill.created_at,
    updated_at: backendSkill.updated_at,
    files: backendSkill.files?.map((f: any) => normalizeSkillFile(f)) || [],
    // Legacy fields for backward compatibility (deprecated, use source_type instead)
    // Map source_type directly to source without 'aws' conversion
    source: backendSkill.source_type === 'git' ? 'git' : backendSkill.source_type === 's3' ? 's3' : 'local',
    sourceUrl: backendSkill.source_url,
    updatedAt: new Date(backendSkill.updated_at).getTime(),
  };
}

// Helper function to convert backend SkillFile to frontend SkillFile format
function normalizeSkillFile(backendFile: any): SkillFile {
  const path = backendFile.path || '';
  return {
    id: backendFile.id,
    skill_id: backendFile.skill_id,
    path: path,
    file_name: backendFile.file_name,
    file_type: backendFile.file_type,
    content: backendFile.content,
    storage_type: backendFile.storage_type,
    storage_key: backendFile.storage_key,
    size: backendFile.size,
    created_at: backendFile.created_at,
    updated_at: backendFile.updated_at,
    // Legacy fields for backward compatibility
    name: backendFile.file_name,
    language: backendFile.file_type,
  };
}

// Helper function to convert frontend Skill to backend format
function toBackendSkill(skill: Partial<Skill>): any {
  const files = skill.files?.map(f => ({
    path: f.path || f.name || '',
    file_name: f.file_name || f.name || '',
    file_type: f.file_type || f.language || '',
    content: f.content || null,
    storage_type: f.storage_type || 'database',
    storage_key: f.storage_key || null,
    size: f.size || 0,
  })) || [];

  return {
    name: skill.name,
    description: skill.description || '',
    content: skill.content || '',
    tags: skill.tags || [],
    source_type: skill.source_type || (
      skill.source === 'git' ? 'git'
      : skill.source === 's3' ? 's3'
      : 'local'
    ),
    source_url: skill.source_url || skill.sourceUrl || null,
    root_path: skill.root_path || null,
    owner_id: skill.owner_id || null,
    is_public: skill.is_public || false,
    license: skill.license || null,
    files: files.length > 0 ? files : undefined,
  };
}

/**
 * Create default files for a new skill with SKILL.md format.
 */
const createDefaultFiles = (name: string, description: string, body?: string): SkillFile[] => {
  const now = new Date().toISOString();
  const skillMdContent = generateSkillMd(name, description, body || `# ${name}\n\n## Overview\n\nAdd your skill instructions here.`);

  return [
    {
      id: '',
      skill_id: '',
      path: 'SKILL.md',
      file_name: 'SKILL.md',
      file_type: 'markdown',
      content: skillMdContent,
      storage_type: 'database',
      storage_key: null,
      size: skillMdContent.length,
      created_at: now,
      updated_at: now,
      name: 'SKILL.md',
      language: 'markdown',
    },
  ];
};

/**
 * Create a new file with proper structure.
 * @param directory - The directory path (e.g., "src", "lib/utils") or null for root level
 * @param filename - The filename
 * @param fileType - The file type (e.g., "python", "markdown")
 * @param content - Optional content
 */
export function createSkillFile(
  directory: string | null,
  filename: string,
  fileType: string,
  content: string = ''
): Partial<SkillFile> {
  const path = createFilePath(directory, filename);
  const now = new Date().toISOString();

  return {
    id: '',
    skill_id: '',
    path,
    file_name: filename,
    file_type: fileType,
    content,
    storage_type: 'database',
    storage_key: null,
    size: content.length,
    created_at: now,
    updated_at: now,
    name: filename,
    language: fileType,
  };
}

// ============================================================================
// File Compliance Validation
// ============================================================================

/**
 * System files that should be automatically filtered (not shown to users)
 */
export const SYSTEM_FILES = [
  '.DS_Store',           // macOS
  'Thumbs.db',           // Windows
  '.gitkeep',            // Git
  '.gitignore',          // Git (but we might want to keep this, so maybe remove)
  'desktop.ini',         // Windows
  '.Spotlight-V100',     // macOS
  '.Trashes',            // macOS
  '__MACOSX',            // macOS (zip extraction artifact)
];

/**
 * Compliance configuration for skill file imports
 */
export const COMPLIANCE_CONFIG = {
  maxFileSize: 1024 * 1024,        // 1MB per file
  maxTotalSize: 10 * 1024 * 1024,  // 10MB total
  allowedExtensions: [
    '.md', '.txt', '.rst',         // Documentation
    '.py', '.js', '.ts', '.jsx', '.tsx',  // Scripts
    '.sh', '.bash', '.zsh',        // Shell scripts
    '.json', '.yaml', '.yml', '.toml',  // Config files
    '.html', '.css', '.scss',      // Web assets
    '.svg', '.xml',                // Other formats
  ],
  requiredFiles: ['SKILL.md'],
};

/**
 * Rejected file information
 */
export interface RejectedFile {
  path: string;
  reason: string;
}

/**
 * Validation result for file compliance checks
 */
export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  rejectedFiles?: RejectedFile[];  // Files that were rejected (binary files, etc.)
}

/**
 * Extract relative path from webkitRelativePath (removes root folder name).
 * Used when importing from local directory via browser file picker.
 */
function extractRelativePath(webkitRelativePath: string): string {
  const parts = webkitRelativePath.split('/');
  // Remove the first part (root folder name) to get the relative path
  return parts.slice(1).join('/');
}

/**
 * Check if a filename is a system file that should be filtered
 */
export function isSystemFile(filename: string): boolean {
  const name = filename.toLowerCase();
  // Check exact matches
  if (SYSTEM_FILES.some(sysFile => name === sysFile.toLowerCase())) {
    return true;
  }
  // Check if filename starts with system file patterns
  if (name.startsWith('.ds_store') || name.endsWith('.ds_store')) {
    return true;
  }
  // Check for __MACOSX directory files
  if (name.includes('__macosx')) {
    return true;
  }
  return false;
}

/**
 * Check if content contains binary data (NULL bytes)
 */
export function isBinaryFile(content: string): boolean {
  // Check for NULL bytes (0x00)
  if (content.includes('\x00')) {
    return true;
  }
  // Check for other common binary indicators
  // If content has a high ratio of non-printable characters, it's likely binary
  const nonPrintableCount = (content.match(/[\x00-\x08\x0E-\x1F\x7F-\x9F]/g) || []).length;
  const totalChars = content.length;
  // If more than 5% are non-printable (excluding common whitespace), likely binary
  if (totalChars > 0 && nonPrintableCount / totalChars > 0.05) {
    return true;
  }
  return false;
}

/**
 * Validate imported files for compliance
 */
export function validateImportedFiles(files: File[]): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const rejectedFiles: RejectedFile[] = [];

  if (files.length === 0) {
    errors.push('No files selected');
    return { valid: false, errors, warnings, rejectedFiles };
  }

  // Filter out system files first (they won't be counted in validation)
  const validFiles: File[] = [];
  for (const file of files) {
    const relativePath = extractRelativePath(file.webkitRelativePath || file.name);
    const filename = getFilenameFromPath(relativePath) || file.name;

    // Skip system files silently (don't show to user)
    if (isSystemFile(filename)) {
      continue;
    }

    validFiles.push(file);
  }

  // Calculate total size (only for valid files)
  const totalSize = validFiles.reduce((sum, f) => sum + f.size, 0);

  // Check total size limit
  if (totalSize > COMPLIANCE_CONFIG.maxTotalSize) {
    errors.push(
      `Total size ${(totalSize / 1024 / 1024).toFixed(2)}MB exceeds limit of ${COMPLIANCE_CONFIG.maxTotalSize / 1024 / 1024}MB`
    );
  }

  // Check for SKILL.md (only in valid files)
  const hasSkillMd = validFiles.some(f => {
    const relativePath = extractRelativePath(f.webkitRelativePath || f.name);
    return relativePath === 'SKILL.md';
  });

  if (!hasSkillMd) {
    errors.push('SKILL.md is required but not found in the directory');
  }

  // Check individual files
  for (const file of validFiles) {
    const relativePath = extractRelativePath(file.webkitRelativePath || file.name);
    const filename = getFilenameFromPath(relativePath) || file.name;
    const ext = getFileExtension(filename);

    // Skip directories (some browsers include them)
    if (file.size === 0 && !ext) continue;

    // Check file size
    if (file.size > COMPLIANCE_CONFIG.maxFileSize) {
      errors.push(
        `File "${relativePath}" (${(file.size / 1024 / 1024).toFixed(2)}MB) exceeds max size of ${COMPLIANCE_CONFIG.maxFileSize / 1024 / 1024}MB`
      );
    }

    // Check file extension - just warn, don't reject
    const extValidation = validateFileExtension(relativePath);
    if (extValidation.warning) {
      warnings.push(extValidation.warning);
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    rejectedFiles,
  };
}

/**
 * Validate SKILL.md content for required frontmatter
 */
export function validateSkillMdContent(content: string): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  const parsed = parseSkillMd(content);

  if (!parsed.frontmatter.name || parsed.frontmatter.name.trim() === '') {
    errors.push('SKILL.md frontmatter is missing required "name" field');
  }

  if (!parsed.frontmatter.description || parsed.frontmatter.description.trim() === '') {
    errors.push('SKILL.md frontmatter is missing required "description" field');
  }

  if (!parsed.body || parsed.body.trim() === '') {
    warnings.push('SKILL.md has no content body after frontmatter');
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

/**
 * Process files from a local directory selection
 */
export async function processLocalDirectoryFiles(fileList: FileList): Promise<{
  files: File[];
  validation: ValidationResult;
}> {
  const files = Array.from(fileList);

  // Initial file structure validation (this filters system files)
  const validation = validateImportedFiles(files);

  // Filter out system files from the files array
  const validFiles = files.filter(file => {
    const relativePath = extractRelativePath(file.webkitRelativePath || file.name);
    const filename = getFilenameFromPath(relativePath) || file.name;
    return !isSystemFile(filename);
  });

  // Detect binary files early (for validation display)
  const rejectedFiles: RejectedFile[] = [];
  for (const file of validFiles) {
    const relativePath = extractRelativePath(file.webkitRelativePath || file.name);
    const filename = getFilenameFromPath(relativePath) || file.name;

    // Skip empty files
    if (file.size === 0) continue;

    try {
      const { isBinary } = await readFileAsText(file);
      if (isBinary) {
        rejectedFiles.push({
          path: relativePath,
          reason: 'binary', // Will be translated in UI
        });
      }
    } catch (e) {
      // If reading fails, it might be binary
      rejectedFiles.push({
        path: relativePath,
        reason: `无法读取文件: ${e instanceof Error ? e.message : '未知错误'}`,
      });
    }
  }

  // Add rejected files to validation result
  validation.rejectedFiles = rejectedFiles;

  // If there are structure errors, return early
  if (!validation.valid) {
    return { files: validFiles, validation };
  }

  // Find and validate SKILL.md content (from valid files, excluding binary)
  const skillMdFile = validFiles.find(f => {
    const relativePath = extractRelativePath(f.webkitRelativePath || f.name);
    return relativePath === 'SKILL.md' && !rejectedFiles.some(rf => rf.path === relativePath);
  });

  if (skillMdFile) {
    try {
      const { content, isBinary } = await readFileAsText(skillMdFile);

      // Check if SKILL.md is binary (should never happen, but just in case)
      if (isBinary) {
        validation.errors.push('SKILL.md_BINARY'); // Will be translated in UI
        validation.valid = false;
      } else {
        const contentValidation = validateSkillMdContent(content);

        // Merge content validation results
        validation.errors.push(...contentValidation.errors);
        validation.warnings.push(...contentValidation.warnings);
        validation.valid = validation.errors.length === 0;
      }
    } catch (e) {
      validation.errors.push('SKILL.md_READ_ERROR'); // Will be translated in UI
      validation.valid = false;
    }
  }

  return { files: validFiles, validation };
}

/**
 * Read file content as text with binary detection
 */
function readFileAsText(file: File): Promise<{ content: string; isBinary: boolean }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const content = reader.result as string;
      const isBinary = isBinaryFile(content);
      resolve({ content, isBinary });
    };
    reader.onerror = () => reject(reader.error);
    // Try to read as UTF-8 first
    reader.readAsText(file, 'UTF-8');
  });
}

/**
 * Convert imported files to SkillFile format
 * Returns both the skill files and rejected files list
 */
export async function convertFilesToSkillFiles(
  files: File[]
): Promise<{ skillFiles: SkillFile[]; rejectedFiles: RejectedFile[] }> {
  const now = new Date().toISOString();
  const skillFiles: SkillFile[] = [];
  const rejectedFiles: RejectedFile[] = [];

  for (const file of files) {
    const relativePath = extractRelativePath(file.webkitRelativePath || file.name);
    const filename = getFilenameFromPath(relativePath) || file.name;
    const ext = getFileExtension(filename);

    // Skip system files silently (don't show to user)
    if (isSystemFile(filename)) {
      continue;
    }

    // Skip empty files (directories)
    if (file.size === 0 && !ext) continue;

    try {
      const { content, isBinary } = await readFileAsText(file);

      // Reject binary files
      if (isBinary) {
        rejectedFiles.push({
          path: relativePath,
          reason: 'binary', // Will be translated in UI
        });
        continue;
      }

      const fileType = getFileTypeFromExtension(ext);

      skillFiles.push({
        id: '',
        skill_id: '',
        path: relativePath,
        file_name: filename,
        file_type: fileType,
        content,
        storage_type: 'database',
        storage_key: null,
        size: content.length,
        created_at: now,
        updated_at: now,
        name: filename,
        language: fileType,
      });
    } catch (e) {
      // If reading fails, it might be binary or corrupted
      rejectedFiles.push({
        path: relativePath,
        reason: 'read_error', // Will be translated in UI
      });
      console.error(`Failed to read file ${relativePath}:`, e);
    }
  }

  return { skillFiles, rejectedFiles };
}

export const skillService = {
  async getSkills(includePublic: boolean = true, tags?: string[]): Promise<Skill[]> {
    try {
      const params = new URLSearchParams();
      if (includePublic !== undefined) {
        params.append('include_public', includePublic.toString());
      }
      if (tags && tags.length > 0) {
        tags.forEach(tag => params.append('tags', tag));
      }

      const url = params.toString()
        ? `${SKILLS_ENDPOINT}?${params.toString()}`
        : SKILLS_ENDPOINT;

      // apiGet extracts data from ApiResponse automatically, so response is Skill[]
      const response = await apiGet<Skill[]>(url);
      const skills = Array.isArray(response) ? response : [];
      return skills.map(normalizeSkill);
    } catch (error) {
      console.error('Failed to fetch skills:', error);
      return [];
    }
  },

  async getSkill(id: string): Promise<Skill | null> {
    try {
      // apiGet extracts data from ApiResponse automatically, so response is Skill
      const response = await apiGet<Skill>(`${SKILLS_ENDPOINT}/${id}`);
      if (response) {
        return normalizeSkill(response);
      }
      return null;
    } catch (error) {
      console.error('Failed to fetch skill:', error);
      return null;
    }
  },

  async saveSkill(skill: Partial<Omit<Skill, 'id' | 'updated_at' | 'created_at'>> & { id?: string; name: string }): Promise<Skill> {
    try {
      const backendSkill = toBackendSkill(skill);

      let skillData: Skill;
      if (skill.id) {
        // Update existing skill
        skillData = await apiPut<Skill>(
          `${SKILLS_ENDPOINT}/${skill.id}`,
          backendSkill
        );
      } else {
        // Create new skill
        skillData = await apiPost<Skill>(
          SKILLS_ENDPOINT,
          backendSkill
        );
      }

      if (skillData) {
        return normalizeSkill(skillData);
      }
      throw new Error('Failed to save skill');
    } catch (error) {
      console.error('Failed to save skill:', error);
      throw error;
    }
  },

  async deleteSkill(id: string): Promise<void> {
    try {
      await apiDelete<ApiResponse<void>>(`${SKILLS_ENDPOINT}/${id}`);
    } catch (error) {
      console.error('Failed to delete skill:', error);
      throw error;
    }
  },

  async deleteFile(fileId: string): Promise<void> {
    try {
      await apiDelete<ApiResponse<void>>(`${SKILLS_ENDPOINT}/files/${fileId}`);
    } catch (error) {
      console.error('Failed to delete file:', error);
      throw error;
    }
  },

  async updateFile(fileId: string, updates: {
    path?: string;
    file_name?: string;
    content?: string;
  }): Promise<SkillFile> {
    try {
      const response = await apiPut<SkillFile>(
        `${SKILLS_ENDPOINT}/files/${fileId}`,
        updates
      );
      return normalizeSkillFile(response);
    } catch (error) {
      console.error('Failed to update file:', error);
      throw error;
    }
  },

  /**
   * Get only public skills from the marketplace
   */
  async getPublicSkills(tags?: string[]): Promise<Skill[]> {
    try {
      const params = new URLSearchParams();
      params.append('include_public', 'true');
      if (tags && tags.length > 0) {
        tags.forEach(tag => params.append('tags', tag));
      }

      const url = `${SKILLS_ENDPOINT}?${params.toString()}`;
      const response = await apiGet<Skill[]>(url);
      const skills = Array.isArray(response) ? response : [];
      // Filter to only include public skills (not owned by current user)
      return skills.filter(s => s.is_public).map(normalizeSkill);
    } catch (error) {
      console.error('Failed to fetch public skills:', error);
      return [];
    }
  },

  /**
   * Toggle the public status of a skill
   */
  async togglePublic(skillId: string, isPublic: boolean): Promise<Skill> {
    try {
      const response = await apiPut<Skill>(
        `${SKILLS_ENDPOINT}/${skillId}`,
        { is_public: isPublic }
      );
      return normalizeSkill(response);
    } catch (error) {
      console.error('Failed to toggle skill public status:', error);
      throw error;
    }
  },

  /**
   * Fork (copy) a public skill to user's own collection
   */
  async forkSkill(skillId: string): Promise<Skill> {
    try {
      // First get the original skill with all files
      const originalSkill = await this.getSkill(skillId);
      if (!originalSkill) {
        throw new Error('Skill not found');
      }

      // Generate a unique name with timestamp to avoid duplicates
      const timestamp = Date.now().toString(36);
      const newName = `${originalSkill.name}-copy-${timestamp}`;

      // Prepare files with only the necessary fields for creation
      const newFiles = originalSkill.files?.map(f => ({
        path: f.path,
        file_name: f.file_name,
        file_type: f.file_type,
        content: f.content,
        storage_type: f.storage_type || 'database',
        storage_key: null,
        size: f.size || 0,
      })) || [];

      // Update SKILL.md content if present to reflect new name
      const updatedFiles = newFiles.map(f => {
        if (f.path === 'SKILL.md' || f.file_name === 'SKILL.md') {
          // Update the frontmatter with new name
          const content = f.content || '';
          const updatedContent = content.replace(
            /^(---\s*\nname:\s*).+$/m,
            `$1${newName}`
          );
          return { ...f, content: updatedContent, size: updatedContent.length };
        }
        return f;
      });

      // Create a new skill with the same content but new ownership
      const forkedSkill = await this.saveSkill({
        name: newName,
        description: originalSkill.description,
        content: originalSkill.content,
        tags: originalSkill.tags,
        source_type: originalSkill.source_type,
        license: originalSkill.license,
        is_public: false, // Forked skills are private by default
        files: updatedFiles as SkillFile[],
      });

      return forkedSkill;
    } catch (error) {
      console.error('Failed to fork skill:', error);
      throw error;
    }
  },

  /**
   * Get user's own skills (excluding public skills from others)
   */
  async getMySkills(): Promise<Skill[]> {
    try {
      const params = new URLSearchParams();
      params.append('include_public', 'false');

      const url = `${SKILLS_ENDPOINT}?${params.toString()}`;
      const response = await apiGet<Skill[]>(url);
      const skills = Array.isArray(response) ? response : [];
      return skills.map(normalizeSkill);
    } catch (error) {
      console.error('Failed to fetch my skills:', error);
      return [];
    }
  },
};
