'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '@/lib/i18n'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import { EditorView } from '@codemirror/view'
import { useTheme } from 'next-themes'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Plus,
  Trash2,
  FileText,
  FolderOpen,
  FolderPlus,
  ChevronRight,
  ChevronDown,
  Save,
  Check,
  Eye,
  Pencil,
  Clock,
  Camera,
  History,
  Upload,
  RefreshCw,
} from 'lucide-react'
import { managedGet, managedPost, managedPut, managedDelete, managedUpload } from '@/lib/api-client'
import type {
  SkillRecord,
  SkillFileRecord,
  SkillVersionRecord,
  SkillSecurityScanRecord,
} from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  MonoId,
  RelativeTime,
  StatusBadge,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'
import {
  SkillLifecycleBadge,
  SkillSecurityBadge,
  SkillStatusBadges,
  SkillVisibilityBadge,
} from '@/components/managed/skills/skill-status-badges'
import { SkillLifecycleActions } from '@/components/managed/skills/skill-lifecycle-actions'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  getManagedSkillImportApiErrorMessage,
  buildManagedSkillImportFromDirectory,
  getManagedSkillImportValidationMessage,
} from '@/lib/managed/skill-import'
import { toastOperationError } from '@/lib/managed/errors'
import { useToast } from '@/hooks/use-toast'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'

function stripId(id: string): string {
  return id.replace(/^(skill_|sklver_|sklfile_)/, '')
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getEditorExtensions(fileType?: string, fileName?: string) {
  const normalizedType = (fileType || '').toLowerCase()
  const normalizedName = (fileName || '').toLowerCase()
  const extensions = [EditorView.lineWrapping]

  if (normalizedType === 'python' || normalizedName.endsWith('.py')) {
    extensions.push(python())
  }

  return extensions
}

function SkillCodeEditor({
  value,
  onChange,
  fileType,
  fileName,
  minHeight = '360px',
  height = '420px',
}: {
  value: string
  onChange: (value: string) => void
  fileType?: string
  fileName?: string
  minHeight?: string
  height?: string
}) {
  const { resolvedTheme } = useTheme()
  const editorTheme = resolvedTheme === 'dark' ? vscodeDark : 'light'

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={editorTheme}
      height={height}
      minHeight={minHeight}
      extensions={getEditorExtensions(fileType, fileName)}
      className="h-full overflow-hidden text-sm [&_.cm-editor]:h-full [&_.cm-scroller]:overflow-auto"
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: true,
        highlightActiveLine: true,
        highlightActiveLineGutter: true,
        searchKeymap: true,
      }}
    />
  )
}

const MAX_FOLDER_DEPTH = 2

// Skill writes (create/update/file edits/version publish/rescan) run the
// security scan synchronously on the backend. With LLM semantic analysis
// enabled a scan can take well over a minute, so these calls override the
// default 30s client timeout. Backend scanner timeout is 180s.
const SKILL_SCAN_TIMEOUT_MS = 200000

const FILE_TYPE_EXT: Record<string, string> = {
  text: '.txt',
  markdown: '.md',
  json: '.json',
  yaml: '.yaml',
  python: '.py',
  javascript: '.js',
  shell: '.sh',
}

function SkillScanProgressNotice({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-md border border-border bg-muted/35 px-4 py-3">
      <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" />
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="mt-1 text-xs text-muted-foreground">{description}</div>
      </div>
    </div>
  )
}

function ensureExtension(name: string, fileType: string): string {
  if (name.includes('.')) return name
  return name + (FILE_TYPE_EXT[fileType] || '.txt')
}

function formatVersion(version: string): string {
  if (/^\d{10,}$/.test(version)) {
    const ms = Math.floor(Number(version) / 1000)
    return new Date(ms).toLocaleString()
  }
  return `v${version}`
}

function timeAgo(dateStr: string, lang?: string): string {
  const locale = lang?.startsWith('zh') ? 'zh-CN' : 'en-US'
  return new Date(dateStr).toLocaleString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function skillSecurityStatus(skill: SkillRecord): string {
  return skill.security_scan?.status || 'not_scanned'
}

function skillSecurityScore(skill: SkillRecord): number | null {
  return typeof skill.security_scan?.score === 'number' ? skill.security_scan.score : null
}

function skillSecuritySearchTerms(skill: SkillRecord): string[] {
  const scan = skill.security_scan
  if (!scan) return ['not_scanned']
  return [
    scan.status,
    scan.severity || '',
    scan.recommendation || '',
    scan.score !== null && scan.score !== undefined ? String(scan.score) : '',
  ]
}

type SecurityIssueView = {
  key: string
  severity: string
  title: string
  category: string | null
  finding: string | null
  explanation: string | null
  remediation: string | null
  confidence: string | null
  location: string | null
  codeSnippet: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  }
  return null
}

function readNumber(record: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  return null
}

function formatIssueConfidence(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const percent = value <= 1 ? value * 100 : value
  return `${Math.round(percent)}%`
}

function formatIssueLocation(value: unknown): string | null {
  if (!isRecord(value)) return null
  const file = readString(value, ['file', 'path', 'filename'])
  const line = readString(value, ['start_line', 'line', 'line_number'])
  const endLine = readString(value, ['end_line'])
  if (!file && !line) return null
  if (!file) return `L${line}`
  if (!line) return file
  if (endLine && endLine !== line) return `${file}:${line}-${endLine}`
  return `${file}:${line}`
}

const SECURITY_ISSUE_SEVERITY_ORDER: Record<string, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MEDIUM: 2,
  LOW: 3,
  INFO: 4,
  INFORMATIONAL: 4,
}

function getSecurityIssueSeverityDistribution(scan: SkillSecurityScanRecord): Array<{ severity: string; count: number }> {
  return [
    { severity: 'CRITICAL', count: scan.critical_count },
    { severity: 'HIGH', count: scan.high_count },
    { severity: 'MEDIUM', count: scan.medium_count },
    { severity: 'LOW', count: scan.low_count },
  ]
}

function getRawScannerRisk(scan: SkillSecurityScanRecord): { score: number | null; severity: string | null; recommendation: string | null } | null {
  const report = scan.report
  if (!isRecord(report)) return null

  const risk = isRecord(report.risk_assessment) ? report.risk_assessment : null
  if (!risk) return null

  const score = readNumber(risk, ['score'])
  const severity = readString(risk, ['severity'])
  const recommendation = readString(risk, ['recommendation'])
  if (score === null && !severity && !recommendation) return null

  return {
    score,
    severity: severity ? severity.toUpperCase() : null,
    recommendation: recommendation ? recommendation.toUpperCase() : null,
  }
}

function securityIssueSeverityClass(severity: string): string {
  switch (severity) {
    case 'CRITICAL':
    case 'HIGH':
      return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300'
    case 'MEDIUM':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-300'
    case 'LOW':
      return 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
    default:
      return 'border-border bg-muted text-muted-foreground'
  }
}

function securityIssueBorderClass(severity: string): string {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'border-red-200 dark:border-red-900/50'
  if (severity === 'MEDIUM') return 'border-amber-200 dark:border-amber-900/50'
  return 'border-border'
}

function getSecurityIssues(scan: SkillSecurityScanRecord): SecurityIssueView[] {
  const report = scan.report
  if (!isRecord(report) || !Array.isArray(report.issues)) return []

  return report.issues
    .filter(isRecord)
    .map((issue, index) => {
      const severity = (readString(issue, ['severity', 'level', 'risk', 'priority']) || 'UNKNOWN').toUpperCase()
      const id = readString(issue, ['id', 'rule_id', 'ruleId', 'code'])
      const pattern = readString(issue, ['pattern', 'rule', 'title', 'name'])
      const category = readString(issue, ['category', 'type'])
      const finding = readString(issue, ['finding', 'message', 'description'])
      const explanation = readString(issue, ['explanation', 'details', 'detail'])
      const remediation = readString(issue, ['remediation', 'recommendation', 'fix', 'suggestion'])
      const title = pattern || category || finding || id || `Issue ${index + 1}`

      return {
        key: `${id || title}-${index}`,
        severity,
        title,
        category,
        finding,
        explanation,
        remediation,
        confidence: formatIssueConfidence(issue.confidence),
        location: formatIssueLocation(issue.location),
        codeSnippet: readString(issue, ['code_snippet', 'snippet', 'evidence']),
      }
    })
    .sort((a, b) => {
      const aOrder = SECURITY_ISSUE_SEVERITY_ORDER[a.severity] ?? 99
      const bOrder = SECURITY_ISSUE_SEVERITY_ORDER[b.severity] ?? 99
      return aOrder - bOrder
    })
}

// -- Center Panel: File tree --

