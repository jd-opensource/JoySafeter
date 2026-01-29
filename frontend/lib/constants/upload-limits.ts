export const UPLOAD_LIMITS = {
  MAX_FILE_SIZE_BYTES: 50 * 1024 * 1024, // 50MB
  MAX_FILE_SIZE_MB: 50,
  MAX_FILES_PER_UPLOAD: 10, // Maximum 10 files per upload
  MAX_ZIP_FILES: 50,
  MAX_ZIP_TOTAL_SIZE_BYTES: 100 * 1024 * 1024, // 100MB
} as const;

export const ALLOWED_MIME_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.oasis.opendocument.text',
  'application/vnd.oasis.opendocument.spreadsheet',
  'application/vnd.oasis.opendocument.presentation',
  'application/rtf',
  'application/epub+zip',
  'text/plain',
  'text/csv',
  'text/markdown',
  'text/html',
  'text/css',
  'text/javascript',
  'text/x-python',
  'text/x-java',
  'text/x-c',
  'text/x-c++',
  'application/json',
  'application/xml',
  'application/javascript',
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/zip',
  'application/x-tar',
  'application/gzip',
  'application/vnd.android.package-archive',
] as const;

export const ALLOWED_EXTENSIONS = [
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.odt', '.ods', '.odp', '.rtf', '.epub',
  '.txt', '.csv', '.md', '.html', '.css',
  '.js', '.ts', '.py', '.java', '.c', '.cpp', '.h', '.hpp',
  '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
  '.sh', '.sql', '.yaml', '.yml', '.toml', '.xml', '.json',
  '.jsx', '.tsx', '.vue', '.svelte',
  '.jpeg', '.jpg', '.png', '.gif', '.webp',
  '.zip', '.tar', '.gz', '.7z', '.rar',
  '.apk',
] as const;

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function isAllowedFile(file: File): { allowed: boolean; reason?: string } {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();

  if (!ALLOWED_EXTENSIONS.includes(ext as any)) {
    return { allowed: false, reason: `File type ${ext} is not supported` };
  }

  if (file.size > UPLOAD_LIMITS.MAX_FILE_SIZE_BYTES) {
    return {
      allowed: false,
      reason: `File size (${formatFileSize(file.size)}) exceeds ${UPLOAD_LIMITS.MAX_FILE_SIZE_MB}MB limit`
    };
  }

  return { allowed: true };
}

export const ALLOWED_EXTENSIONS_STRING = ALLOWED_EXTENSIONS.join(',');