interface TreeNode {
  name: string
  fullPath: string
  file?: SkillFileRecord
  children: TreeNode[]
}

function buildFileTree(files: SkillFileRecord[]): TreeNode {
  const root: TreeNode = { name: '', fullPath: '', children: [] }

  for (const f of files) {
    const parts = f.path.split('/').filter(Boolean)

    let current = root
    for (const part of parts) {
      let child = current.children.find((c) => c.name === part && !c.file)
      if (!child) {
        const prefix = current.fullPath
        child = { name: part, fullPath: prefix + part + '/', children: [] }
        current.children.push(child)
      }
      current = child
    }
    current.children.push({
      name: f.file_name,
      fullPath: f.path + f.file_name,
      file: f,
      children: [],
    })
  }

  const sortTree = (node: TreeNode) => {
    node.children.sort((a, b) => {
      if (a.file && !b.file) return 1
      if (!a.file && b.file) return -1
      return a.name.localeCompare(b.name)
    })
    node.children.forEach(sortTree)
  }
  sortTree(root)
  return root
}

function FileTreeNode({
  node,
  depth,
  selectedFileId,
  onSelectFile,
  onDeleteFile,
  onDeleteFolder,
  onAddToFolder,
}: {
  node: TreeNode
  depth: number
  selectedFileId: string | null
  onSelectFile: (id: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  onAddToFolder: (folderPath: string) => void
}) {
  const [open, setOpen] = useState(true)
  const paddingLeft = 12 + depth * 16

  if (node.file) {
    if (node.name === '.gitkeep') return null
    return (
      <div
        onClick={() => onSelectFile(node.file!.id)}
        className={`group flex cursor-pointer items-center gap-2 py-1.5 pr-3 transition-colors hover:bg-muted/50 ${
          selectedFileId === node.file!.id ? 'bg-muted font-medium' : ''
        }`}
        style={{ paddingLeft }}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/50">
          {formatBytes(node.file!.size)}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDeleteFile(node.file!.id)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    )
  }

  return (
    <>
      <div
        onClick={() => setOpen(!open)}
        className="group flex cursor-pointer items-center gap-1 py-1.5 pr-3 text-muted-foreground hover:text-foreground"
        style={{ paddingLeft }}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <FolderOpen className="h-4 w-4" />
        <span className="ml-1 flex-1">{node.name}/</span>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onAddToFolder(node.fullPath)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-foreground group-hover:block"
        >
          <Plus className="h-3 w-3" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDeleteFolder(node.fullPath)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      {open &&
        node.children.map((child, i) => (
          <FileTreeNode
            key={child.file?.id ?? child.fullPath + i}
            node={child}
            depth={depth + 1}
            selectedFileId={selectedFileId}
            onSelectFile={onSelectFile}
            onDeleteFile={onDeleteFile}
            onDeleteFolder={onDeleteFolder}
            onAddToFolder={onAddToFolder}
          />
        ))}
    </>
  )
}

function SkillWorkspace({
  files,
  selectedFileId,
  onSelectFile,
  onSelectMain,
  onAddFolder,
  onAddToFolder,
  onDeleteFile,
  onDeleteFolder,
  isMainSelected,
}: {
  files: SkillFileRecord[]
  selectedFileId: string | null
  onSelectFile: (id: string) => void
  onSelectMain: () => void
  onAddFolder: () => void
  onAddToFolder: (folderPath: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  isMainSelected: boolean
}) {
  const { t } = useTranslation()
  const filteredFiles = files.filter(
    (f) => !(f.path === '' && f.file_name.toLowerCase() === 'skill.md'),
  )
  const tree = buildFileTree(filteredFiles)

  return (
    <div className="flex h-full w-[260px] shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-medium">{t('managed.skills.workspace')}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={onAddFolder}
          title={t('managed.skills.newFolder')}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto text-sm">
        {/* SKILL.md -- always first */}
        <div
          onClick={onSelectMain}
          className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 transition-colors hover:bg-muted/50 ${
            isMainSelected ? 'bg-muted font-medium' : ''
          }`}
        >
          <FileText className="h-4 w-4 text-blue-500" />
          <span>SKILL.md</span>
        </div>

        {/* File tree */}
        {tree.children.length > 0 ? (
          tree.children.map((child, i) => (
            <FileTreeNode
              key={child.file?.id ?? child.fullPath + i}
              node={child}
              depth={0}
              selectedFileId={selectedFileId}
              onSelectFile={onSelectFile}
              onDeleteFile={onDeleteFile}
              onDeleteFolder={onDeleteFolder}
              onAddToFolder={onAddToFolder}
            />
          ))
        ) : (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground/60">
            {t('managed.skills.emptyWorkspace')}
          </div>
        )}
      </div>
    </div>
  )
}

// -- Right Panel: Editor with metadata + content --

interface SkillFormState {
  name: string
  description: string
  content: string
  license: string
  tags: string
  is_public: boolean
  visibility?: string
  source_type: string
  source_url: string
}

function SkillEditor({
  files,
  selectedFileId,
  form,
  setForm,
  fileContent,
  setFileContent,
  versions,
  onCreateVersion,
  onDeleteVersion,
  isCreatingVersion,
}: {
  skill: SkillRecord
  files: SkillFileRecord[]
  selectedFileId: string | null
  form: SkillFormState
  setForm: (f: SkillFormState) => void
  fileContent: string
  setFileContent: (c: string) => void
  versions: SkillVersionRecord[]
  onCreateVersion: (releaseNotes: string, version?: string) => void
  onDeleteVersion: (
    version: string,
    force?: boolean,
  ) => Promise<{ ok: true } | { ok: false; referrers: Array<Record<string, unknown>>; hint?: string }>
  isCreatingVersion: boolean
}) {
  const { t, i18n } = useTranslation()
  const [editorTab, setEditorTab] = useState<'editor' | 'versions'>('editor')
  const [contentMode, setContentMode] = useState<'edit' | 'preview'>('edit')
  const [showVersionForm, setShowVersionForm] = useState(false)
  const [newReleaseNotes, setNewReleaseNotes] = useState('')
  const [newVersionStr, setNewVersionStr] = useState('')
  /** Per-row delete state: keyed by version string. */
  const [deleteState, setDeleteState] = useState<{
    version: string
    referrers?: Array<Record<string, unknown>>
    hint?: string
    pending?: boolean
  } | null>(null)

  const selectedFile = files.find((f) => f.id === selectedFileId)
  const isEditingFile = selectedFileId !== null && selectedFile !== undefined

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Tab bar */}
      <Tabs
        value={editorTab}
        onValueChange={(v) => setEditorTab(v as 'editor' | 'versions')}
      >
        <div className="flex items-center justify-between border-b border-border pr-3">
          <TabsList>
            <TabsTrigger value="editor">{t('managed.skills.editor')}</TabsTrigger>
            <TabsTrigger value="versions">
              {t('managed.skills.versionHistory')}
            </TabsTrigger>
          </TabsList>
        </div>
      </Tabs>

      {/* Tab content */}
      {editorTab === 'editor' && (
        <div className="flex-1 overflow-y-auto p-4">
          {isEditingFile ? (
            <div className="flex h-full flex-col">
              <div className="mb-2 text-sm font-medium text-muted-foreground">
                {selectedFile.file_name}
              </div>
              <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border">
                <SkillCodeEditor
                  value={fileContent}
                  onChange={setFileContent}
                  fileType={selectedFile.file_type}
                  fileName={selectedFile.file_name}
                  minHeight="400px"
                  height="100%"
                />
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {/* Name + License + Visibility row */}
              <div className="grid grid-cols-[1fr,160px,160px] gap-3">
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label className="text-xs font-medium text-muted-foreground">
                      {t('managed.skills.name')}
                    </label>
                    <span className="text-[10px] tabular-nums text-muted-foreground/50">
                      {form.name.length}/64
                    </span>
                  </div>
                  <Input
                    value={form.name}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        name: e.target.value.slice(0, 64),
                      })
                    }
                    placeholder={t('managed.skills.namePlaceholder')}
                    className="h-8 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    {t('managed.skills.license')}
                  </label>
                  <Input
                    value={form.license}
                    onChange={(e) =>
                      setForm({ ...form, license: e.target.value })
                    }
                    placeholder="MIT"
                    className="h-8 text-sm"
                  />
                </div>
                {/* Visibility selector (P2.8) — drives the four-tier
                    sharing surface; legacy ``is_public`` derives from
                    this on submit. */}
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    {t('managed.skills.visibility.label')}
                  </label>
                  <Select
                    value={form.visibility || 'private'}
                    onValueChange={(v) =>
                      setForm({
                        ...form,
                        visibility: v,
                        // Keep legacy is_public in sync so any cached
                        // read still landing on the old column matches
                        // the new column.
                        is_public: v === 'public',
                      })
                    }
                  >
                    <SelectTrigger className="h-8 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="private" title={t('managed.skills.visibility.privateHint')}>{t('managed.skills.visibility.private')}</SelectItem>
                      <SelectItem value="project" title={t('managed.skills.visibility.projectHint')}>{t('managed.skills.visibility.project')}</SelectItem>
                      <SelectItem value="organization" title={t('managed.skills.visibility.organizationHint')}>{t('managed.skills.visibility.organization')}</SelectItem>
                      <SelectItem value="public" title={t('managed.skills.visibility.publicHint')}>{t('managed.skills.visibility.public')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Description */}
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t('managed.skills.description')}
                  </label>
                  <span className="text-[10px] tabular-nums text-muted-foreground/50">
                    {form.description.length}/1024
                  </span>
                </div>
                <textarea
                  value={form.description}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      description: e.target.value.slice(0, 1024),
                    })
                  }
                  placeholder={t('managed.skills.descriptionPlaceholder')}
                  rows={2}
                  className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>

              {/* Divider */}
              <div className="border-t border-border" />

              {/* Content editor */}
              <div className="overflow-hidden rounded-lg border border-border">
                <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1.5">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t('managed.skills.contentMarkdown')}
                  </span>
                  <div className="flex items-center gap-px rounded-md bg-muted p-0.5">
                    <button
                      onClick={() => setContentMode('edit')}
                      className={`flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition-colors ${
                        contentMode === 'edit'
                          ? 'bg-background font-medium text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Pencil className="h-3 w-3" />
                      {t('managed.skills.edit')}
                    </button>
                    <button
                      onClick={() => setContentMode('preview')}
                      className={`flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition-colors ${
                        contentMode === 'preview'
                          ? 'bg-background font-medium text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Eye className="h-3 w-3" />
                      {t('managed.skills.preview')}
                    </button>
                  </div>
                </div>

                {contentMode === 'edit' ? (
                  <SkillCodeEditor
                    value={form.content}
                    onChange={(value) => setForm({ ...form, content: value })}
                    fileType="markdown"
                    fileName="SKILL.md"
                    minHeight="420px"
                    height="420px"
                  />
                ) : (
                  <div className="min-h-[300px] bg-background p-4">
                    {form.content ? (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {form.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="text-sm italic text-muted-foreground">
                        {t('managed.skills.contentPlaceholder')}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {editorTab === 'versions' && (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="mx-auto max-w-2xl">
            {/* Create snapshot */}
            <div className="mb-6">
              {showVersionForm ? (
                <div className="rounded-lg border border-dashed border-primary/30 bg-primary/[0.03] p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                    <Camera className="h-4 w-4 text-primary" />
                    {t('managed.skills.createVersionBtn')}
                  </div>
                  {(() => {
                    const trimmed = newVersionStr.trim()
                    const semverOk = trimmed === '' || /^\d+\.\d+\.\d+$/.test(trimmed)
                    const highest = (() => {
                      const candidates = versions
                        .map((v) => v.version)
                        .filter((v) => /^\d+\.\d+\.\d+$/.test(v))
                      if (candidates.length === 0) return null
                      candidates.sort((a, b) => {
                        const pa = a.split('.').map(Number)
                        const pb = b.split('.').map(Number)
                        for (let i = 0; i < 3; i++) {
                          if (pa[i] !== pb[i]) return pb[i] - pa[i]
                        }
                        return 0
                      })
                      return candidates[0]
                    })()
                    return (
                      <>
                        <div className="mb-3">
                          <input
                            type="text"
                            value={newVersionStr}
                            onChange={(e) => setNewVersionStr(e.target.value)}
                            placeholder={t(
                              'managed.skills.versionInputPlaceholder',
                              'Version (e.g. 1.2.0) — leave empty to auto-bump patch',
                            )}
                            className={`w-full rounded-md border bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-ring ${
                              semverOk ? 'border-border' : 'border-red-500'
                            }`}
                          />
                          <div className="mt-1 text-xs text-muted-foreground">
                            {!semverOk
                              ? t(
                                  'managed.skills.versionInvalidSemver',
                                  'Must be MAJOR.MINOR.PATCH (e.g. 1.2.0)',
                                )
                              : highest
                                ? t(
                                    'managed.skills.versionCurrentHighest',
                                    'Current highest: v{{v}}. New version must be greater.',
                                    { v: highest },
                                  )
                                : t(
                                    'managed.skills.versionFirstHint',
                                    'Leave empty to start at v0.1.0.',
                                  )}
                          </div>
                        </div>
                        <textarea
                          value={newReleaseNotes}
                          onChange={(e) => setNewReleaseNotes(e.target.value)}
                          placeholder={t('managed.skills.releaseNotesPlaceholder')}
                          rows={2}
                          className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                        />
                        <div className="mt-3 flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => {
                              setShowVersionForm(false)
                              setNewReleaseNotes('')
                              setNewVersionStr('')
                            }}
                          >
                            {t('managed.skills.cancel')}
                          </Button>
                          <Button
                            size="sm"
                            className="h-7 text-xs"
                            disabled={isCreatingVersion || !semverOk}
                            onClick={() => {
                              onCreateVersion(newReleaseNotes.trim(), trimmed || undefined)
                              setShowVersionForm(false)
                              setNewReleaseNotes('')
                              setNewVersionStr('')
                            }}
                          >
                            <Camera className="mr-1 h-3 w-3" />
                            {t('managed.skills.createVersionBtn')}
                          </Button>
                        </div>
                      </>
                    )
                  })()}
                </div>
              ) : (
                <button
                  onClick={() => setShowVersionForm(true)}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/[0.02] hover:text-foreground"
                >
                  <Plus className="h-4 w-4" />
                  {t('managed.skills.createVersionBtn')}
                </button>
              )}
            </div>

            {versions.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-16 text-center">
                <History className="h-8 w-8 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground">
                  {t('managed.skills.noVersions')}
                </p>
              </div>
            ) : (
              <div className="relative">
                {/* Timeline line */}
                <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border" />

                <div className="space-y-0">
                  {versions.map((v, idx) => (
                    <div
                      key={v.id}
                      className="group relative flex gap-4 py-3"
                    >
                      {/* Timeline dot */}
                      <div className="relative z-10 mt-1 flex h-[23px] w-[23px] shrink-0 items-center justify-center">
                        <div
                          className={`h-2.5 w-2.5 rounded-full ${
                            idx === 0
                              ? 'bg-primary ring-2 ring-primary/20'
                              : 'bg-muted-foreground/30'
                          }`}
                        />
                      </div>

                      {/* Content */}
                      <div className="min-w-0 flex-1 rounded-lg border border-transparent px-3 py-2 transition-colors group-hover:border-border group-hover:bg-muted/30">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 font-mono text-xs font-medium">
                                {formatVersion(v.version)}
                              </span>
                              {idx === 0 && (
                                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                                  latest
                                </span>
                              )}
                            </div>
                            {v.release_notes && (
                              <p className="mt-1.5 text-sm text-muted-foreground">
                                {v.release_notes}
                              </p>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-1 pt-0.5 text-[11px] text-muted-foreground/60">
                            <Clock className="h-3 w-3" />
                            {timeAgo(v.created_at, i18n.language)}
                            <button
                              type="button"
                              aria-label={t('managed.skills.deleteVersion', 'Delete version')}
                              title={t('managed.skills.deleteVersion', 'Delete version')}
                              onClick={() => setDeleteState({ version: v.version })}
                              className="ml-1 rounded p-1 text-muted-foreground/60 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Delete version dialog (handles 409 SKILL_VERSION_IN_USE with force-confirm) */}
      <Dialog
        open={!!deleteState}
        onOpenChange={(open) => {
          if (!open) setDeleteState(null)
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>
              {t('managed.skills.deleteVersionTitle', 'Delete version v{{v}}', {
                v: deleteState?.version || '',
              })}
            </DialogTitle>
            <DialogDescription>
              {deleteState?.referrers && deleteState.referrers.length > 0
                ? t(
                    'managed.skills.deleteVersionInUse',
                    'This version is referenced by {{n}} agent(s) or saved agent versions. Deleting will leave them pointing at a missing version.',
                    { n: deleteState.referrers.length },
                  )
                : t(
                    'managed.skills.deleteVersionConfirm',
                    'This permanently removes the published snapshot. Agents pinned to this version will fail to load it.',
                  )}
            </DialogDescription>
          </DialogHeader>
          {deleteState?.referrers && deleteState.referrers.length > 0 && (
            <div className="max-h-48 overflow-y-auto rounded-md border border-border bg-muted/30 p-2">
              <ul className="space-y-1 text-xs">
                {deleteState.referrers.map((r, i) => {
                  const kind = String(r.kind ?? '')
                  const agentId = String(r.agent_id ?? '')
                  const label =
                    kind === 'agent'
                      ? `agent · ${(r.name as string) || agentId}`
                      : `agent_version · ${agentId} (v${r.agent_version ?? ''})`
                  return (
                    <li key={i} className="font-mono">
                      {label}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteState(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteState?.pending}
              onClick={async () => {
                if (!deleteState) return
                const force = (deleteState.referrers?.length ?? 0) > 0
                setDeleteState({ ...deleteState, pending: true })
                const res = await onDeleteVersion(deleteState.version, force)
                if (res.ok) {
                  setDeleteState(null)
                } else {
                  // 409 came back — surface referrers and switch to force mode.
                  setDeleteState({
                    version: deleteState.version,
                    referrers: res.referrers,
                    hint: res.hint,
                    pending: false,
                  })
                }
              }}
            >
              {(deleteState?.referrers?.length ?? 0) > 0
                ? t('managed.skills.deleteAnyway', 'Delete anyway')
                : t('managed.skills.delete', 'Delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// -- Main SkillManager --

export default function SkillManagerPage() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null)
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showAddFileDialog, setShowAddFileDialog] = useState(false)
  const [newFileMode, setNewFileMode] = useState<'file' | 'folder'>('file')
  const [newFileDir, setNewFileDir] = useState('')
  const [newFileName, setNewFileName] = useState('')
  const [newFileType, setNewFileType] = useState('text')
  const [newSkillName, setNewSkillName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [deleteFileTarget, setDeleteFileTarget] = useState<string | null>(null)
  const [deleteFolderTarget, setDeleteFolderTarget] = useState<string | null>(
    null,
  )
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [showSecurityHistoryDialog, setShowSecurityHistoryDialog] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [savedFlash, setSavedFlash] = useState(false)
  const flashTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const zipInputRef = useRef<HTMLInputElement>(null)

  const [form, setForm] = useState<SkillFormState>({
    name: '',
    description: '',
    content: '',
    license: '',
    tags: '',
    is_public: false,
    visibility: 'private',
    source_type: '',
    source_url: '',
  })
  const [formSnapshot, setFormSnapshot] = useState<SkillFormState>(form)
  const [fileContent, setFileContent] = useState('')
  const [fileContentSnapshot, setFileContentSnapshot] = useState('')

  const backToSkillList = useCallback(() => {
    setSelectedSkillId(null)
    setSelectedFileId(null)
  }, [])

  // -- Queries --

  const {
    data: skills = [],
    isLoading: skillsLoading,
    isFetching: skillsFetching,
    isError: skillsIsError,
    error: skillsError,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
  } = usePaginatedList<SkillRecord>({ queryKey: 'skills', path: '/skills' })

  const { data: selectedSkill, isError: selectedSkillIsError, error: selectedSkillError } = useQuery({
    queryKey: ['skill', selectedSkillId],
    queryFn: () =>
      managedGet<SkillRecord>(`/skills/${stripId(selectedSkillId!)}`),
    enabled: !!selectedSkillId,
    // While a security scan is running in the background (rescan dispatches
    // async because LLM analysis is slow), poll the skill so the security
    // badge / score refresh automatically once the verdict lands.
    refetchInterval: (query) => {
      const data = query.state.data as SkillRecord | undefined
      return data?.security_scan?.status === 'scanning' ? 3000 : false
    },
  })

  const { data: skillFiles = [] } = useQuery({
    queryKey: ['skill-files', selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillFileRecord[] } | SkillFileRecord[]>(
        `/skills/${stripId(selectedSkillId!)}/files`,
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId,
  })

  const { data: versions = [] } = useQuery({
    queryKey: ['skill-versions', selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillVersionRecord[] } | SkillVersionRecord[]>(
        `/skills/${stripId(selectedSkillId!)}/versions?limit=50`,
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId,
  })

  const {
    data: securityScans = [],
    isFetching: securityScansFetching,
    isError: securityScansIsError,
  } = useQuery({
    queryKey: ['skill-security-scans', selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillSecurityScanRecord[] } | SkillSecurityScanRecord[]>(
        `/skills/${stripId(selectedSkillId!)}/security-scans?limit=20`,
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId && showSecurityHistoryDialog,
  })

  // -- Load skill into form --

  const loadSkillIntoForm = useCallback((skill: SkillRecord) => {
    const tagsStr = Array.isArray(skill.tags)
      ? (skill.tags as string[]).join(', ')
      : ''
    const newForm: SkillFormState = {
      name: skill.name || '',
      description: skill.description || '',
      content: skill.content || '',
      license: skill.license || '',
      tags: tagsStr,
      is_public: skill.is_public || false,
      visibility: skill.visibility || (skill.is_public ? 'public' : 'private'),
      source_type: skill.source_type || '',
      source_url: skill.source_url || '',
    }
    setForm(newForm)
    setFormSnapshot(newForm)
  }, [])

  const prevSkillRef = useState<string | null>(null)
  if (
    selectedSkill &&
    selectedSkillId &&
    prevSkillRef[0] !== selectedSkillId
  ) {
    prevSkillRef[1](selectedSkillId)
    loadSkillIntoForm(selectedSkill)
  }

  // Auto-select SKILL.md when skill files load
  useEffect(() => {
    if (selectedFileId === null && skillFiles.length > 0) {
      const skillMd = skillFiles.find(
        (f) => f.path === '' && f.file_name.toLowerCase() === 'skill.md',
      )
      if (skillMd) {
        setSelectedFileId(skillMd.id)
        setFileContent(skillMd.content || '')
        setFileContentSnapshot(skillMd.content || '')
      }
    }
  }, [skillFiles, selectedFileId])

  const isDirty = JSON.stringify(form) !== JSON.stringify(formSnapshot)
  const isFileDirty = fileContent !== fileContentSnapshot

  // -- Saved flash helper --

  const triggerFlash = useCallback(() => {
    setSavedFlash(true)
    if (flashTimer.current) clearTimeout(flashTimer.current)
    flashTimer.current = setTimeout(() => setSavedFlash(false), 2000)
  }, [])

  // -- Mutations --

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      managedPost<SkillRecord>('/skills', {
        name,
        description: '',
        content: '',
      }),
    onSuccess: (skill) => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      setSelectedSkillId(skill.id)
      setSelectedFileId(null)
      setShowCreateDialog(false)
      setNewSkillName('')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const importFolderMutation = useMutation({
    mutationFn: async (fileList: File[]) => {
      const result = await buildManagedSkillImportFromDirectory(fileList)
      if (!result.valid || !result.skillData) {
        throw new Error(getManagedSkillImportValidationMessage(result.validation, fileList, t))
      }
      return managedPost<SkillRecord>('/skills', result.skillData, {
        timeout: SKILL_SCAN_TIMEOUT_MS,
      })
    },
    onSuccess: (skill) => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      setSelectedSkillId(skill.id)
      setSelectedFileId(null)
      toast({ title: t('managed.skills.localImportSuccess') })
    },
    onError: (error) => {
      console.error('Failed to import skill folder:', error)
      toast({
        variant: 'destructive',
        title: t('common.operationFailed'),
        description: getManagedSkillImportApiErrorMessage(error, t),
      })
    },
  })

  const importZipMutation = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      return managedUpload<SkillRecord>('/skills/import-zip', formData)
    },
    onSuccess: (skill) => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      setSelectedSkillId(skill.id)
      setSelectedFileId(null)
      toast({ title: t('managed.skills.zipImportSuccess') })
    },
    onError: (error) => {
      toast({
        variant: 'destructive',
        title: t('common.operationFailed'),
        description: getManagedSkillImportApiErrorMessage(error, t),
      })
    },
  })

  const isImporting = importFolderMutation.isPending || importZipMutation.isPending

  const handleFolderImportChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const fileList = Array.from(event.target.files || [])
      if (fileList.length > 0) {
        importFolderMutation.mutate(fileList)
      }
      event.target.value = ''
    },
    [importFolderMutation],
  )

  const handleZipImportChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (file) {
        importZipMutation.mutate(file)
      }
      event.target.value = ''
    },
    [importZipMutation],
  )

  const saveMutation = useMutation({
    mutationFn: () => {
      const tags = form.tags
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      return managedPut<SkillRecord>(
        `/skills/${stripId(selectedSkillId!)}`,
        {
          name: form.name,
          description: form.description,
          content: form.content,
          license: form.license,
          tags,
          is_public: form.is_public,
          visibility: form.visibility,
          source_type: form.source_type,
          source_url: form.source_url,
        },
        { timeout: SKILL_SCAN_TIMEOUT_MS },
      )
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      loadSkillIntoForm(updated)
      triggerFlash()
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      managedDelete(`/skills/${stripId(id)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      if (selectedSkillId === deleteTarget) {
        setSelectedSkillId(null)
        setSelectedFileId(null)
      }
      setDeleteTarget(null)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const createFileMutation = useMutation({
    mutationFn: ({
      dir,
      fileName,
      fileType,
      mode,
    }: {
      dir: string
      fileName: string
      fileType: string
      mode: 'file' | 'folder'
    }) => {
      const cleanDir = dir.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
      let path: string
      let name: string

      if (mode === 'folder') {
        const depth = cleanDir
          ? cleanDir.split('/').filter(Boolean).length + 1
          : 1
        if (depth > MAX_FOLDER_DEPTH) {
          return Promise.reject(
            new Error(`Folder nesting limited to ${MAX_FOLDER_DEPTH} levels`),
          )
        }
        path = cleanDir ? `${cleanDir}/${fileName}/` : `${fileName}/`
        name = '.gitkeep'
      } else {
        path = cleanDir ? `${cleanDir}/` : ''
        name = ensureExtension(fileName, fileType)
      }

      return managedPost<SkillFileRecord>(
        `/skills/${stripId(selectedSkillId!)}/files`,
        {
          path,
          file_name: name,
          file_type: fileType,
          content: '',
        },
        { timeout: SKILL_SCAN_TIMEOUT_MS },
      )
    },
    onSuccess: (_file, { mode }) => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      if (mode === 'file') {
        setSelectedFileId(_file.id)
        setFileContent('')
        setFileContentSnapshot('')
      }
      setShowAddFileDialog(false)
      setNewFileDir('')
      setNewFileName('')
      setNewFileType('text')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const saveFileMutation = useMutation({
    mutationFn: () =>
      managedPut<SkillFileRecord>(
        `/skills/${stripId(selectedSkillId!)}/files/${stripId(selectedFileId!)}`,
        { content: fileContent },
        { timeout: SKILL_SCAN_TIMEOUT_MS },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      setFileContentSnapshot(fileContent)
      triggerFlash()
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteFileMutation = useMutation({
    mutationFn: (fileId: string) =>
      managedDelete(
        `/skills/${stripId(selectedSkillId!)}/files/${stripId(fileId)}`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      if (selectedFileId === deleteFileTarget) {
        setSelectedFileId(null)
      }
      setDeleteFileTarget(null)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteFolderMutation = useMutation({
    mutationFn: (folderPath: string) => {
      const filesToDelete = skillFiles.filter((f) =>
        f.path.startsWith(folderPath),
      )
      return Promise.all(
        filesToDelete.map((f) =>
          managedDelete(
            `/skills/${stripId(selectedSkillId!)}/files/${stripId(f.id)}`,
          ),
        ),
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      const folderPath = deleteFolderTarget
      if (
        folderPath &&
        selectedFileId &&
        skillFiles.find(
          (f) => f.id === selectedFileId && f.path.startsWith(folderPath),
        )
      ) {
        setSelectedFileId(null)
      }
      setDeleteFolderTarget(null)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const createVersionMutation = useMutation({
    mutationFn: ({ releaseNotes, version }: { releaseNotes: string; version?: string }) =>
      managedPost<SkillVersionRecord>(
        `/skills/${stripId(selectedSkillId!)}/versions`,
        {
          name: form.name,
          description: form.description,
          content: form.content,
          release_notes: releaseNotes,
          ...(version ? { version } : {}),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['skill-versions', selectedSkillId],
      })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  /** Delete a published skill version. Returns 409-payload referrers on conflict
   * so the dialog can offer a force retry; throws on any other error. */
  const deleteVersion = useCallback(
    async (version: string, force = false): Promise<
      { ok: true } | { ok: false; referrers: Array<Record<string, unknown>>; hint?: string }
    > => {
      try {
        await managedDelete(
          `/skills/${stripId(selectedSkillId!)}/versions/${encodeURIComponent(version)}${
            force ? '?force=true' : ''
          }`,
        )
        queryClient.invalidateQueries({ queryKey: ['skill-versions', selectedSkillId] })
        return { ok: true }
      } catch (e) {
        // 409 with referrer list → caller shows a force-confirm UI.
        const err = e as { status?: number; code?: string; data?: { referrers?: unknown[]; hint?: string } }
        if (err?.status === 409 && err?.code === 'SKILL_VERSION_IN_USE') {
          return {
            ok: false,
            referrers: (err.data?.referrers as Array<Record<string, unknown>>) || [],
            hint: err.data?.hint,
          }
        }
        toastOperationError(t, e, 'common.operationFailed')
        throw e
      }
    },
    [selectedSkillId, queryClient, t],
  )

  const rescanSecurityMutation = useMutation({
    mutationFn: () =>
      managedPost<SkillSecurityScanRecord>(
        `/skills/${stripId(selectedSkillId!)}/security-scans/rescan`,
        {},
        // Rescan dispatches asynchronously on the backend and returns
        // immediately with a scanning-state row, so the default 30s client
        // timeout is plenty — no override needed. The selectedSkill query
        // polls (refetchInterval) until the background verdict lands.
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', selectedSkillId],
      })
      // Scan now runs in the background; tell the user it started rather
      // than that it completed.
      toast({ title: t('managed.skills.rescanStarted') })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  // -- Handlers --

  const handleSelectSkill = useCallback((id: string) => {
    setSelectedSkillId(id)
    setSelectedFileId(null)
  }, [])

  const handleSelectFile = useCallback(
    (fileId: string) => {
      const file = skillFiles.find((f) => f.id === fileId)
      if (file) {
        setSelectedFileId(fileId)
        setFileContent(file.content || '')
        setFileContentSnapshot(file.content || '')
      }
    },
    [skillFiles],
  )

  const handleSelectMain = useCallback(() => {
    const skillMd = skillFiles.find(
      (f) => f.path === '' && f.file_name.toLowerCase() === 'skill.md',
    )
    if (skillMd) {
      setSelectedFileId(skillMd.id)
      setFileContent(skillMd.content || '')
      setFileContentSnapshot(skillMd.content || '')
    } else {
      setSelectedFileId(null)
    }
  }, [skillFiles])

  // -- Ctrl+S / Cmd+S --

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (selectedFileId && isFileDirty) {
          saveFileMutation.mutate()
        } else if (selectedSkillId && isDirty) {
          saveMutation.mutate()
        }
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [
    selectedSkillId,
    selectedFileId,
    isDirty,
    isFileDirty,
    saveMutation,
    saveFileMutation,
  ])

  // -- Unsaved changes guard --

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty || isFileDirty) {
        e.preventDefault()
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty, isFileDirty])

  // -- Render --

  if (skillsIsError) {
    return <ResourceErrorState error={skillsError} resource="skill" onRetry={() => queryClient.invalidateQueries({ queryKey: ['skills'] })} />
  }

  if (selectedSkillIsError) {
    return <ResourceErrorState error={selectedSkillError} resource="skill" onRetry={() => queryClient.invalidateQueries({ queryKey: ['skill', selectedSkillId] })} />
  }

  if (!selectedSkill) {
    // -- List Homepage (consistent with other pages) --
    const filteredSkills = skills.filter((s) =>
      filterByCreatedTime(s.created_at, createdFilter) &&
      matchesSearch(searchQuery, [
        s.id,
        s.name,
        s.description,
        s.license,
        s.is_public ? 'public' : 'private',
        ...skillSecuritySearchTerms(s),
      ]),
    )

    const filters: FilterDef[] = [
      {
        ...createCreatedTimeFilter(t),
        value: createdFilter,
        onChange: setCreatedFilter,
      },
    ]

    const columns: Column<SkillRecord>[] = [
      {
        key: 'id',
        header: t('managed.table.id'),
        width: '12%',
        render: (s) => <MonoId id={s.id} />,
      },
      {
        key: 'name',
        header: t('managed.table.name'),
        width: '14%',
        render: (s) => (
          <span className="font-medium text-foreground">{s.name}</span>
        ),
      },
      {
        key: 'description',
        header: t('managed.skills.description'),
        width: '30%',
        render: (s) => (
          <span className="block truncate text-muted-foreground">
            {s.description || '-'}
          </span>
        ),
      },
      {
        key: 'license',
        header: t('managed.skills.license'),
        width: '13%',
        render: (s) => (
          <span className="text-muted-foreground">{s.license || '-'}</span>
        ),
      },
      {
        key: 'status',
        header: t('managed.table.status'),
        width: '14%',
        render: (s) => (
          <div className="flex flex-wrap items-center gap-1">
            <SkillLifecycleBadge status={s.lifecycle_status} />
            <SkillVisibilityBadge
              visibility={s.visibility}
              isPublic={s.is_public}
            />
          </div>
        ),
      },
      {
        key: 'security',
        header: t('managed.table.security'),
        width: '12%',
        render: (s) => {
          const score = skillSecurityScore(s)
          return (
            <div className="flex items-center gap-2">
              <SkillSecurityBadge status={s.security_scan?.status} />
              {score !== null && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {t('managed.skills.securityScore', { score })}
                </span>
              )}
            </div>
          )
        },
      },
      {
        key: 'updated_at',
        header: t('managed.table.lastUpdated'),
        width: '9%',
        render: (s) => (
          <span className="text-muted-foreground text-xs">
            <RelativeTime date={s.updated_at} />
          </span>
        ),
      },
    ]

    return (
      <div>
        <PageHeader
          title={t('managed.skills.title')}
          subtitle={t('managed.skills.subtitle')}
          action={
            <div className="flex flex-wrap items-center gap-3">
              <Button
                className="h-10 gap-2 px-4 text-sm font-medium leading-none"
                disabled={isImporting}
                onClick={() => setShowImportDialog(true)}
              >
                {isImporting ? (
                  <RefreshCw className="h-4 w-4 animate-spin" strokeWidth={2.25} />
                ) : (
                  <Upload className="h-4 w-4" strokeWidth={2.25} />
                )}
                {isImporting
                  ? t('managed.skills.importingSkill')
                  : t('managed.skills.importSkill')}
              </Button>
              <Button
                className="h-10 gap-2 px-4 text-sm font-medium leading-none"
                onClick={() => setShowCreateDialog(true)}
              >
                <Plus className="h-4 w-4" strokeWidth={2.25} />
                {t('managed.skills.new')}
              </Button>
            </div>
          }
        />

        <input
          ref={folderInputRef}
          type="file"
          className="hidden"
          multiple
          // @ts-expect-error webkitdirectory is supported by Chromium browsers.
          webkitdirectory=""
          onChange={handleFolderImportChange}
        />
        <input
          ref={zipInputRef}
          type="file"
          className="hidden"
          accept=".zip,application/zip"
          onChange={handleZipImportChange}
        />

        {isImporting && (
          <SkillScanProgressNotice
            title={t('managed.skills.importScanInProgressTitle')}
            description={t('managed.skills.importScanInProgressDescription')}
          />
        )}

        <FilterBar
          searchPlaceholder={t('managed.search.skills')}
          searchValue={searchQuery}
          onSearchChange={setSearchQuery}
          onSearch={(id) => {
            const match = skills.find(
              (s) =>
                s.id.includes(id) ||
                s.name.toLowerCase().includes(id.toLowerCase()),
            )
            if (match) handleSelectSkill(match.id)
          }}
          filters={filters}
        />

        <DataTable
          columns={columns}
          data={filteredSkills}
          loading={skillsLoading}
          fetching={skillsFetching}
          onRowClick={(s) => handleSelectSkill(s.id)}
          actionMenu={(s) => [
            {
              label: t('managed.skills.viewDetails'),
              onClick: () => handleSelectSkill(s.id),
            },
            {
              label: t('managed.skills.deleteSkill'),
              onClick: () => setDeleteTarget(s.id),
              destructive: true,
            },
          ]}
          pagination={{
            hasNext,
            hasPrev,
            page,
            pageSize,
            pageSizeOptions,
            onNext: goNext,
            onPrev: goPrev,
            onPageChange: goToPage,
            onPageSizeChange: setPageSize,
          }}
          emptyMessage={t('managed.skills.empty')}
        />

        <Dialog open={showImportDialog} onOpenChange={setShowImportDialog}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t('managed.skills.chooseImportMethod')}</DialogTitle>
              <DialogDescription>
                {t('managed.skills.chooseImportMethodDescription')}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3 py-2">
              <button
                type="button"
                className="flex items-start gap-3 rounded-lg border border-border p-4 text-left transition-colors hover:bg-accent/50 disabled:opacity-60"
                disabled={isImporting}
                onClick={() => {
                  setShowImportDialog(false)
                  zipInputRef.current?.click()
                }}
              >
                <div className="mt-0.5 rounded-md bg-muted p-2">
                  <Upload className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-medium">{t('managed.skills.importZip')}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('managed.skills.importZipHint')}
                  </div>
                </div>
              </button>
              <button
                type="button"
                className="flex items-start gap-3 rounded-lg border border-border p-4 text-left transition-colors hover:bg-accent/50 disabled:opacity-60"
                disabled={isImporting}
                onClick={() => {
                  setShowImportDialog(false)
                  folderInputRef.current?.click()
                }}
              >
                <div className="mt-0.5 rounded-md bg-muted p-2">
                  <FolderOpen className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-medium">{t('managed.skills.importFolder')}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('managed.skills.importFolderBrowserHint')}
                  </div>
                </div>
              </button>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t('managed.skills.createTitle')}</DialogTitle>
              <DialogDescription>
                {t('managed.skills.createDescription')}
              </DialogDescription>
            </DialogHeader>
            <div className="py-4">
              <Input
                value={newSkillName}
                onChange={(e) => setNewSkillName(e.target.value)}
                placeholder={t('managed.skills.namePlaceholder')}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newSkillName.trim()) {
                    createMutation.mutate(newSkillName.trim())
                  }
                }}
              />
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowCreateDialog(false)}
              >
                {t('managed.skills.cancel')}
              </Button>
              <Button
                onClick={() => createMutation.mutate(newSkillName.trim())}
                disabled={!newSkillName.trim() || createMutation.isPending}
              >
                {createMutation.isPending
                  ? t('managed.skills.creating')
                  : t('managed.skills.create')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <ConfirmDialog
          open={deleteTarget !== null}
          title={t('managed.skills.deleteSkill')}
          description={t('managed.skills.deleteConfirm')}
          confirmLabel={t('managed.skills.deleteSkill')}
          destructive
          onConfirm={() =>
            deleteTarget && deleteMutation.mutate(deleteTarget)
          }
          onCancel={() => setDeleteTarget(null)}
        />
      </div>
    )
  }

  // -- Editor View (skill selected) --
  const selectedFile = skillFiles.find((file) => file.id === selectedFileId)
  const isEditingFile = selectedFileId !== null && selectedFile !== undefined
  const canSave = isEditingFile ? isFileDirty : isDirty
  const selectedSecurityScore = skillSecurityScore(selectedSkill)
  const securityTriggerLabels: Record<string, string> = {
    create: t('managed.skills.securityTriggers.create'),
    update: t('managed.skills.securityTriggers.update'),
    file_add: t('managed.skills.securityTriggers.fileAdd'),
    file_update: t('managed.skills.securityTriggers.fileUpdate'),
    file_delete: t('managed.skills.securityTriggers.fileDelete'),
    manual: t('managed.skills.securityTriggers.manual'),
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col px-6 py-5">
      <div className="shrink-0">
        <PageHeader
          title={selectedSkill.name}
          titleExtra={(
            <div className="flex items-center gap-2 flex-wrap">
              <SkillStatusBadges skill={selectedSkill} />
              {/* Visibility selector lives in the header so it's always
                  reachable, regardless of whether the user is editing a
                  file or the metadata form. Bound to the same ``form``
                  state the save mutation reads, so picking a value here
                  is persisted by the next save. */}
              <div className="ml-1 flex items-center gap-1.5">
                <span className="text-[11px] text-muted-foreground">
                  {t('managed.skills.visibility.label')}
                </span>
                <Select
                  value={form.visibility || (form.is_public ? 'public' : 'private')}
                  onValueChange={async (v) => {
                    // Optimistically update local form so the UI
                    // doesn't flicker.
                    setForm({
                      ...form,
                      visibility: v,
                      is_public: v === 'public',
                    })
                    // Fire a focused PUT carrying ONLY visibility +
                    // the legacy ``is_public`` mirror. We don't piggy-
                    // back on ``saveMutation`` because that one bundles
                    // every editable field (name / description /
                    // content / tags / ...), and a stray empty value
                    // there would overwrite real data. The minimal
                    // payload keeps the change scoped to the dropdown
                    // the user actually moved.
                    try {
                      await managedPut<SkillRecord>(
                        `/skills/${stripId(selectedSkillId!)}`,
                        {
                          visibility: v,
                          is_public: v === 'public',
                        },
                        { timeout: SKILL_SCAN_TIMEOUT_MS },
                      )
                      queryClient.invalidateQueries({ queryKey: ['skills'] })
                      queryClient.invalidateQueries({
                        queryKey: ['skill', selectedSkillId],
                      })
                      toast({
                        title: t('managed.skills.savedSuccess'),
                      })
                    } catch (error) {
                      toastOperationError(t, error, 'managed.skills.save.failed')
                    }
                  }}
                >
                  <SelectTrigger className="h-7 w-[110px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="private" title={t('managed.skills.visibility.privateHint')}>{t('managed.skills.visibility.private')}</SelectItem>
                    <SelectItem value="project" title={t('managed.skills.visibility.projectHint')}>{t('managed.skills.visibility.project')}</SelectItem>
                    <SelectItem value="organization" title={t('managed.skills.visibility.organizationHint')}>{t('managed.skills.visibility.organization')}</SelectItem>
                    <SelectItem value="public" title={t('managed.skills.visibility.publicHint')}>{t('managed.skills.visibility.public')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {selectedSecurityScore !== null && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {t('managed.skills.securityScore', { score: selectedSecurityScore })}
                </span>
              )}
            </div>
          )}
          subtitle={selectedFile ? selectedFile.file_name : t('managed.skills.detailSubtitle')}
          breadcrumb={[
            {
              label: t('managed.skills.title'),
              onClick: backToSkillList,
            },
            { label: selectedSkill.name },
          ]}
          action={(
            <div className="flex items-center gap-3">
              {savedFlash && (
                <span className="flex items-center gap-1 text-xs text-green-600">
                  <Check className="h-3 w-3" />
                  {t('managed.skills.savedSuccess')}
                </span>
              )}
              {/* Lifecycle transition buttons — only the legal next
                  edges from the current state are rendered. */}
              <SkillLifecycleActions
                skillId={selectedSkill.id}
                currentStatus={selectedSkill.lifecycle_status}
                invalidateKeys={[
                  ['skill', selectedSkillId],
                  ['skills'],
                ]}
              />
              <Button
                variant="outline"
                className="h-9 gap-2"
                onClick={() => setShowSecurityHistoryDialog(true)}
              >
                <History className="h-4 w-4" />
                {t('managed.skills.viewSecurityHistory')}
              </Button>
              <Button
                variant="outline"
                className="h-9 gap-2"
                onClick={() => rescanSecurityMutation.mutate()}
                disabled={rescanSecurityMutation.isPending || saveMutation.isPending || saveFileMutation.isPending}
              >
                <RefreshCw className={`h-4 w-4 ${rescanSecurityMutation.isPending ? 'animate-spin' : ''}`} />
                {rescanSecurityMutation.isPending
                  ? t('managed.skills.rescanningSecurity')
                  : t('managed.skills.rescanSecurity')}
              </Button>
              <Button
                className="h-9 gap-2"
                onClick={isEditingFile ? () => saveFileMutation.mutate() : () => saveMutation.mutate()}
                disabled={saveMutation.isPending || saveFileMutation.isPending || !canSave}
              >
                <Save className="h-4 w-4" />
                {saveMutation.isPending || saveFileMutation.isPending ? t('managed.skills.saving') : t('managed.skills.saveChanges')}
              </Button>
            </div>
          )}
        />
      </div>

      {rescanSecurityMutation.isPending && (
        <SkillScanProgressNotice
          title={t('managed.skills.securityScanInProgressTitle')}
          description={t('managed.skills.securityScanInProgressDescription')}
        />
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-xl border border-border bg-background">
        {/* Center panel -- file tree */}
        <SkillWorkspace
          files={skillFiles}
          selectedFileId={selectedFileId}
          onSelectFile={handleSelectFile}
          onSelectMain={handleSelectMain}
          onAddFolder={() => {
            setNewFileMode('folder')
            setNewFileDir('')
            setShowAddFileDialog(true)
          }}
          onAddToFolder={(folderPath) => {
            setNewFileMode('file')
            setNewFileDir(folderPath.replace(/\/+$/, ''))
            setShowAddFileDialog(true)
          }}
          onDeleteFile={(id) => setDeleteFileTarget(id)}
          onDeleteFolder={(path) => setDeleteFolderTarget(path)}
          isMainSelected={selectedFileId === null}
        />

        {/* Right panel -- editor */}
        <SkillEditor
          skill={selectedSkill}
          files={skillFiles}
          selectedFileId={selectedFileId}
          form={form}
          setForm={setForm}
          fileContent={fileContent}
          setFileContent={setFileContent}
          versions={versions}
          onCreateVersion={(notes, version) =>
            createVersionMutation.mutate({
              releaseNotes: notes,
              version,
            })
          }
          onDeleteVersion={deleteVersion}
          isCreatingVersion={createVersionMutation.isPending}
        />
      </div>

      <Dialog open={showSecurityHistoryDialog} onOpenChange={setShowSecurityHistoryDialog}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('managed.skills.securityHistory')}</DialogTitle>
            <DialogDescription>
              {t('managed.skills.securityHistoryDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-auto rounded-md border border-border">
            {securityScansFetching ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                {t('common.loading')}
              </div>
            ) : securityScansIsError ? (
              <div className="px-4 py-8 text-center text-sm text-destructive">
                {t('managed.skills.securityHistoryLoadFailed')}
              </div>
            ) : securityScans.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                {t('managed.skills.securityHistoryEmpty')}
              </div>
            ) : (
              <div className="divide-y divide-border">
                {securityScans.map((scan) => {
                  const issues = getSecurityIssues(scan)
                  const severityDistribution = getSecurityIssueSeverityDistribution(scan)
                  const rawScannerRisk = getRawScannerRisk(scan)
                  return (
                    <div key={scan.id} className="grid gap-3 px-4 py-3 md:grid-cols-[1.2fr_1fr_1fr]">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={scan.status} />
                          <span className="text-xs text-muted-foreground">
                            {securityTriggerLabels[scan.trigger] || scan.trigger.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          <RelativeTime date={scan.created_at} />
                        </div>
                      </div>
                      <div className="text-sm">
                        <div className="text-xs text-muted-foreground">
                          {t('managed.skills.securityScoreLabel')}
                        </div>
                        <div className="font-medium">
                          {scan.score !== null && scan.score !== undefined ? scan.score : '-'}
                        </div>
                      </div>
                      <div className="text-sm">
                        <div className="text-xs text-muted-foreground">
                          {t('managed.skills.securityIssues')}
                        </div>
                        <div className="font-medium">
                          {scan.issues_count}
                          {scan.critical_count > 0 || scan.high_count > 0 ? (
                            <span className="ml-2 text-xs text-destructive">
                              {t('managed.skills.securityCriticalHigh', {
                                critical: scan.critical_count,
                                high: scan.high_count,
                              })}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <div className="min-w-0 text-xs text-muted-foreground md:col-span-3">
                        {t('managed.skills.securitySeverity')}: {scan.severity || '-'} ·{' '}
                        {t('managed.skills.securityRecommendation')}: {scan.recommendation || '-'}
                        {scan.error_message ? (
                          <span className="ml-2 text-destructive">{scan.error_message}</span>
                        ) : null}
                      </div>
                      {scan.issues_count > 0 ? (
                        <div className="min-w-0 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs md:col-span-3">
                          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="font-medium text-foreground">
                              {t('managed.skills.securityAggregateRisk')}
                            </span>
                            <span className="text-muted-foreground">
                              {t('managed.skills.securitySeverity')}: {scan.severity || '-'}
                            </span>
                            <span className="text-muted-foreground">
                              {t('managed.skills.securityRecommendation')}: {scan.recommendation || '-'}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {severityDistribution.map((item) => (
                              <span
                                key={item.severity}
                                className={`rounded-full border px-2 py-0.5 font-medium ${securityIssueSeverityClass(item.severity)}`}
                              >
                                {item.severity} {item.count}
                              </span>
                            ))}
                          </div>
                          <div className="mt-2 text-muted-foreground">
                            {t('managed.skills.securityAggregateRiskDescription', {
                              score: scan.score !== null && scan.score !== undefined ? scan.score : '-',
                              severity: scan.severity || '-',
                              recommendation: scan.recommendation || '-',
                            })}
                          </div>
                          {rawScannerRisk ? (
                            <div className="mt-1 text-muted-foreground">
                              {t('managed.skills.securityRawScannerRiskDescription', {
                                score: rawScannerRisk.score !== null ? rawScannerRisk.score : '-',
                                severity: rawScannerRisk.severity || '-',
                                recommendation: rawScannerRisk.recommendation || '-',
                              })}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      {scan.issues_count > 0 ? (
                        <div className="min-w-0 md:col-span-3">
                          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                            <span className="font-medium text-foreground">
                              {t('managed.skills.securityIssueDetails')}
                            </span>
                            <span className="text-muted-foreground">
                              {t('managed.skills.securityIssueDetailsCount', {
                                shown: issues.length,
                                total: scan.issues_count,
                              })}
                            </span>
                          </div>
                          {issues.length > 0 ? (
                            <div className="space-y-2">
                              {issues.map((issue) => {
                                const isHighRisk = issue.severity === 'CRITICAL' || issue.severity === 'HIGH'
                                return (
                                  <details
                                    key={issue.key}
                                    open={isHighRisk}
                                    className={`rounded-md border bg-background ${securityIssueBorderClass(issue.severity)}`}
                                  >
                                    <summary className="grid cursor-pointer gap-2 px-3 py-2 text-sm outline-none transition-colors hover:bg-muted/60 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
                                      <span className={`w-fit rounded-full border px-2 py-0.5 text-[11px] font-medium ${securityIssueSeverityClass(issue.severity)}`}>
                                        {t('managed.skills.securitySingleIssueSeverity', {
                                          severity: issue.severity,
                                        })}
                                      </span>
                                      <span className="min-w-0 truncate font-medium text-foreground">
                                        {issue.title}
                                      </span>
                                      <span className="min-w-0 truncate text-xs text-muted-foreground">
                                        {issue.location || issue.category || '-'}
                                      </span>
                                    </summary>
                                    <div className="space-y-2 border-t border-border px-3 py-2 text-xs text-muted-foreground">
                                      <div className="flex flex-wrap gap-x-4 gap-y-1">
                                        {issue.category ? (
                                          <span>
                                            {t('managed.skills.securityIssueCategory')}: {issue.category}
                                          </span>
                                        ) : null}
                                        {issue.confidence ? (
                                          <span>
                                            {t('managed.skills.securityIssueConfidence')}: {issue.confidence}
                                          </span>
                                        ) : null}
                                      </div>
                                      {issue.finding ? (
                                        <div>
                                          <span className="font-medium text-foreground">
                                            {t('managed.skills.securityIssueFinding')}:{' '}
                                          </span>
                                          {issue.finding}
                                        </div>
                                      ) : null}
                                      {issue.explanation ? (
                                        <div>
                                          <span className="font-medium text-foreground">
                                            {t('managed.skills.securityIssueExplanation')}:{' '}
                                          </span>
                                          {issue.explanation}
                                        </div>
                                      ) : null}
                                      {issue.remediation ? (
                                        <div>
                                          <span className="font-medium text-foreground">
                                            {t('managed.skills.securityIssueRemediation')}:{' '}
                                          </span>
                                          {issue.remediation}
                                        </div>
                                      ) : null}
                                      {issue.codeSnippet ? (
                                        <pre className="max-h-32 overflow-auto rounded border border-border bg-muted px-3 py-2 font-mono text-[11px] text-foreground">
                                          {issue.codeSnippet}
                                        </pre>
                                      ) : null}
                                    </div>
                                  </details>
                                )
                              })}
                            </div>
                          ) : (
                            <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                              {t('managed.skills.securityIssueDetailsUnavailable')}
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Add file/folder dialog */}
      <Dialog
        open={showAddFileDialog}
        onOpenChange={(open) => {
          setShowAddFileDialog(open)
          if (!open) {
            setNewFileMode('file')
            setNewFileDir('')
            setNewFileName('')
            setNewFileType('text')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {newFileMode === 'folder' ? (
                <>
                  <FolderPlus className="h-5 w-5 text-primary" />
                  {t('managed.skills.newFolder')}
                </>
              ) : (
                <>
                  <Plus className="h-5 w-5 text-primary" />
                  {t('managed.skills.newFile')}
                </>
              )}
            </DialogTitle>
            <DialogDescription>
              {newFileMode === 'folder'
                ? t('managed.skills.newFolderHint')
                : t('managed.skills.addFileHint')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {/* Target directory context */}
            {newFileDir && (
              <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
                <FolderOpen className="h-4 w-4 shrink-0" />
                <span className="font-mono">{newFileDir}/</span>
              </div>
            )}

            {/* File / Folder toggle */}
            {newFileDir &&
              (() => {
                const currentDepth = newFileDir
                  .split('/')
                  .filter(Boolean).length
                const canCreateSubfolder = currentDepth < MAX_FOLDER_DEPTH
                return (
                  <div className="flex gap-2">
                    <Button
                      variant={
                        newFileMode === 'file' ? 'default' : 'outline'
                      }
                      size="sm"
                      className="flex-1"
                      onClick={() => {
                        setNewFileMode('file')
                        setNewFileName('')
                      }}
                    >
                      <FileText className="mr-1.5 h-3.5 w-3.5" />
                      {t('managed.skills.file')}
                    </Button>
                    <Button
                      variant={
                        newFileMode === 'folder' ? 'default' : 'outline'
                      }
                      size="sm"
                      className="flex-1"
                      disabled={!canCreateSubfolder}
                      onClick={() => {
                        setNewFileMode('folder')
                        setNewFileName('')
                      }}
                    >
                      <FolderPlus className="mr-1.5 h-3.5 w-3.5" />
                      {t('managed.skills.folder')}
                    </Button>
                  </div>
                )
              })()}

            {/* Name input */}
            <div>
              <label className="mb-1.5 block text-sm font-medium">
                {newFileMode === 'folder'
                  ? t('managed.skills.folderName')
                  : t('managed.skills.fileName')}
              </label>
              <Input
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                placeholder={
                  newFileMode === 'folder'
                    ? t('managed.skills.folderNamePlaceholder')
                    : t('managed.skills.fileNamePlaceholder')
                }
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newFileName.trim()) {
                    createFileMutation.mutate({
                      dir: newFileDir.trim(),
                      fileName: newFileName.trim(),
                      fileType: newFileType,
                      mode: newFileMode,
                    })
                  }
                }}
              />
            </div>

            {/* File type (only for file mode) */}
            {newFileMode === 'file' && (
              <div>
                <label className="mb-1.5 block text-sm font-medium">
                  {t('managed.skills.fileType')}
                </label>
                <Select value={newFileType} onValueChange={setNewFileType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="text">{t('managed.skills.fileTypeText')}</SelectItem>
                    <SelectItem value="markdown">{t('managed.skills.fileTypeMarkdown')}</SelectItem>
                    <SelectItem value="json">{t('managed.skills.fileTypeJSON')}</SelectItem>
                    <SelectItem value="yaml">{t('managed.skills.fileTypeYAML')}</SelectItem>
                    <SelectItem value="python">{t('managed.skills.fileTypePython')}</SelectItem>
                    <SelectItem value="javascript">{t('managed.skills.fileTypeJavaScript')}</SelectItem>
                    <SelectItem value="shell">{t('managed.skills.fileTypeShell')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Preview final path */}
            {newFileName.trim() && (
              <div className="rounded-md bg-muted/50 px-3 py-2 font-mono text-xs text-muted-foreground">
                {newFileDir ? `${newFileDir}/` : ''}
                {newFileMode === 'folder'
                  ? `${newFileName.trim()}/`
                  : ensureExtension(newFileName.trim(), newFileType)}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddFileDialog(false)}
            >
              {t('managed.skills.cancel')}
            </Button>
            <Button
              onClick={() =>
                createFileMutation.mutate({
                  dir: newFileDir.trim(),
                  fileName: newFileName.trim(),
                  fileType: newFileType,
                  mode: newFileMode,
                })
              }
              disabled={!newFileName.trim() || createFileMutation.isPending}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {newFileMode === 'folder'
                ? t('managed.skills.createFolder')
                : t('managed.skills.createFile')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete file confirmation */}
      <Dialog
        open={deleteFileTarget !== null}
        onOpenChange={(open) => !open && setDeleteFileTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.deleteFile')}</DialogTitle>
            <DialogDescription>
              {t('managed.skills.deleteFileConfirm')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteFileTarget(null)}
            >
              {t('managed.skills.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                deleteFileTarget &&
                deleteFileMutation.mutate(deleteFileTarget)
              }
              disabled={deleteFileMutation.isPending}
            >
              {t('managed.skills.deleteFile')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete folder confirmation */}
      <Dialog
        open={deleteFolderTarget !== null}
        onOpenChange={(open) => !open && setDeleteFolderTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.deleteFolder')}</DialogTitle>
            <DialogDescription>
              {t('managed.skills.deleteFolderConfirm')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteFolderTarget(null)}
            >
              {t('managed.skills.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                deleteFolderTarget &&
                deleteFolderMutation.mutate(deleteFolderTarget)
              }
              disabled={deleteFolderMutation.isPending}
            >
              {t('managed.skills.deleteFolder')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
