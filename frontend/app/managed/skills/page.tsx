'use client'

import { python } from '@codemirror/lang-python'
import { EditorView } from '@codemirror/view'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import CodeMirror from '@uiw/react-codemirror'
import {
  Plus,
  Trash2,
  ArrowLeft,
  FileText,
  FolderOpen,
  FolderPlus,
  ChevronRight,
  ChevronDown,
  Save,
  Check,
  Eye,
  Pencil,
  Camera,
  History,
  Upload,
  RefreshCw,
  Sparkles,
  GitCompare,
  X,
  ArrowUpCircle,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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
  SkillRiskScoreBadge,
  SkillSecurityBadge,
  SkillStatusBadges,
  SkillVisibilityBadge,
} from '@/components/managed/skills/skill-status-badges'
import { SkillLifecycleActions } from '@/components/managed/skills/skill-lifecycle-actions'
import { eligibilityReasonView, eligibilityActionView } from '@/lib/managed/skill-eligibility'
import {
  SkillVersionDiffView,
  type DiffViewMode,
} from '@/components/managed/skills/skill-version-diff'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/hooks/use-toast'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  currentProjectAllowsAdmin,
  useCurrentProjectReadOnly,
  useCurrentProjectIsAdmin,
} from '@/hooks/managed/use-current-project-read-only'
import { managedGet, managedPost, managedPut, managedDelete, managedUpload } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourceId, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { canOwn } from '@/lib/managed/roles'
import {
  getManagedSkillImportApiErrorMessage,
  buildManagedSkillImportFromDirectory,
  getManagedSkillImportValidationMessage,
} from '@/lib/managed/skill-import'
import { severityLabelKey } from '@/lib/managed/skill-severity'
import { diffSkillVersionFiles } from '@/lib/managed/skill-version-diff'
import type {
  SkillRecord,
  SkillFileRecord,
  SkillVersionRecord,
  SkillSecurityScanRecord,
  SessionSkillUsage,
  PromotableTier,
} from '@/types/managed'

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
  readOnly = false,
  minHeight = '360px',
  height = '420px',
}: {
  value: string
  onChange: (value: string) => void
  fileType?: string
  fileName?: string
  readOnly?: boolean
  minHeight?: string
  height?: string
}) {
  const { resolvedTheme } = useTheme()
  const editorTheme = resolvedTheme === 'dark' ? vscodeDark : 'light'

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      editable={!readOnly}
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

function SkillScanProgressNotice({ title, description }: { title: string; description: string }) {
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

/** Split a timestamp into date + time-of-day parts for the timeline axis. */
function timelineDateParts(dateStr: string, lang?: string): { date: string; time: string } {
  const locale = lang?.startsWith('zh') ? 'zh-CN' : 'en-US'
  const d = new Date(dateStr)
  return {
    date: d.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' }),
    time: d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }),
  }
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

function isSkillMutable(skill: SkillRecord | null | undefined): boolean {
  return !!skill && skill.lifecycle_status !== 'archived'
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

function getSecurityIssueSeverityDistribution(
  scan: SkillSecurityScanRecord,
): Array<{ severity: string; count: number }> {
  return [
    { severity: 'CRITICAL', count: scan.critical_count },
    { severity: 'HIGH', count: scan.high_count },
    { severity: 'MEDIUM', count: scan.medium_count },
    { severity: 'LOW', count: scan.low_count },
  ]
}

function getRawScannerRisk(
  scan: SkillSecurityScanRecord,
): { score: number | null; severity: string | null; recommendation: string | null } | null {
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
      const severity = (
        readString(issue, ['severity', 'level', 'risk', 'priority']) || 'UNKNOWN'
      ).toUpperCase()
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

/** Drag payload for a move. A file carries its real id; a folder carries its
 * ``fullPath`` (trailing ``/``). ``path`` on a file is its directory. */
type MoveSource = { kind: 'file'; id: string; path: string } | { kind: 'folder'; path: string }

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
  canEdit,
  onSelectFile,
  onDeleteFile,
  onDeleteFolder,
  onAddToFolder,
  onMove,
}: {
  node: TreeNode
  depth: number
  selectedFileId: string | null
  canEdit: boolean
  onSelectFile: (id: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  onAddToFolder: (folderPath: string) => void
  /** When provided, nodes become draggable and folders accept drops.
   * ``source`` carries a file id or a folder fullPath; ``destFolder`` is the
   * target folder's fullPath (trailing ``/``) or ``''`` for root. */
  onMove?: (source: MoveSource, destFolder: string) => void
}) {
  const [open, setOpen] = useState(true)
  const [dragOver, setDragOver] = useState(false)
  const paddingLeft = 12 + depth * 16
  const dndEnabled = canEdit && !!onMove

  if (node.file) {
    if (node.name === '.gitkeep') return null
    return (
      <div
        onClick={() => onSelectFile(node.file!.id)}
        draggable={dndEnabled}
        onDragStart={
          dndEnabled
            ? (e) => {
                e.dataTransfer.setData(
                  'text/plain',
                  JSON.stringify({
                    kind: 'file',
                    id: node.file!.id,
                    path: node.file!.path,
                  } as MoveSource),
                )
                e.dataTransfer.effectAllowed = 'move'
              }
            : undefined
        }
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
        {canEdit && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDeleteFile(node.file!.id)
            }}
            className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
    )
  }

  return (
    <>
      <div
        onClick={() => setOpen(!open)}
        draggable={dndEnabled}
        onDragStart={
          dndEnabled
            ? (e) => {
                e.stopPropagation()
                e.dataTransfer.setData(
                  'text/plain',
                  JSON.stringify({ kind: 'folder', path: node.fullPath } as MoveSource),
                )
                e.dataTransfer.effectAllowed = 'move'
              }
            : undefined
        }
        onDragOver={
          dndEnabled
            ? (e) => {
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                if (!dragOver) setDragOver(true)
              }
            : undefined
        }
        onDragLeave={dndEnabled ? () => setDragOver(false) : undefined}
        onDrop={
          dndEnabled
            ? (e) => {
                e.preventDefault()
                e.stopPropagation()
                setDragOver(false)
                try {
                  const source = JSON.parse(e.dataTransfer.getData('text/plain')) as MoveSource
                  if (source) onMove!(source, node.fullPath)
                } catch {
                  /* ignore malformed payloads */
                }
              }
            : undefined
        }
        className={`group flex cursor-pointer items-center gap-1 py-1.5 pr-3 text-muted-foreground hover:text-foreground ${
          dragOver ? 'bg-primary/10 ring-1 ring-inset ring-primary/40' : ''
        }`}
        style={{ paddingLeft }}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <FolderOpen className="h-4 w-4" />
        <span className="ml-1 flex-1">{node.name}/</span>
        {canEdit && (
          <>
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
          </>
        )}
      </div>
      {open &&
        node.children.map((child, i) => (
          <FileTreeNode
            key={child.file?.id ?? child.fullPath + i}
            node={child}
            depth={depth + 1}
            selectedFileId={selectedFileId}
            canEdit={canEdit}
            onSelectFile={onSelectFile}
            onDeleteFile={onDeleteFile}
            onDeleteFolder={onDeleteFolder}
            onAddToFolder={onAddToFolder}
            onMove={onMove}
          />
        ))}
    </>
  )
}

function SkillWorkspace({
  skillName,
  files,
  selectedFileId,
  canEdit,
  onSelectFile,
  onSelectMain,
  onAddFolder,
  onAddToFolder,
  onDeleteFile,
  onDeleteFolder,
  onMove,
  isMainSelected,
}: {
  skillName: string
  files: SkillFileRecord[]
  selectedFileId: string | null
  canEdit: boolean
  onSelectFile: (id: string) => void
  onSelectMain: () => void
  onAddFolder: () => void
  onAddToFolder: (folderPath: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  onMove?: (source: MoveSource, destFolder: string) => void
  isMainSelected: boolean
}) {
  const { t } = useTranslation()
  const [rootOpen, setRootOpen] = useState(true)
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
          disabled={!canEdit}
          onClick={onAddFolder}
          title={t('managed.skills.newFolder')}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      <div
        className="flex-1 overflow-y-auto py-1 text-sm"
        onDragOver={canEdit && onMove ? (e) => e.preventDefault() : undefined}
        onDrop={
          canEdit && onMove
            ? (e) => {
                try {
                  const source = JSON.parse(e.dataTransfer.getData('text/plain')) as MoveSource
                  if (source) onMove(source, '')
                } catch {
                  /* ignore */
                }
              }
            : undefined
        }
      >
        {/* Root node — the skill itself. SKILL.md and folders nest under it. */}
        <div
          onClick={() => setRootOpen((v) => !v)}
          className="flex cursor-pointer items-center gap-1.5 px-2 py-1.5 font-medium text-foreground transition-colors hover:bg-muted/50"
        >
          {rootOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{skillName}</span>
        </div>

        {rootOpen && (
          <>
            {/* SKILL.md -- always first, nested under the root */}
            <div
              onClick={onSelectMain}
              className={`flex cursor-pointer items-center gap-2 py-1.5 pr-3 transition-colors hover:bg-muted/50 ${
                isMainSelected ? 'bg-muted font-medium' : ''
              }`}
              style={{ paddingLeft: 28 }}
            >
              <FileText className="h-4 w-4 shrink-0 text-blue-500" />
              <span>SKILL.md</span>
            </div>

            {/* File tree — depth starts at 1 so it sits under the root */}
            {tree.children.map((child, i) => (
              <FileTreeNode
                key={child.file?.id ?? child.fullPath + i}
                node={child}
                depth={1}
                selectedFileId={selectedFileId}
                canEdit={canEdit}
                onSelectFile={onSelectFile}
                onDeleteFile={onDeleteFile}
                onDeleteFolder={onDeleteFolder}
                onAddToFolder={onAddToFolder}
                onMove={canEdit ? onMove : undefined}
              />
            ))}
          </>
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
  visibility?: string
  source_type: string
  source_url: string
}

interface SkillActionScope {
  runId: number
  scope: ManagedRequestScope
  skillId: string
}

interface ManagedActionScope {
  runId: number
  scope: ManagedRequestScope
}

interface ImportFolderVariables extends ManagedActionScope {
  fileList: File[]
}

interface ImportZipVariables extends ManagedActionScope {
  file: File
}

interface DeleteSkillVariables extends ManagedActionScope {
  id: string
}

interface SaveSkillVariables extends SkillActionScope {
  form: SkillFormState
}

interface CreateFileVariables extends SkillActionScope {
  dir: string
  fileName: string
  fileType: string
  mode: 'file' | 'folder'
}

interface SaveFileVariables extends SkillActionScope {
  fileId: string
  content: string
}

interface DeleteFileVariables extends SkillActionScope {
  fileId: string
}

interface DeleteFolderVariables extends SkillActionScope {
  folderPath: string
  filesToDelete: SkillFileRecord[]
}

interface MoveVariables extends SkillActionScope {
  source: MoveSource
  destFolder: string
  files: SkillFileRecord[]
}

interface CreateVersionVariables extends SkillActionScope {
  releaseNotes: string
  version?: string
}

function SkillEditor({
  skill,
  files,
  selectedFileId,
  canEdit,
  form,
  setForm,
  fileContent,
  setFileContent,
  versions,
  onCreateVersion,
  onDeleteVersion,
  onRestoreVersion,
  onDeleteVersionDialogActivity,
  isProjectSkillAdmin,
  isOrgOwner,
  onPromoteVersion,
  onApproveVersion,
  onRejectVersion,
  onTakedown,
  isCreatingVersion,
  editorTab,
  setEditorTab,
  showVersionForm,
  setShowVersionForm,
  queryScope,
  requestScope,
}: {
  skill: SkillRecord
  files: SkillFileRecord[]
  selectedFileId: string | null
  canEdit: boolean
  form: SkillFormState
  setForm: (f: SkillFormState) => void
  fileContent: string
  setFileContent: (c: string) => void
  versions: SkillVersionRecord[]
  onCreateVersion: (releaseNotes: string, version?: string) => void
  onDeleteVersion: (
    version: string,
    force?: boolean,
  ) => Promise<
    { ok: true } | { ok: false; referrers: Array<Record<string, unknown>>; hint?: string }
  >
  onRestoreVersion: (version: string) => Promise<boolean>
  onDeleteVersionDialogActivity: () => void
  isProjectSkillAdmin: boolean
  isOrgOwner: boolean
  onPromoteVersion: (version: string) => void
  onApproveVersion: (version: string) => void
  onRejectVersion: (version: string) => void
  onTakedown: (tier: PromotableTier) => void
  isCreatingVersion: boolean
  editorTab: 'editor' | 'metadata' | 'versions'
  setEditorTab: (tab: 'editor' | 'metadata' | 'versions') => void
  showVersionForm: boolean
  setShowVersionForm: (v: boolean) => void
  queryScope: string
  requestScope: ManagedRequestScope
}) {
  const { t, i18n } = useTranslation()
  const [contentMode, setContentMode] = useState<'edit' | 'preview'>('edit')
  const [newReleaseNotes, setNewReleaseNotes] = useState('')
  const [newVersionStr, setNewVersionStr] = useState('')
  /** Per-row delete state: keyed by version string. */
  const [deleteState, setDeleteState] = useState<{
    version: string
    referrers?: Array<Record<string, unknown>>
    hint?: string
    pending?: boolean
  } | null>(null)
  /** Per-row restore confirm: the version string pending a restore-to-draft. */
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null)
  const [restorePending, setRestorePending] = useState(false)
  const versionDeleteRunRef = useRef(0)
  /** Version-diff state — compares a version against its predecessor.
   * Rendered inline within the versions tab (not a dialog). */
  const [diffTarget, setDiffTarget] = useState<{
    fromVersion: string
    toVersion: string
  } | null>(null)
  const [diffMode, setDiffMode] = useState<DiffViewMode>('unified')

  // Fetch the FULL file snapshot of both compared versions on demand. The
  // version list only carries SKILL.md's main content, so we hit the
  // per-version files endpoint to diff the whole skill package.
  const skillIdForDiff = apiResourceId(skill.id)
  const { data: fromFiles = [] } = useQuery({
    queryKey: ['skill-version-files', queryScope, skillIdForDiff, diffTarget?.fromVersion],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillFileRecord[] } | SkillFileRecord[]>(
        apiResourcePath('skills', skillIdForDiff, 'versions', diffTarget!.fromVersion, 'files'),
        managedRequestOptions(requestScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!diffTarget,
  })
  const { data: toFiles = [], isFetching: toFilesFetching } = useQuery({
    queryKey: ['skill-version-files', queryScope, skillIdForDiff, diffTarget?.toVersion],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillFileRecord[] } | SkillFileRecord[]>(
        apiResourcePath('skills', skillIdForDiff, 'versions', diffTarget!.toVersion, 'files'),
        managedRequestOptions(requestScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!diffTarget,
  })
  const versionDiff = useMemo(
    () => (diffTarget ? diffSkillVersionFiles(fromFiles, toFiles) : null),
    [diffTarget, fromFiles, toFiles],
  )
  const diffLoading = !!diffTarget && toFilesFetching

  const selectedFile = files.find((f) => f.id === selectedFileId)
  const isEditingFile = selectedFileId !== null && selectedFile !== undefined

  const markVersionDeleteDialogActivity = useCallback(() => {
    versionDeleteRunRef.current += 1
    onDeleteVersionDialogActivity()
  }, [onDeleteVersionDialogActivity])

  const openDeleteVersionDialog = useCallback(
    (version: string) => {
      if (!canEdit) return
      markVersionDeleteDialogActivity()
      setDeleteState({ version })
    },
    [canEdit, markVersionDeleteDialogActivity],
  )

  const closeDeleteVersionDialog = useCallback(() => {
    markVersionDeleteDialogActivity()
    setDeleteState(null)
  }, [markVersionDeleteDialogActivity])

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Tab bar */}
      <Tabs
        value={editorTab}
        onValueChange={(v) => setEditorTab(v as 'editor' | 'metadata' | 'versions')}
      >
        <div className="flex items-center justify-between border-b border-border pr-3">
          <TabsList>
            <TabsTrigger value="editor">{t('managed.skills.editor')}</TabsTrigger>
            <TabsTrigger value="metadata">{t('managed.skills.metadata')}</TabsTrigger>
            <TabsTrigger value="versions">{t('managed.skills.versionHistory')}</TabsTrigger>
          </TabsList>
        </div>
      </Tabs>

      {/* Tab content */}
      {editorTab === 'editor' && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {isEditingFile ? (
            <div className="flex h-full min-h-0 flex-col overflow-hidden">
              <div className="shrink-0 border-b border-border bg-muted/10 px-4 py-2 text-xs text-muted-foreground">
                <FileText className="mr-1 inline h-3 w-3" />
                {selectedFile.path}
                {selectedFile.file_name}
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                <SkillCodeEditor
                  value={fileContent}
                  onChange={setFileContent}
                  fileType={selectedFile.file_type}
                  fileName={selectedFile.file_name}
                  readOnly={!canEdit}
                  minHeight="400px"
                  height="100%"
                />
              </div>
            </div>
          ) : (
            /* SKILL.md — full-width, flush with the pane (no centered card),
               matching the sub-file editor. Metadata lives in its own tab. */
            <div className="flex h-full min-h-0 flex-col overflow-hidden">
              <div className="flex shrink-0 items-center justify-between border-b border-border bg-muted/10 px-4 py-2">
                <span className="flex items-center text-xs text-muted-foreground">
                  <FileText className="mr-1 inline h-3 w-3" />
                  SKILL.md
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

              <div className="min-h-0 flex-1 overflow-hidden">
                {contentMode === 'edit' ? (
                  <SkillCodeEditor
                    value={form.content}
                    onChange={(value) => setForm({ ...form, content: value })}
                    fileType="markdown"
                    fileName="SKILL.md"
                    readOnly={!canEdit}
                    minHeight="100%"
                    height="100%"
                  />
                ) : (
                  <div className="h-full overflow-y-auto bg-background p-6">
                    {form.content ? (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{form.content}</ReactMarkdown>
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

      {editorTab === 'metadata' && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="w-full space-y-5 overflow-y-auto p-6">
            {/* Name + License + Visibility row */}
            <div className="grid grid-cols-[1fr,200px,200px] gap-4">
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
                  disabled={!canEdit}
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
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, license: e.target.value })}
                  placeholder="MIT"
                  className="h-8 text-sm"
                />
              </div>
              {/* Visibility is read-only here: a skill starts as a project
                  resource and is only exposed to the organization / public
                  tiers through the version-level promotion approval flow
                  (see the Versions tab). */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  {t('managed.skills.visibility.label')}
                </label>
                <div className="flex h-8 items-center gap-2">
                  <SkillVisibilityBadge visibility={form.visibility || 'project'} />
                  <span className="text-xs text-muted-foreground">
                    {t('managed.skills.visibility.managedByPromotion')}
                  </span>
                  {isOrgOwner && skill.visibility === 'public' && (
                    <button
                      type="button"
                      onClick={() => onTakedown('public')}
                      className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                    >
                      {t('managed.skills.promotion.takedownPublic')}
                    </button>
                  )}
                  {isOrgOwner && skill.visibility === 'organization' && (
                    <button
                      type="button"
                      onClick={() => onTakedown('organization')}
                      className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                    >
                      {t('managed.skills.promotion.takedownOrg')}
                    </button>
                  )}
                </div>
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
                disabled={!canEdit}
                onChange={(e) =>
                  setForm({
                    ...form,
                    description: e.target.value.slice(0, 1024),
                  })
                }
                placeholder={t('managed.skills.descriptionPlaceholder')}
                rows={8}
                className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            {/* Tags */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                {t('managed.skills.tags')}
              </label>
              <Input
                value={form.tags}
                disabled={!canEdit}
                onChange={(e) => setForm({ ...form, tags: e.target.value })}
                placeholder={t('managed.skills.tagsPlaceholder')}
                className="h-8 text-sm"
              />
            </div>
          </div>
        </div>
      )}

      {editorTab === 'versions' && (
        <div className="flex-1 overflow-y-auto p-4">
          {diffTarget ? (
            <div className="w-full">
              {/* Diff header: back + title + view toggle */}
              <div className="mb-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDiffTarget(null)}
                  className="flex items-center gap-1 rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <ArrowLeft className="h-4 w-4" />
                  {t('managed.skills.diffBackToVersions')}
                </button>
                <div className="flex items-center gap-2 font-mono text-sm">
                  <span className="rounded bg-muted px-1.5 py-0.5">
                    {formatVersion(diffTarget.fromVersion)}
                  </span>
                  <span className="text-muted-foreground">→</span>
                  <span className="rounded bg-muted px-1.5 py-0.5">
                    {formatVersion(diffTarget.toVersion)}
                  </span>
                </div>
                {/* Unified / Split toggle */}
                <div className="ml-auto flex items-center gap-px rounded-md bg-muted p-0.5">
                  {(['unified', 'split'] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setDiffMode(m)}
                      className={`rounded px-2.5 py-1 text-xs transition-colors ${
                        diffMode === m
                          ? 'bg-background font-medium text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {m === 'unified'
                        ? t('managed.skills.diffViewUnified')
                        : t('managed.skills.diffViewSplit')}
                    </button>
                  ))}
                </div>
              </div>

              {diffLoading ? (
                <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  {t('common.loading')}
                </div>
              ) : versionDiff ? (
                <>
                  {/* Summary bar */}
                  <div className="mb-2.5 flex items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-1.5 font-mono text-xs">
                    <span className="text-muted-foreground">
                      {t('managed.skills.versionDiffFilesChanged', {
                        count: versionDiff.changedCount,
                      })}
                    </span>
                    <span className="ml-auto flex items-center gap-2">
                      <span className="text-green-600 dark:text-green-400">
                        +{versionDiff.totalAdded}
                      </span>
                      <span className="text-red-600 dark:text-red-400">
                        −{versionDiff.totalRemoved}
                      </span>
                    </span>
                  </div>
                  <SkillVersionDiffView diff={versionDiff} mode={diffMode} />
                </>
              ) : null}
            </div>
          ) : (
            <div className="max-w-4xl">
              {versions.length > 0 && (
                <div className="mb-3 flex items-center gap-2">
                  <History className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-foreground">
                    {t('managed.skills.versionHistory')}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    {versions.length}
                  </span>
                </div>
              )}

              {versions.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-16 text-center">
                  <History className="h-8 w-8 text-muted-foreground/30" />
                  <p className="text-sm text-muted-foreground">{t('managed.skills.noVersions')}</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {versions.map((v, idx) => (
                    <div key={v.id} className="flex gap-3">
                      {/* Time column — the timeline axis */}
                      <div className="w-24 shrink-0 pt-[13px] text-right leading-tight">
                        <div className="text-xs font-medium text-foreground/80">
                          {timelineDateParts(v.created_at, i18n.language).date}
                        </div>
                        <div className="text-[11px] tabular-nums text-muted-foreground/60">
                          {timelineDateParts(v.created_at, i18n.language).time}
                        </div>
                      </div>
                      {/* Rail + node */}
                      <div className="relative flex w-3 shrink-0 justify-center">
                        {idx < versions.length - 1 && (
                          <span className="absolute bottom-[-12px] top-6 w-px bg-border" />
                        )}
                        <span
                          className={`absolute top-[15px] flex h-3.5 w-3.5 items-center justify-center rounded-full ring-4 ring-background ${
                            idx === 0 ? 'bg-primary' : 'bg-muted-foreground/30'
                          }`}
                        >
                          {idx === 0 && <span className="h-1.5 w-1.5 rounded-full bg-background" />}
                        </span>
                      </div>
                      {/* Content card */}
                      <div
                        className={`group relative min-w-0 flex-1 overflow-hidden rounded-xl border bg-card p-4 transition-all hover:shadow-md ${
                          idx === 0
                            ? 'border-primary/40 bg-gradient-to-br from-primary/[0.04] to-transparent'
                            : 'border-border/60 hover:border-border'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 font-mono text-sm font-semibold text-foreground">
                              {formatVersion(v.version)}
                            </span>
                            {idx === 0 && (
                              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                                latest
                              </span>
                            )}
                            {v.lifecycle_status === 'pending_review' && (
                              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                                {t('managed.skills.promotion.pendingFor', {
                                  tier: t(
                                    `managed.skills.visibility.${v.review_target_visibility || 'organization'}`,
                                  ),
                                })}
                              </span>
                            )}
                            {v.lifecycle_status === 'rejected' && (
                              <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-destructive">
                                {t('managed.skills.promotion.rejected')}
                              </span>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            {v.lifecycle_status === 'pending_review' && isOrgOwner && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => onApproveVersion(v.version)}
                                  className="flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100"
                                >
                                  <Check className="h-3.5 w-3.5" />
                                  {t('managed.skills.promotion.approve')}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => onRejectVersion(v.version)}
                                  className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                                >
                                  <X className="h-3.5 w-3.5" />
                                  {t('managed.skills.promotion.reject')}
                                </button>
                              </>
                            )}
                            {v.lifecycle_status !== 'pending_review' && isProjectSkillAdmin && (
                              <button
                                type="button"
                                onClick={() => onPromoteVersion(v.version)}
                                className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary"
                              >
                                <ArrowUpCircle className="h-3.5 w-3.5" />
                                {t('managed.skills.promotion.submit')}
                              </button>
                            )}
                            {idx < versions.length - 1 && (
                              <button
                                type="button"
                                aria-label={t('managed.skills.compareWithPrevious')}
                                title={t('managed.skills.compareWithPrevious')}
                                onClick={() =>
                                  setDiffTarget({
                                    fromVersion: versions[idx + 1].version,
                                    toVersion: v.version,
                                  })
                                }
                                className="border-border/60 flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary"
                              >
                                <GitCompare className="h-3.5 w-3.5" />
                                {t('managed.skills.compareWithPrevious')}
                              </button>
                            )}
                            <button
                              type="button"
                              aria-label={t('managed.skills.restoreVersion')}
                              title={t('managed.skills.restoreVersion')}
                              onClick={() => setRestoreTarget(v.version)}
                              disabled={!canEdit}
                              className="rounded-md p-1.5 text-muted-foreground/50 opacity-0 transition-all hover:bg-primary/10 hover:text-primary disabled:cursor-not-allowed disabled:opacity-30 group-hover:opacity-100"
                            >
                              <History className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              aria-label={t('managed.skills.deleteVersion', 'Delete version')}
                              title={t('managed.skills.deleteVersion', 'Delete version')}
                              onClick={() => openDeleteVersionDialog(v.version)}
                              disabled={!canEdit}
                              className="rounded-md p-1.5 text-muted-foreground/50 opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-30 group-hover:opacity-100"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                        {v.release_notes && (
                          <p className="border-border/50 mt-2.5 whitespace-pre-wrap border-l-2 pl-3 text-sm text-muted-foreground">
                            {v.release_notes}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Restore-version confirm: restoring replaces the current draft with the
          selected version's contents, so gate it behind an explicit confirm. */}
      <Dialog
        open={!!restoreTarget}
        onOpenChange={(open) => !open && !restorePending && setRestoreTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t('managed.skills.restoreVersionTitle', 'Restore version v{{v}}', {
                v: restoreTarget ? formatVersion(restoreTarget) : '',
              })}
            </DialogTitle>
            <DialogDescription>{t('managed.skills.restoreVersionConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRestoreTarget(null)}
              disabled={restorePending}
            >
              {t('common.cancel')}
            </Button>
            <Button
              onClick={async () => {
                if (!restoreTarget) return
                setRestorePending(true)
                try {
                  const ok = await onRestoreVersion(restoreTarget)
                  if (ok) setRestoreTarget(null)
                } finally {
                  setRestorePending(false)
                }
              }}
              disabled={restorePending}
            >
              {t('managed.skills.restore')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish version dialog — mounted at SkillEditor top level so it works
          from any tab (the entry button lives in the global action bar). */}
      <Dialog
        open={showVersionForm}
        onOpenChange={(open) => {
          if (!open) {
            setShowVersionForm(false)
            setNewReleaseNotes('')
            setNewVersionStr('')
          }
        }}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Camera className="h-4 w-4 text-primary" />
              {t('managed.skills.createVersionBtn')}
            </DialogTitle>
          </DialogHeader>
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
                <div className="space-y-3 py-2">
                  <div>
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
                          : t('managed.skills.versionFirstHint', 'Leave empty to start at v0.1.0.')}
                    </div>
                  </div>
                  <textarea
                    value={newReleaseNotes}
                    onChange={(e) => setNewReleaseNotes(e.target.value)}
                    placeholder={t('managed.skills.releaseNotesPlaceholder')}
                    rows={3}
                    className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowVersionForm(false)
                      setNewReleaseNotes('')
                      setNewVersionStr('')
                    }}
                  >
                    {t('managed.skills.cancel')}
                  </Button>
                  <Button
                    disabled={!canEdit || isCreatingVersion || !semverOk}
                    onClick={() => {
                      if (!canEdit) return
                      onCreateVersion(newReleaseNotes.trim(), trimmed || undefined)
                      setShowVersionForm(false)
                      setNewReleaseNotes('')
                      setNewVersionStr('')
                    }}
                  >
                    <Camera className="mr-1 h-4 w-4" />
                    {t('managed.skills.createVersionBtn')}
                  </Button>
                </DialogFooter>
              </>
            )
          })()}
        </DialogContent>
      </Dialog>

      {/* Delete version dialog (handles 409 SKILL_VERSION_IN_USE with force-confirm) */}
      <Dialog
        open={!!deleteState}
        onOpenChange={(open) => {
          if (!open) closeDeleteVersionDialog()
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
            <Button variant="outline" onClick={closeDeleteVersionDialog}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={!canEdit || deleteState?.pending}
              onClick={async () => {
                if (!deleteState) return
                const force = (deleteState.referrers?.length ?? 0) > 0
                if (!canEdit) return
                const runId = versionDeleteRunRef.current + 1
                versionDeleteRunRef.current = runId
                setDeleteState({ ...deleteState, pending: true })
                const res = await onDeleteVersion(deleteState.version, force)
                if (versionDeleteRunRef.current !== runId) return
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

export function SkillManagerPageContent({
  initialSkillId = null,
}: {
  initialSkillId?: string | null
}) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const router = useRouter()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  // Promotion gating: submitting a version for promotion needs project ADMIN
  // capability; approving / rejecting / taking down needs the org OWNER role
  // (the backend enforces both — these just drive which controls render).
  const isProjectSkillAdmin = useCurrentProjectIsAdmin()
  const isOrgOwner = canOwn(
    useProjectStore((s) => s.organizations.find((o) => o.id === s.currentOrgId)?.role),
  )

  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(initialSkillId)
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  // Which workspace tab is active. Lifted here (out of SkillEditor) so the
  // header's Save button can decide what to persist: on the Metadata tab
  // we always save the skill-level form, regardless of which file happens
  // to be selected in the tree.
  const [editorTab, setEditorTab] = useState<'editor' | 'metadata' | 'versions'>('editor')
  // Lifted so the "publish version" button can live in the top-right action
  // group while the form itself renders inside SkillEditor's versions tab.
  const [showVersionForm, setShowVersionForm] = useState(false)
  // Promotion dialogs: which version is being promoted (tier picker) / rejected
  // (reason input).
  const [promoteTarget, setPromoteTarget] = useState<string | null>(null)
  const [rejectTarget, setRejectTarget] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showAddFileDialog, setShowAddFileDialog] = useState(false)
  const [newFileMode, setNewFileMode] = useState<'file' | 'folder'>('file')
  const [newFileDir, setNewFileDir] = useState('')
  const [newFileName, setNewFileName] = useState('')
  const [newFileType, setNewFileType] = useState('text')
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [deleteFileTarget, setDeleteFileTarget] = useState<string | null>(null)
  const [deleteFolderTarget, setDeleteFolderTarget] = useState<string | null>(null)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [showSecurityHistoryDialog, setShowSecurityHistoryDialog] = useState(false)
  const [showRuntimeStatsDialog, setShowRuntimeStatsDialog] = useState(false)
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
    visibility: 'project',
    source_type: '',
    source_url: '',
  })
  const [formSnapshot, setFormSnapshot] = useState<SkillFormState>(form)
  const [fileContent, setFileContent] = useState('')
  const [fileContentSnapshot, setFileContentSnapshot] = useState('')
  const managedScopeRef = useRef(managedScope)
  const selectedSkillIdRef = useRef<string | null>(selectedSkillId)
  const selectedFileIdRef = useRef<string | null>(selectedFileId)
  const mutationRunRef = useRef(0)

  const clearSavedFlash = useCallback(() => {
    if (flashTimer.current) {
      clearTimeout(flashTimer.current)
      flashTimer.current = undefined
    }
    setSavedFlash(false)
  }, [])

  const backToSkillList = useCallback(() => {
    mutationRunRef.current += 1
    selectedSkillIdRef.current = null
    selectedFileIdRef.current = null
    clearSavedFlash()
    setSelectedSkillId(null)
    setSelectedFileId(null)
    router.push('/managed/skills')
  }, [clearSavedFlash, router])

  // Reset the detail tab whenever the open skill changes, so the previously
  // selected tab doesn't persist onto an unrelated skill. Also close any open
  // promotion dialog — its target version belongs to the old skill.
  useEffect(() => {
    setEditorTab('editor')
    setPromoteTarget(null)
    setRejectTarget(null)
  }, [selectedSkillId])

  useEffect(
    () => () => {
      mutationRunRef.current += 1
      selectedSkillIdRef.current = null
      selectedFileIdRef.current = null
      if (flashTimer.current) {
        clearTimeout(flashTimer.current)
      }
    },
    [],
  )

  useEffect(() => {
    selectedSkillIdRef.current = selectedSkillId
  }, [selectedSkillId])

  useEffect(() => {
    selectedFileIdRef.current = selectedFileId
  }, [selectedFileId])

  useEffect(() => {
    managedScopeRef.current = managedScope
    mutationRunRef.current += 1
    selectedSkillIdRef.current = initialSkillId
    selectedFileIdRef.current = null
    setSelectedSkillId(initialSkillId)
    setSelectedFileId(null)
    setShowVersionForm(false)
    setShowAddFileDialog(false)
    setDeleteTarget(null)
    setDeleteFileTarget(null)
    setDeleteFolderTarget(null)
    setShowImportDialog(false)
    setShowSecurityHistoryDialog(false)
    clearSavedFlash()
    setFileContent('')
    setFileContentSnapshot('')
  }, [managedScope.key, initialSkillId, clearSavedFlash])

  const getCurrentManagedScope = useCallback(() => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }, [])

  const currentManagedScopeIsActive = useCallback(
    (scope = managedScopeRef.current.key) =>
      managedScopeRef.current.key === scope && getCurrentManagedScope() === scope,
    [getCurrentManagedScope],
  )

  const currentManagedScopeAllowsWrite = useCallback(
    (scope = managedScopeRef.current.key) =>
      currentManagedScopeIsActive(scope) && currentProjectAllowsWrite(),
    [currentManagedScopeIsActive],
  )

  const nextSkillAction = useCallback((): SkillActionScope | null => {
    if (!currentManagedScopeAllowsWrite()) return null
    const skillId = selectedSkillIdRef.current
    if (!skillId) return null
    const runId = mutationRunRef.current + 1
    mutationRunRef.current = runId
    return {
      runId,
      scope: managedScopeRef.current,
      skillId,
    }
  }, [currentManagedScopeAllowsWrite])

  const isCurrentSkillAction = useCallback(
    (action: SkillActionScope): boolean => {
      return (
        mutationRunRef.current === action.runId &&
        currentManagedScopeAllowsWrite(action.scope.key) &&
        selectedSkillIdRef.current === action.skillId
      )
    },
    [currentManagedScopeAllowsWrite],
  )

  const nextManagedAction = useCallback((): ManagedActionScope | null => {
    if (!currentManagedScopeAllowsWrite()) return null
    const runId = mutationRunRef.current + 1
    mutationRunRef.current = runId
    return {
      runId,
      scope: managedScopeRef.current,
    }
  }, [currentManagedScopeAllowsWrite])

  const isCurrentManagedAction = useCallback(
    (action: ManagedActionScope): boolean => {
      return (
        mutationRunRef.current === action.runId && currentManagedScopeAllowsWrite(action.scope.key)
      )
    },
    [currentManagedScopeAllowsWrite],
  )

  const currentSkillInList = useCallback(
    (skillId: string | null) => {
      if (!skillId) return null
      if (!currentManagedScopeIsActive()) return null
      return (
        queryClient
          .getQueriesData<{ data?: SkillRecord[] }>({
            queryKey: ['skills', managedScopeRef.current.key, '/skills'],
          })
          .flatMap(([, page]) => page?.data ?? [])
          .find((skill) => skill.id === skillId) ?? null
      )
    },
    [currentManagedScopeIsActive, queryClient],
  )

  const currentSkillDetail = useCallback(
    (skillId: string | null) => {
      if (!skillId) return null
      if (!currentManagedScopeIsActive()) return null
      return (
        queryClient.getQueryData<SkillRecord>(['skill', managedScopeRef.current.key, skillId]) ??
        null
      )
    },
    [currentManagedScopeIsActive, queryClient],
  )

  const nextCurrentSkillAction = useCallback((): SkillActionScope | null => {
    const action = nextSkillAction()
    if (!action) return null
    return currentSkillInList(action.skillId) ? action : null
  }, [currentSkillInList, nextSkillAction])

  const nextCurrentMutableSkillAction = useCallback((): SkillActionScope | null => {
    if (!currentProjectAllowsWrite()) return null
    const action = nextSkillAction()
    if (!action) return null
    const listSkill = currentSkillInList(action.skillId)
    if (!isSkillMutable(listSkill)) return null
    const detailSkill = currentSkillDetail(action.skillId)
    if (detailSkill && !isSkillMutable(detailSkill)) return null
    return action
  }, [currentSkillDetail, currentSkillInList, nextSkillAction])

  const currentSkillFiles = useCallback(
    (skillId = selectedSkillIdRef.current) => {
      if (!skillId) return []
      if (!currentManagedScopeIsActive()) return []
      return (
        queryClient.getQueryData<SkillFileRecord[]>([
          'skill-files',
          managedScopeRef.current.key,
          skillId,
        ]) ?? []
      )
    },
    [currentManagedScopeIsActive, queryClient],
  )

  const currentSkillFile = useCallback(
    (fileId: string | null, skillId = selectedSkillIdRef.current) => {
      if (!fileId || !skillId) return null
      return currentSkillFiles(skillId).find((file) => file.id === fileId) ?? null
    },
    [currentSkillFiles],
  )

  const currentFolderFiles = useCallback(
    (folderPath: string | null, skillId = selectedSkillIdRef.current) => {
      if (!folderPath || !skillId) return []
      return currentSkillFiles(skillId).filter((file) => file.path.startsWith(folderPath))
    },
    [currentSkillFiles],
  )

  const currentSkillVersion = useCallback(
    (version: string | null, skillId = selectedSkillIdRef.current) => {
      if (!version || !skillId) return null
      if (!currentManagedScopeIsActive()) return null
      const currentVersions =
        queryClient.getQueryData<SkillVersionRecord[]>([
          'skill-versions',
          managedScopeRef.current.key,
          skillId,
        ]) ?? []
      return currentVersions.find((item) => item.version === version) ?? null
    },
    [currentManagedScopeIsActive, queryClient],
  )

  const invalidateSkillResources = useCallback(
    (skillId: string, scopeKey = managedScopeRef.current.key) => {
      queryClient.invalidateQueries({ queryKey: ['skills', scopeKey] })
      queryClient.invalidateQueries({ queryKey: ['skill', scopeKey, skillId] })
      queryClient.invalidateQueries({ queryKey: ['skill-files', scopeKey, skillId] })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', scopeKey, skillId],
      })
    },
    [queryClient],
  )

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

  const {
    data: selectedSkill,
    isError: selectedSkillIsError,
    error: selectedSkillError,
  } = useQuery({
    queryKey: ['skill', managedScope.key, selectedSkillId],
    queryFn: () =>
      managedGet<SkillRecord>(
        apiResourcePath('skills', selectedSkillId!),
        managedRequestOptions(managedScope),
      ),
    enabled: !!selectedSkillId && hasManagedRequestScope(managedScope),
    // While a security scan is running in the background (rescan dispatches
    // async because LLM analysis is slow), poll the skill so the security
    // badge / score refresh automatically once the verdict lands.
    refetchInterval: (query) => {
      const data = query.state.data as SkillRecord | undefined
      return data?.security_scan?.status === 'scanning' ? 3000 : false
    },
  })

  // When the detail query's security scan transitions from "scanning" to a
  // terminal status, sync the list cache so the left-side badge updates.
  const prevSecurityStatusRef = useRef<string | undefined>(undefined)
  useEffect(() => {
    const status = selectedSkill?.security_scan?.status
    const prev = prevSecurityStatusRef.current
    prevSecurityStatusRef.current = status
    if (prev === 'scanning' && status && status !== 'scanning') {
      queryClient.invalidateQueries({ queryKey: ['skills', managedScope.key] })
    }
  }, [selectedSkill?.security_scan?.status, queryClient, managedScope.key])

  const { data: skillFiles = [] } = useQuery({
    queryKey: ['skill-files', managedScope.key, selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillFileRecord[] } | SkillFileRecord[]>(
        apiResourcePath('skills', selectedSkillId!, 'files'),
        managedRequestOptions(managedScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId && hasManagedRequestScope(managedScope),
  })

  const { data: versions = [] } = useQuery({
    queryKey: ['skill-versions', managedScope.key, selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillVersionRecord[] } | SkillVersionRecord[]>(
        apiResourceSubpath('skills', selectedSkillId!, ['versions'], { limit: 50 }),
        managedRequestOptions(managedScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId && hasManagedRequestScope(managedScope),
  })

  // Files of the latest published version — used to detect "unpublished
  // changes" across the WHOLE package (SKILL.md + sub-files), not just the
  // main content. Only fetched when at least one version exists.
  const latestPublishedVersion = versions.length > 0 ? versions[0].version : null
  const { data: latestVersionFiles = [] } = useQuery({
    queryKey: ['skill-version-files', managedScope.key, selectedSkillId, latestPublishedVersion],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillFileRecord[] } | SkillFileRecord[]>(
        apiResourcePath('skills', selectedSkillId!, 'versions', latestPublishedVersion!, 'files'),
        managedRequestOptions(managedScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId && !!latestPublishedVersion && hasManagedRequestScope(managedScope),
  })

  const {
    data: securityScans = [],
    isFetching: securityScansFetching,
    isError: securityScansIsError,
  } = useQuery({
    queryKey: ['skill-security-scans', managedScope.key, selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SkillSecurityScanRecord[] } | SkillSecurityScanRecord[]>(
        apiResourceSubpath('skills', selectedSkillId!, ['security-scans'], { limit: 20 }),
        managedRequestOptions(managedScope),
      )
      return Array.isArray(res) ? res : res.data || []
    },
    enabled: !!selectedSkillId && showSecurityHistoryDialog && hasManagedRequestScope(managedScope),
  })

  const { data: recentSkillUsage = [] } = useQuery({
    queryKey: ['skill-usage', managedScope.key, selectedSkillId],
    queryFn: async () => {
      const res = await managedGet<{ data: SessionSkillUsage[] }>(
        apiResourceSubpath('skills', selectedSkillId!, ['usage'], { limit: 5 }),
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: !!selectedSkillId && hasManagedRequestScope(managedScope),
  })
  const currentTargetHash = selectedSkill?.security_scan?.target_hash || null
  const { data: targetHashUsage = [] } = useQuery({
    queryKey: ['skill-usage-search', managedScope.key, currentTargetHash],
    queryFn: async () => {
      const res = await managedGet<{ data: SessionSkillUsage[] }>(
        apiResourceSubpath('skills', 'usage', ['search'], {
          limit: 5,
          target_hash: currentTargetHash,
        }),
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: !!currentTargetHash && hasManagedRequestScope(managedScope),
  })

  // -- Load skill into form --

  const loadSkillIntoForm = useCallback((skill: SkillRecord) => {
    const tagsStr = Array.isArray(skill.tags) ? (skill.tags as string[]).join(', ') : ''
    const newForm: SkillFormState = {
      name: skill.name || '',
      description: skill.description || '',
      content: skill.content || '',
      license: skill.license || '',
      tags: tagsStr,
      visibility: skill.visibility || 'project',
      source_type: skill.source_type || '',
      source_url: skill.source_url || '',
    }
    setForm(newForm)
    setFormSnapshot(newForm)
  }, [])

  const prevSkillRef = useState<string | null>(null)
  if (selectedSkill && selectedSkillId && prevSkillRef[0] !== selectedSkillId) {
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
        selectedFileIdRef.current = skillMd.id
        setSelectedFileId(skillMd.id)
        setFileContent(skillMd.content || '')
        setFileContentSnapshot(skillMd.content || '')
      }
    }
  }, [skillFiles, selectedFileId])

  const isDirty = JSON.stringify(form) !== JSON.stringify(formSnapshot)
  const isFileDirty = fileContent !== fileContentSnapshot

  // "Unpublished changes" — the current skill package (all files, not just
  // SKILL.md) differs from the latest published version snapshot. We diff the
  // live saved files against the version's files, and additionally compare the
  // live form content so unsaved SKILL.md edits count too.
  const latestVersion = versions.length > 0 ? versions[0] : null
  const hasUnpublishedChanges = useMemo(() => {
    if (!latestVersion) return false
    // Unsaved edit to the main doc vs the published snapshot.
    if ((form.content || '') !== (latestVersion.content || '')) return true
    // Any file added / removed / modified across the whole package.
    if (latestVersionFiles.length > 0 || skillFiles.length > 0) {
      const d = diffSkillVersionFiles(latestVersionFiles, skillFiles)
      if (d.changedCount > 0) return true
    }
    return false
  }, [latestVersion, form.content, latestVersionFiles, skillFiles])

  // High-risk gate — a skill blocked by the security scan cannot be published
  // (the backend rejects it too; this disables the entry points client-side).
  const securityBlocked = selectedSkill?.security_scan?.status === 'blocked'

  // -- Saved flash helper --

  const triggerFlash = useCallback(() => {
    setSavedFlash(true)
    if (flashTimer.current) clearTimeout(flashTimer.current)
    flashTimer.current = setTimeout(() => {
      setSavedFlash(false)
      flashTimer.current = undefined
    }, 2000)
  }, [])

  // -- Mutations --

  const importFolderMutation = useMutation({
    mutationFn: async (variables: ImportFolderVariables) => {
      if (!isCurrentManagedAction(variables)) {
        throw new Error('Stale skill folder import ignored')
      }
      const { fileList } = variables
      const result = await buildManagedSkillImportFromDirectory(fileList)
      if (!result.valid || !result.skillData) {
        throw new Error(getManagedSkillImportValidationMessage(result.validation, fileList, t))
      }
      if (!isCurrentManagedAction(variables)) {
        throw new Error('Stale skill folder import ignored')
      }
      return managedPost<SkillRecord>('/skills', result.skillData, {
        ...managedRequestOptions(variables.scope),
        timeout: SKILL_SCAN_TIMEOUT_MS,
      })
    },
    onSuccess: (skill, variables) => {
      if (!isCurrentManagedAction(variables)) return
      queryClient.invalidateQueries({ queryKey: ['skills', variables.scope.key] })
      mutationRunRef.current += 1
      selectedSkillIdRef.current = skill.id
      selectedFileIdRef.current = null
      setSelectedSkillId(skill.id)
      setSelectedFileId(null)
      toast({ title: t('managed.skills.localImportSuccess') })
    },
    onError: (error, variables) => {
      if (!isCurrentManagedAction(variables)) return
      console.error('Failed to import skill folder:', error)
      toast({
        variant: 'destructive',
        title: t('common.operationFailed'),
        description: getManagedSkillImportApiErrorMessage(error, t),
      })
    },
  })

  const importZipMutation = useMutation({
    mutationFn: (variables: ImportZipVariables) => {
      if (!isCurrentManagedAction(variables)) {
        throw new Error('Stale skill zip import ignored')
      }
      const formData = new FormData()
      formData.append('file', variables.file)
      return managedUpload<SkillRecord>(
        '/skills/import-zip',
        formData,
        managedRequestOptions(variables.scope),
      )
    },
    onSuccess: (skill, variables) => {
      if (!isCurrentManagedAction(variables)) return
      queryClient.invalidateQueries({ queryKey: ['skills', variables.scope.key] })
      mutationRunRef.current += 1
      selectedSkillIdRef.current = skill.id
      selectedFileIdRef.current = null
      setSelectedSkillId(skill.id)
      setSelectedFileId(null)
      toast({ title: t('managed.skills.zipImportSuccess') })
    },
    onError: (error, variables) => {
      if (!isCurrentManagedAction(variables)) return
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
        const action = nextManagedAction()
        if (action) importFolderMutation.mutate({ ...action, fileList })
      }
      event.target.value = ''
    },
    [importFolderMutation, nextManagedAction],
  )

  const handleZipImportChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (file) {
        const action = nextManagedAction()
        if (action) importZipMutation.mutate({ ...action, file })
      }
      event.target.value = ''
    },
    [importZipMutation, nextManagedAction],
  )

  const saveMutation = useMutation({
    mutationFn: (variables: SaveSkillVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill save ignored')
      }
      const { form, skillId } = variables
      const tags = form.tags
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      return managedPut<SkillRecord>(
        apiResourcePath('skills', skillId),
        {
          name: form.name,
          description: form.description,
          content: form.content,
          license: form.license,
          tags,
          source_type: form.source_type,
          source_url: form.source_url,
        },
        {
          ...managedRequestOptions(variables.scope),
          timeout: SKILL_SCAN_TIMEOUT_MS,
        },
      )
    },
    onSuccess: (updated, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
      loadSkillIntoForm(updated)
      triggerFlash()
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (variables: DeleteSkillVariables) => {
      if (!isCurrentManagedAction(variables)) {
        throw new Error('Stale skill delete ignored')
      }
      return managedDelete(
        apiResourcePath('skills', variables.id),
        managedRequestOptions(variables.scope),
      )
    },
    onSuccess: (_result, variables) => {
      if (!isCurrentManagedAction(variables)) return
      queryClient.invalidateQueries({ queryKey: ['skills', variables.scope.key] })
      if (selectedSkillIdRef.current === variables.id) {
        selectedSkillIdRef.current = null
        selectedFileIdRef.current = null
        setSelectedSkillId(null)
        setSelectedFileId(null)
      }
      setDeleteTarget(null)
    },
    onError: (error, variables) => {
      if (!isCurrentManagedAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const createFileMutation = useMutation({
    mutationFn: (variables: CreateFileVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill file create ignored')
      }
      const { dir, fileName, fileType, mode, skillId } = variables
      const cleanDir = dir.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
      let path: string
      let name: string

      if (mode === 'folder') {
        const depth = cleanDir ? cleanDir.split('/').filter(Boolean).length + 1 : 1
        if (depth > MAX_FOLDER_DEPTH) {
          return Promise.reject(new Error(`Folder nesting limited to ${MAX_FOLDER_DEPTH} levels`))
        }
        path = cleanDir ? `${cleanDir}/${fileName}/` : `${fileName}/`
        name = '.gitkeep'
      } else {
        path = cleanDir ? `${cleanDir}/` : ''
        name = ensureExtension(fileName, fileType)
      }

      return managedPost<SkillFileRecord>(
        apiResourcePath('skills', skillId, 'files'),
        {
          path,
          file_name: name,
          file_type: fileType,
          content: '',
        },
        {
          ...managedRequestOptions(variables.scope),
          timeout: SKILL_SCAN_TIMEOUT_MS,
        },
      )
    },
    onSuccess: (_file, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
      if (variables.mode === 'file') {
        setSelectedFileId(_file.id)
        selectedFileIdRef.current = _file.id
        setFileContent('')
        setFileContentSnapshot('')
      }
      setShowAddFileDialog(false)
      setNewFileDir('')
      setNewFileName('')
      setNewFileType('text')
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const saveFileMutation = useMutation({
    mutationFn: (variables: SaveFileVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill file save ignored')
      }
      return managedPut<SkillFileRecord>(
        apiResourcePath('skills', variables.skillId, 'files', apiResourceId(variables.fileId)),
        { content: variables.content },
        {
          ...managedRequestOptions(variables.scope),
          timeout: SKILL_SCAN_TIMEOUT_MS,
        },
      )
    },
    onSuccess: (_file, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
      setFileContentSnapshot(variables.content)
      triggerFlash()
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteFileMutation = useMutation({
    mutationFn: (variables: DeleteFileVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill file delete ignored')
      }
      return managedDelete(
        apiResourcePath('skills', variables.skillId, 'files', apiResourceId(variables.fileId)),
        managedRequestOptions(variables.scope),
      )
    },
    onSuccess: (_result, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
      if (selectedFileIdRef.current === variables.fileId) {
        setSelectedFileId(null)
        selectedFileIdRef.current = null
      }
      setDeleteFileTarget(null)
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteFolderMutation = useMutation({
    mutationFn: (variables: DeleteFolderVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill folder delete ignored')
      }
      const { filesToDelete, skillId } = variables
      return Promise.all(
        filesToDelete.map((f) =>
          managedDelete(
            apiResourcePath('skills', skillId, 'files', apiResourceId(f.id)),
            managedRequestOptions(variables.scope),
          ),
        ),
      )
    },
    onSuccess: (_result, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
      const folderPath = variables.folderPath
      if (
        folderPath &&
        selectedFileIdRef.current &&
        variables.filesToDelete.find(
          (f) => f.id === selectedFileIdRef.current && f.path.startsWith(folderPath),
        )
      ) {
        setSelectedFileId(null)
        selectedFileIdRef.current = null
      }
      setDeleteFolderTarget(null)
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  // Drag-and-drop move. A file move is a single PUT changing its ``path``
  // (directory); a folder move batch-PUTs every file under the folder prefix.
  const moveMutation = useMutation({
    mutationFn: async (variables: MoveVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill file move ignored')
      }
      const { files, source, destFolder, skillId } = variables
      const dest = destFolder ? destFolder.replace(/\/*$/, '/') : ''

      if (source.kind === 'file') {
        if (source.path === dest) return // no-op: already there
        if (files.some((f) => f.path === dest && f.id === source.id)) return
        // Conflict: a different file with the same name already sits in dest.
        const movingFile = files.find((f) => f.id === source.id)
        if (
          movingFile &&
          files.some(
            (f) => f.id !== source.id && f.path === dest && f.file_name === movingFile.file_name,
          )
        ) {
          throw new Error('MOVE_CONFLICT')
        }
        await managedPut<SkillFileRecord>(
          apiResourcePath('skills', skillId, 'files', apiResourceId(source.id)),
          { path: dest },
          {
            ...managedRequestOptions(variables.scope),
            timeout: SKILL_SCAN_TIMEOUT_MS,
          },
        )
        return
      }

      // Folder move.
      const srcFolder = source.path.replace(/\/*$/, '/')
      const folderName = srcFolder.replace(/\/$/, '').split('/').pop() || ''
      const currentParent = srcFolder.slice(0, srcFolder.length - (folderName.length + 1))
      if (dest === currentParent) return // no-op
      if (dest === srcFolder || dest.startsWith(srcFolder)) {
        throw new Error('MOVE_INTO_SELF')
      }
      const affected = files.filter((f) => f.path.startsWith(srcFolder))
      const existing = new Set(files.map((f) => f.path + f.file_name))
      await Promise.all(
        affected.map((f) => {
          const rest = f.path.slice(srcFolder.length) // sub-dir tail
          const newDir = `${dest}${folderName}/${rest}`
          if (newDir !== f.path && existing.has(newDir + f.file_name)) {
            throw new Error('MOVE_CONFLICT')
          }
          return managedPut<SkillFileRecord>(
            apiResourcePath('skills', skillId, 'files', apiResourceId(f.id)),
            { path: newDir },
            {
              ...managedRequestOptions(variables.scope),
              timeout: SKILL_SCAN_TIMEOUT_MS,
            },
          )
        }),
      )
    },
    onSuccess: (_result, variables) => {
      if (!isCurrentSkillAction(variables)) return
      invalidateSkillResources(variables.skillId, variables.scope.key)
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      if (
        error instanceof Error &&
        (error.message === 'MOVE_CONFLICT' || error.message === 'MOVE_INTO_SELF')
      ) {
        toast({ title: t('managed.skills.moveConflict'), variant: 'destructive' })
        return
      }
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const createVersionMutation = useMutation({
    mutationFn: (variables: CreateVersionVariables) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill version create ignored')
      }
      return managedPost<SkillVersionRecord>(
        apiResourcePath('skills', variables.skillId, 'versions'),
        {
          name: form.name,
          description: form.description,
          content: form.content,
          release_notes: variables.releaseNotes,
          ...(variables.version ? { version: variables.version } : {}),
        },
        managedRequestOptions(variables.scope),
      )
    },
    onSuccess: (_version, variables) => {
      if (!isCurrentSkillAction(variables)) return
      queryClient.invalidateQueries({
        queryKey: ['skill-versions', variables.scope.key, variables.skillId],
      })
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  // Exposing a version to the organization / public tiers goes through this
  // approval flow. The routes/service enforce the ADMIN (submit) and org-OWNER
  // + four-eyes + scan (approve) gates.
  // Promotion changes the skill's visibility/tier pointers (list + detail) and
  // the version's lifecycle_status, and can surface a fresh scan verdict — but
  // never the file tree, so it deliberately does NOT invalidate skill-files.
  const invalidatePromotion = useCallback(
    (skillId: string, scope: ManagedRequestScope) => {
      queryClient.invalidateQueries({ queryKey: ['skills', scope.key] })
      queryClient.invalidateQueries({ queryKey: ['skill', scope.key, skillId] })
      queryClient.invalidateQueries({ queryKey: ['skill-security-scans', scope.key, skillId] })
      queryClient.invalidateQueries({ queryKey: ['skill-versions', scope.key, skillId] })
    },
    [queryClient],
  )

  const submitPromotionMutation = useMutation({
    mutationFn: (v: {
      skillId: string
      scope: ManagedRequestScope
      version: string
      targetTier: PromotableTier
    }) =>
      managedPost<SkillVersionRecord>(
        apiResourcePath('skills', v.skillId, 'versions', v.version, 'submit-promotion'),
        { target_tier: v.targetTier },
        managedRequestOptions(v.scope),
      ),
    onSuccess: (_r, v) => {
      invalidatePromotion(v.skillId, v.scope)
      toast({ title: t('managed.skills.promotion.submitted') })
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  const approvePromotionMutation = useMutation({
    mutationFn: (v: { skillId: string; scope: ManagedRequestScope; version: string }) =>
      managedPost<SkillVersionRecord>(
        apiResourcePath('skills', v.skillId, 'versions', v.version, 'approve-promotion'),
        {},
        managedRequestOptions(v.scope),
      ),
    onSuccess: (_r, v) => {
      invalidatePromotion(v.skillId, v.scope)
      toast({ title: t('managed.skills.promotion.approved') })
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  const rejectPromotionMutation = useMutation({
    mutationFn: (v: {
      skillId: string
      scope: ManagedRequestScope
      version: string
      reason: string
    }) =>
      managedPost<SkillVersionRecord>(
        apiResourcePath('skills', v.skillId, 'versions', v.version, 'reject-promotion'),
        { reason: v.reason || null },
        managedRequestOptions(v.scope),
      ),
    onSuccess: (_r, v) => {
      invalidatePromotion(v.skillId, v.scope)
      toast({ title: t('managed.skills.promotion.rejectedDone') })
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  const takedownMutation = useMutation({
    mutationFn: (v: { skillId: string; scope: ManagedRequestScope; tier: PromotableTier }) =>
      managedPost<SkillRecord>(
        apiResourcePath('skills', v.skillId, 'takedown'),
        { tier: v.tier },
        managedRequestOptions(v.scope),
      ),
    onSuccess: (_r, v) => {
      invalidatePromotion(v.skillId, v.scope)
      toast({ title: t('managed.skills.promotion.takenDown') })
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  /** Delete a published skill version. Returns 409-payload referrers on conflict
   * so the dialog can offer a force retry; throws on any other error. */
  const deleteVersion = useCallback(
    async (
      version: string,
      force = false,
    ): Promise<
      { ok: true } | { ok: false; referrers: Array<Record<string, unknown>>; hint?: string }
    > => {
      const action = nextCurrentMutableSkillAction()
      if (!action) return { ok: true }
      if (!currentSkillVersion(version, action.skillId)) return { ok: true }
      if (!isCurrentSkillAction(action)) return { ok: true }
      try {
        await managedDelete(
          apiResourceSubpath('skills', action.skillId, ['versions', version], {
            force: force || undefined,
          }),
          managedRequestOptions(action.scope),
        )
        if (isCurrentSkillAction(action)) {
          queryClient.invalidateQueries({
            queryKey: ['skill-versions', action.scope.key, action.skillId],
          })
        }
        return { ok: true }
      } catch (e) {
        if (!isCurrentSkillAction(action)) return { ok: true }
        // 409 with referrer list → caller shows a force-confirm UI.
        const err = e as {
          status?: number
          code?: string
          data?: { referrers?: unknown[]; hint?: string }
        }
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
    [currentSkillVersion, isCurrentSkillAction, nextCurrentMutableSkillAction, queryClient, t],
  )

  const restoreVersion = useCallback(
    async (version: string): Promise<boolean> => {
      const action = nextCurrentMutableSkillAction()
      if (!action) return false
      if (!currentSkillVersion(version, action.skillId)) return false
      if (!isCurrentSkillAction(action)) return false
      try {
        await managedPost(
          apiResourcePath('skills', action.skillId, 'versions', 'restore', version),
          {},
          managedRequestOptions(action.scope),
        )
        if (isCurrentSkillAction(action)) {
          // Restore rewrites the draft (content + files) from the version,
          // so refresh the skill detail, files, and version list together.
          invalidateSkillResources(action.skillId, action.scope.key)
        }
        return true
      } catch (e) {
        if (!isCurrentSkillAction(action)) return false
        toastOperationError(t, e, 'common.operationFailed')
        throw e
      }
    },
    [
      currentSkillVersion,
      invalidateSkillResources,
      isCurrentSkillAction,
      nextCurrentMutableSkillAction,
      t,
    ],
  )

  const rescanSecurityMutation = useMutation({
    mutationFn: (variables: SkillActionScope) => {
      if (!isCurrentSkillAction(variables)) {
        throw new Error('Stale skill security rescan ignored')
      }
      return managedPost<SkillSecurityScanRecord>(
        apiResourcePath('skills', variables.skillId, 'security-scans', 'rescan'),
        {},
        managedRequestOptions(variables.scope),
        // Rescan dispatches asynchronously on the backend and returns
        // immediately with a scanning-state row, so the default 30s client
        // timeout is plenty — no override needed. The selectedSkill query
        // polls (refetchInterval) until the background verdict lands.
      )
    },
    onSuccess: (_scan, variables) => {
      if (!isCurrentSkillAction(variables)) return
      queryClient.invalidateQueries({ queryKey: ['skills', variables.scope.key] })
      queryClient.invalidateQueries({
        queryKey: ['skill', variables.scope.key, variables.skillId],
      })
      queryClient.invalidateQueries({
        queryKey: ['skill-security-scans', variables.scope.key, variables.skillId],
      })
      // Scan now runs in the background; tell the user it started rather
      // than that it completed.
      toast({ title: t('managed.skills.rescanStarted') })
    },
    onError: (error, variables) => {
      if (!isCurrentSkillAction(variables)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  // -- Handlers --

  const handleSelectSkill = useCallback(
    (id: string) => {
      mutationRunRef.current += 1
      selectedSkillIdRef.current = id
      selectedFileIdRef.current = null
      clearSavedFlash()
      setSelectedSkillId(id)
      setSelectedFileId(null)
      router.push(`/managed/skills/${id}`)
    },
    [clearSavedFlash, router],
  )

  const openDeleteSkillDialog = useCallback(
    (id: string) => {
      // delete_skill requires ADMIN on the backend — gate the single choke
      // point every delete flow passes through. Archived skills stay
      // deletable (delete is a purge, not an edit), so we do NOT gate on
      // isSkillMutable here — only that the skill is still in the list.
      if (!currentProjectAllowsAdmin()) return
      if (!currentSkillInList(id)) return

      mutationRunRef.current += 1
      setDeleteTarget(id)
    },
    [currentSkillInList],
  )

  const closeDeleteSkillDialog = useCallback(() => {
    // NOTE: must NOT bump mutationRunRef here. The ConfirmDialog's confirm
    // button is a Radix AlertDialogAction, which auto-fires onOpenChange(false)
    // -> onCancel on the same click as onConfirm. Bumping the run counter on
    // that close would make the just-launched delete's onSuccess guard fail,
    // silently skipping invalidateQueries — the delete would land server-side
    // but the row would linger in the list until a manual refresh. Staleness
    // from opening a *new* dialog is already covered by openDeleteSkillDialog's
    // bump, and scope changes are covered by the scope check.
    setDeleteTarget(null)
  }, [])

  const openDeleteFileDialog = useCallback(
    (id: string) => {
      const skillId = selectedSkillIdRef.current
      if (!isSkillMutable(currentSkillInList(skillId))) return
      const detailSkill = currentSkillDetail(skillId)
      if (detailSkill && !isSkillMutable(detailSkill)) return
      if (!currentSkillFile(id)) return

      mutationRunRef.current += 1
      setDeleteFileTarget(id)
    },
    [currentSkillDetail, currentSkillFile, currentSkillInList],
  )

  const closeDeleteFileDialog = useCallback(() => {
    mutationRunRef.current += 1
    setDeleteFileTarget(null)
  }, [])

  const openDeleteFolderDialog = useCallback(
    (path: string) => {
      const skillId = selectedSkillIdRef.current
      if (!isSkillMutable(currentSkillInList(skillId))) return
      const detailSkill = currentSkillDetail(skillId)
      if (detailSkill && !isSkillMutable(detailSkill)) return
      if (currentFolderFiles(path).length === 0) return

      mutationRunRef.current += 1
      setDeleteFolderTarget(path)
    },
    [currentFolderFiles, currentSkillDetail, currentSkillInList],
  )

  const closeDeleteFolderDialog = useCallback(() => {
    mutationRunRef.current += 1
    setDeleteFolderTarget(null)
  }, [])

  const handleSelectFile = useCallback(
    (fileId: string) => {
      const file = skillFiles.find((f) => f.id === fileId)
      if (file) {
        selectedFileIdRef.current = fileId
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
      selectedFileIdRef.current = skillMd.id
      setSelectedFileId(skillMd.id)
      setFileContent(skillMd.content || '')
      setFileContentSnapshot(skillMd.content || '')
    } else {
      selectedFileIdRef.current = null
      setSelectedFileId(null)
    }
  }, [skillFiles])

  const canEditSelectedSkill = !projectReadOnly && isSkillMutable(selectedSkill)

  // -- Ctrl+S / Cmd+S --

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (!canEditSelectedSkill) return
        // Mirror the Save button: only save a file on the Editor tab;
        // otherwise save the skill-level metadata form.
        const savingFile = editorTab === 'editor' && !!selectedFileId
        if (savingFile && isFileDirty) {
          const action = nextCurrentMutableSkillAction()
          const fileId = selectedFileIdRef.current
          const file = action && fileId ? currentSkillFile(fileId, action.skillId) : null
          if (action && file) {
            saveFileMutation.mutate({ ...action, fileId: file.id, content: fileContent })
          }
        } else if (!savingFile && selectedSkillId && isDirty) {
          const action = nextCurrentMutableSkillAction()
          if (action) {
            saveMutation.mutate({ ...action, form })
          }
        }
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [
    selectedSkillId,
    selectedFileId,
    editorTab,
    fileContent,
    form,
    isDirty,
    isFileDirty,
    currentSkillFile,
    canEditSelectedSkill,
    nextCurrentMutableSkillAction,
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

  useEffect(() => {
    if (!selectedSkill || canEditSelectedSkill) return
    setShowVersionForm(false)
    setShowAddFileDialog(false)
    setDeleteFileTarget(null)
    setDeleteFolderTarget(null)
  }, [canEditSelectedSkill, selectedSkill])

  useEffect(() => {
    if (!projectReadOnly) return
    mutationRunRef.current += 1
    setShowVersionForm(false)
    setShowAddFileDialog(false)
    setDeleteTarget(null)
    setDeleteFileTarget(null)
    setDeleteFolderTarget(null)
    setShowImportDialog(false)
  }, [projectReadOnly])

  // -- Render --

  if (skillsIsError) {
    return (
      <ResourceErrorState
        error={skillsError}
        resource="skill"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['skills', managedScope.key] })}
      />
    )
  }

  if (selectedSkillIsError) {
    return (
      <ResourceErrorState
        error={selectedSkillError}
        resource="skill"
        onRetry={() =>
          queryClient.invalidateQueries({
            queryKey: ['skill', managedScope.key, selectedSkillId],
          })
        }
      />
    )
  }

  if (!selectedSkill) {
    // -- List Homepage (consistent with other pages) --
    const filteredSkills = skills.filter(
      (s) =>
        filterByCreatedTime(s.created_at, createdFilter) &&
        matchesSearch(searchQuery, [
          s.id,
          s.name,
          s.description,
          s.license,
          s.visibility || 'project',
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
        width: '10%',
        render: (s) => <MonoId id={s.id} />,
      },
      {
        key: 'name',
        header: t('managed.table.name'),
        width: '12%',
        render: (s) => <span className="font-medium text-foreground">{s.name}</span>,
      },
      {
        key: 'description',
        header: t('managed.skills.description'),
        width: '16%',
        render: (s) => (
          <span className="block truncate text-muted-foreground">{s.description || '-'}</span>
        ),
      },
      {
        key: 'status',
        header: t('managed.table.status'),
        width: '24%',
        render: (s) => (
          <div className="flex flex-nowrap items-center gap-1 whitespace-nowrap">
            <SkillLifecycleBadge status={s.lifecycle_status} />
            <SkillVisibilityBadge visibility={s.visibility} />
            {s.latest_version ? (
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300">
                {t('managed.skills.published')} v{s.latest_version}
              </span>
            ) : (
              <span className="inline-flex items-center whitespace-nowrap rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                {t('managed.skills.unpublished')}
              </span>
            )}
          </div>
        ),
      },
      {
        key: 'security',
        header: t('managed.table.security'),
        width: '20%',
        render: (s) => {
          const score = skillSecurityScore(s)
          return (
            <div className="flex flex-nowrap items-center gap-2 whitespace-nowrap">
              <SkillSecurityBadge status={s.security_scan?.status} />
              {score !== null && <SkillRiskScoreBadge score={score} />}
            </div>
          )
        },
      },
      {
        key: 'updated_at',
        header: t('managed.table.lastUpdated'),
        width: '10%',
        render: (s) => (
          <span className="text-xs text-muted-foreground">
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
            projectReadOnly ? null : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  className="h-10 gap-2 px-4 text-sm font-medium leading-none"
                  disabled={isImporting}
                  onClick={() => {
                    if (!currentProjectAllowsWrite()) return
                    setShowImportDialog(true)
                  }}
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
                  onClick={() => {
                    if (!currentProjectAllowsWrite()) return
                    router.push('/managed/skills/new-ai?new=1')
                  }}
                >
                  <Sparkles className="h-4 w-4" strokeWidth={2.25} />
                  {t('managed.skills.aiAuthor.entry')}
                </Button>
              </div>
            )
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
              (s) => s.id.includes(id) || s.name.toLowerCase().includes(id.toLowerCase()),
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
            ...(!projectReadOnly && isProjectSkillAdmin
              ? [
                  {
                    label: t('managed.skills.deleteSkill'),
                    onClick: () => openDeleteSkillDialog(s.id),
                    destructive: true,
                  },
                ]
              : []),
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

        <Dialog
          open={!projectReadOnly && showImportDialog}
          onOpenChange={(open) => {
            if (open && !currentProjectAllowsWrite()) return
            setShowImportDialog(open)
          }}
        >
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

        <ConfirmDialog
          open={!projectReadOnly && deleteTarget !== null}
          title={t('managed.skills.deleteSkill')}
          description={t('managed.skills.deleteConfirm')}
          confirmLabel={t('managed.skills.deleteSkill')}
          destructive
          onConfirm={() => {
            const target = currentSkillInList(deleteTarget)
            if (!target) {
              closeDeleteSkillDialog()
              return
            }
            const action = nextManagedAction()
            if (action) deleteMutation.mutate({ ...action, id: target.id })
          }}
          onCancel={closeDeleteSkillDialog}
        />
      </div>
    )
  }

  // -- Editor View (skill selected) --
  const selectedFile = skillFiles.find((file) => file.id === selectedFileId)
  // The Save button saves a FILE only when the Editor tab is showing an
  // actual file. On the Metadata / Versions tabs it always saves the
  // skill-level metadata form, no matter which file the tree has selected.
  const isEditingFile =
    editorTab === 'editor' && selectedFileId !== null && selectedFile !== undefined
  const canSave = canEditSelectedSkill && (isEditingFile ? isFileDirty : isDirty)
  const selectedSecurityScore = skillSecurityScore(selectedSkill)
  const runtimeEligibility = selectedSkill.runtime_eligibility
  const impactCounts = selectedSkill.impact?.counts
  const publishRuntimeBlocked = !!runtimeEligibility && !runtimeEligibility.usable
  const securityTriggerLabels: Record<string, string> = {
    create: t('managed.skills.securityTriggers.create'),
    update: t('managed.skills.securityTriggers.update'),
    file_add: t('managed.skills.securityTriggers.fileAdd'),
    file_update: t('managed.skills.securityTriggers.fileUpdate'),
    file_delete: t('managed.skills.securityTriggers.fileDelete'),
    manual: t('managed.skills.securityTriggers.manual'),
  }

  return (
    <div className="-m-5 flex h-screen flex-col px-6 py-5">
      <div className="shrink-0">
        <PageHeader
          title={selectedSkill.name}
          titleExtra={
            <div className="flex flex-wrap items-center gap-2">
              {/* Visibility is shown here as a read-only badge. Editing it
                  lives in the Metadata form (SkillEditor), so the header
                  stays a status snapshot rather than a control surface. */}
              <SkillStatusBadges skill={selectedSkill} />
              {selectedSecurityScore !== null && (
                <SkillRiskScoreBadge score={selectedSecurityScore} />
              )}
            </div>
          }
          breadcrumb={[
            {
              label: t('managed.skills.title'),
              onClick: backToSkillList,
            },
            { label: selectedSkill.name },
          ]}
          action={
            <div className="flex items-center gap-2">
              {savedFlash && (
                <span className="flex items-center gap-1 text-xs text-green-600">
                  <Check className="h-3 w-3" />
                  {t('managed.skills.savedSuccess')}
                </span>
              )}
              {/* Lifecycle transition buttons — only the legal next
                  edges from the current state are rendered. */}
              {!projectReadOnly && (
                <SkillLifecycleActions
                  skillId={selectedSkill.id}
                  currentStatus={selectedSkill.lifecycle_status}
                  requestScope={managedScope}
                  operationScope={`${managedScope.key}:${selectedSkill.id}`}
                  canSubmitTransition={(endpoint) => {
                    // Lifecycle transitions require ProjectCapability.ADMIN on
                    // the backend (submit/approve/reject/archive/…), so gate on
                    // admin — a WRITE-only editor would otherwise see buttons
                    // the API rejects with SKILL_ACCESS_DENIED.
                    if (!currentProjectAllowsAdmin()) return false
                    const current = currentSkillInList(selectedSkill.id)
                    if (!current || current.lifecycle_status !== selectedSkill.lifecycle_status)
                      return false
                    if (endpoint === 'unarchive' && publishRuntimeBlocked) {
                      return false
                    }
                    return true
                  }}
                  invalidateKeys={[
                    ['skill', managedScope.key, selectedSkillId],
                    ['skills', managedScope.key],
                  ]}
                  impact={selectedSkill.impact}
                />
              )}
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
                onClick={() => {
                  const action = nextCurrentMutableSkillAction()
                  if (action) rescanSecurityMutation.mutate(action)
                }}
                disabled={
                  !canEditSelectedSkill ||
                  rescanSecurityMutation.isPending ||
                  saveMutation.isPending ||
                  saveFileMutation.isPending
                }
              >
                <RefreshCw
                  className={`h-4 w-4 ${rescanSecurityMutation.isPending ? 'animate-spin' : ''}`}
                />
                {rescanSecurityMutation.isPending
                  ? t('managed.skills.rescanningSecurity')
                  : t('managed.skills.rescanSecurity')}
              </Button>
              {!showVersionForm && (
                <Button
                  className="relative h-9 gap-2"
                  onClick={() => {
                    // Publishing a version requires ADMIN (backend create_version
                    // gate); WRITE-only editors must not reach this.
                    if (!canEditSelectedSkill || !isProjectSkillAdmin) return
                    setShowVersionForm(true)
                  }}
                  disabled={!canEditSelectedSkill || !isProjectSkillAdmin || publishRuntimeBlocked}
                  title={
                    securityBlocked
                      ? t('managed.skills.publishBlockedBySecurity')
                      : publishRuntimeBlocked
                        ? t(eligibilityActionView(runtimeEligibility?.next_action).hintKey)
                        : hasUnpublishedChanges
                          ? t('managed.skills.unpublishedChanges')
                          : undefined
                  }
                >
                  <Plus className="h-4 w-4" />
                  {t('managed.skills.createVersionBtn')}
                  {hasUnpublishedChanges && !publishRuntimeBlocked && (
                    <span className="absolute -right-1 -top-1 flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-amber-500" />
                    </span>
                  )}
                </Button>
              )}
              <Button
                className="h-9 gap-2"
                onClick={() => {
                  const action = nextCurrentMutableSkillAction()
                  if (!action) return
                  if (isEditingFile && selectedFileIdRef.current) {
                    const file = currentSkillFile(selectedFileIdRef.current, action.skillId)
                    if (!file) return
                    saveFileMutation.mutate({
                      ...action,
                      fileId: file.id,
                      content: fileContent,
                    })
                  } else {
                    saveMutation.mutate({ ...action, form })
                  }
                }}
                disabled={saveMutation.isPending || saveFileMutation.isPending || !canSave}
              >
                <Save className="h-4 w-4" />
                {saveMutation.isPending || saveFileMutation.isPending
                  ? t('managed.skills.saving')
                  : t('managed.skills.saveChanges')}
              </Button>
            </div>
          }
        />
      </div>

      {rescanSecurityMutation.isPending && (
        <SkillScanProgressNotice
          title={t('managed.skills.securityScanInProgressTitle')}
          description={t('managed.skills.securityScanInProgressDescription')}
        />
      )}

      {securityBlocked ? (
        <div className="mb-3 flex items-center gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
          <span className="flex h-2 w-2 shrink-0 rounded-full bg-destructive" />
          <span className="flex-1 text-destructive">
            {t('managed.skills.publishBlockedBySecurity')}
          </span>
        </div>
      ) : hasUnpublishedChanges ? (
        <div className="mb-3 flex items-center gap-2.5 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm dark:border-amber-800/50 dark:bg-amber-950/30">
          <span className="flex h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          <span className="flex-1 text-amber-800 dark:text-amber-200">
            {t('managed.skills.unpublishedChanges')}
          </span>
        </div>
      ) : null}

      {runtimeEligibility && !runtimeEligibility.usable && (
        <div className="mb-3 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm dark:border-amber-800/50 dark:bg-amber-950/30">
          <div className="flex items-center gap-2.5">
            <span className="flex h-2 w-2 shrink-0 rounded-full bg-amber-500" />
            <span
              className="font-medium text-amber-900 dark:text-amber-100"
              // Raw reason code kept as a hover affordance for operators/support,
              // not shown as primary UI. Localized copy carries the meaning.
              title={runtimeEligibility.reason || undefined}
            >
              {t(eligibilityReasonView(runtimeEligibility.reason).titleKey)}
            </span>
          </div>
          <div className="mt-1 pl-4 text-xs text-amber-800 dark:text-amber-200">
            {t(eligibilityActionView(runtimeEligibility.next_action).hintKey)}
          </div>
        </div>
      )}

      {((impactCounts && impactCounts.total > 0) ||
        recentSkillUsage.length > 0 ||
        (currentTargetHash && targetHashUsage.length > 0)) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm">
          <div className="flex min-w-0 items-center gap-2">
            <span className="font-medium text-foreground">
              {t('managed.skills.runtimeStatsTitle')}
            </span>
            <span className="hidden text-xs text-muted-foreground md:inline">
              {t('managed.skills.runtimeStatsCompactDescription')}
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-1.5 text-xs">
            {impactCounts && impactCounts.total > 0 && (
              <>
                <span className="rounded-full border bg-background px-2 py-0.5 text-muted-foreground">
                  {t('managed.skills.impactAgents')}: {impactCounts.agents}
                </span>
                <span className="rounded-full border bg-background px-2 py-0.5 text-muted-foreground">
                  {t('managed.skills.impactTriggers')}: {impactCounts.triggers}
                </span>
                <span className="rounded-full border bg-background px-2 py-0.5 text-muted-foreground">
                  {t('managed.skills.impactActiveTasks')}: {impactCounts.active_tasks}
                </span>
              </>
            )}
            {recentSkillUsage.length > 0 && (
              <span className="rounded-full border bg-background px-2 py-0.5 text-muted-foreground">
                {t('managed.skills.recentSessions', { count: recentSkillUsage.length })}
              </span>
            )}
            {currentTargetHash && targetHashUsage.length > 0 && (
              <span className="rounded-full border bg-background px-2 py-0.5 font-mono text-muted-foreground">
                {currentTargetHash.slice(0, 12)}
              </span>
            )}
            <Button variant="outline" size="sm" onClick={() => setShowRuntimeStatsDialog(true)}>
              {t('managed.skills.viewRuntimeStats')}
            </Button>
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-xl border border-border bg-background">
        {/* Center panel -- file tree */}
        <SkillWorkspace
          skillName={selectedSkill.name}
          files={skillFiles}
          selectedFileId={selectedFileId}
          canEdit={canEditSelectedSkill}
          onSelectFile={handleSelectFile}
          onSelectMain={handleSelectMain}
          onAddFolder={() => {
            if (!canEditSelectedSkill) return
            setNewFileMode('folder')
            setNewFileDir('')
            setShowAddFileDialog(true)
          }}
          onAddToFolder={(folderPath) => {
            if (!canEditSelectedSkill) return
            setNewFileMode('file')
            setNewFileDir(folderPath.replace(/\/+$/, ''))
            setShowAddFileDialog(true)
          }}
          onDeleteFile={openDeleteFileDialog}
          onDeleteFolder={openDeleteFolderDialog}
          onMove={(source, destFolder) => {
            const action = nextCurrentMutableSkillAction()
            if (!action) return
            const files = currentSkillFiles(action.skillId)
            if (source.kind === 'file') {
              const file = currentSkillFile(source.id, action.skillId)
              if (!file) return
              moveMutation.mutate({
                ...action,
                source: { ...source, path: file.path },
                destFolder,
                files,
              })
            } else if (currentFolderFiles(source.path, action.skillId).length > 0) {
              moveMutation.mutate({ ...action, source, destFolder, files })
            }
          }}
          isMainSelected={selectedFileId === null}
        />

        {/* Right panel -- editor */}
        <SkillEditor
          skill={selectedSkill}
          files={skillFiles}
          selectedFileId={selectedFileId}
          canEdit={canEditSelectedSkill}
          form={form}
          setForm={setForm}
          fileContent={fileContent}
          setFileContent={setFileContent}
          versions={versions}
          onCreateVersion={(notes, version) => {
            const action = nextCurrentMutableSkillAction()
            if (action) {
              createVersionMutation.mutate({
                ...action,
                releaseNotes: notes,
                version,
              })
            }
          }}
          onDeleteVersion={deleteVersion}
          onRestoreVersion={restoreVersion}
          onDeleteVersionDialogActivity={() => {
            mutationRunRef.current += 1
          }}
          isProjectSkillAdmin={isProjectSkillAdmin}
          isOrgOwner={isOrgOwner}
          onPromoteVersion={(version) => setPromoteTarget(version)}
          onApproveVersion={(version) => {
            if (selectedSkillId) {
              approvePromotionMutation.mutate({
                skillId: selectedSkillId,
                scope: managedScope,
                version,
              })
            }
          }}
          onRejectVersion={(version) => {
            setRejectReason('')
            setRejectTarget(version)
          }}
          onTakedown={(tier) => {
            if (selectedSkillId) {
              takedownMutation.mutate({ skillId: selectedSkillId, scope: managedScope, tier })
            }
          }}
          isCreatingVersion={createVersionMutation.isPending}
          editorTab={editorTab}
          setEditorTab={setEditorTab}
          showVersionForm={showVersionForm}
          setShowVersionForm={setShowVersionForm}
          queryScope={managedScope.key}
          requestScope={managedScope}
        />
      </div>

      <Dialog open={showRuntimeStatsDialog} onOpenChange={setShowRuntimeStatsDialog}>
        <DialogContent className="left-auto right-0 top-0 h-dvh max-h-dvh w-[min(560px,100vw)] max-w-none translate-x-0 translate-y-0 rounded-none border-y-0 border-r-0 p-0 data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right">
          <DialogHeader className="border-b px-5 py-4">
            <DialogTitle>{t('managed.skills.runtimeStatsTitle')}</DialogTitle>
            <DialogDescription>{t('managed.skills.runtimeStatsDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 overflow-y-auto px-5 py-4">
            <section className="rounded-lg border bg-muted/20 p-3">
              <div className="mb-2 text-sm font-medium text-foreground">
                {t('managed.skills.runtimeStatsSummary')}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div className="rounded-md border bg-background p-2">
                  <div className="text-muted-foreground">{t('managed.skills.impactAgents')}</div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {impactCounts?.agents || 0}
                  </div>
                </div>
                <div className="rounded-md border bg-background p-2">
                  <div className="text-muted-foreground">{t('managed.skills.impactTriggers')}</div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {impactCounts?.triggers || 0}
                  </div>
                </div>
                <div className="rounded-md border bg-background p-2">
                  <div className="text-muted-foreground">
                    {t('managed.skills.impactActiveTasks')}
                  </div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {impactCounts?.active_tasks || 0}
                  </div>
                </div>
                <div className="rounded-md border bg-background p-2">
                  <div className="text-muted-foreground">{t('managed.skills.runtimeSession')}</div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {recentSkillUsage.length}
                  </div>
                </div>
              </div>
            </section>

            {impactCounts && impactCounts.total > 0 && (
              <section className="rounded-lg border bg-background p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">
                    {t('managed.skills.impactTitle')}
                  </h3>
                  <span className="text-xs text-muted-foreground">
                    {t('managed.skills.totalReferences', { count: impactCounts.total })}
                  </span>
                </div>
                {selectedSkill.impact?.references?.length ? (
                  <div className="flex max-h-36 flex-wrap gap-1 overflow-y-auto pr-1 text-xs">
                    {selectedSkill.impact.references.map((ref) => (
                      <span
                        key={`${ref.type}:${ref.id}`}
                        className="max-w-full truncate rounded-full border bg-muted/30 px-2 py-0.5 text-muted-foreground"
                        title={`${ref.type}: ${ref.name}`}
                      >
                        {ref.type}: {ref.name}
                      </span>
                    ))}
                  </div>
                ) : null}
              </section>
            )}

            {recentSkillUsage.length > 0 && (
              <section className="min-w-0 rounded-lg border bg-background p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">
                    {t('managed.skills.recentRuntimeUsage')}
                  </h3>
                  <span className="text-xs text-muted-foreground">
                    {t('managed.skills.recentSessions', { count: recentSkillUsage.length })}
                  </span>
                </div>
                <div className="overflow-x-auto rounded-md border">
                  <div className="grid min-w-[520px] grid-cols-[minmax(180px,1fr)_72px_110px_110px] gap-2 border-b px-2 py-1.5 text-xs font-medium text-muted-foreground">
                    <span>{t('managed.skills.runtimeSession')}</span>
                    <span>{t('managed.skills.runtimeVersion')}</span>
                    <span>{t('managed.skills.runtimeArtifact')}</span>
                    <span>{t('managed.skills.runtimeTarget')}</span>
                  </div>
                  <div className="divide-y">
                    {recentSkillUsage.map((usage) => (
                      <div
                        key={usage.id}
                        className="grid min-w-[520px] grid-cols-[minmax(180px,1fr)_72px_110px_110px] gap-2 px-2 py-1.5 text-xs"
                      >
                        <span
                          className="truncate font-mono text-foreground"
                          title={usage.session_id || ''}
                        >
                          {usage.session_id || t('managed.skills.runtimeUnknownSession')}
                        </span>
                        <span className="text-muted-foreground">
                          {usage.skill_version ? `v${usage.skill_version}` : '—'}
                        </span>
                        <span
                          className="truncate font-mono text-muted-foreground"
                          title={usage.artifact_hash || ''}
                        >
                          {usage.artifact_hash ? usage.artifact_hash.slice(0, 12) : '—'}
                        </span>
                        <span
                          className="truncate font-mono text-muted-foreground"
                          title={usage.target_hash || ''}
                        >
                          {usage.target_hash ? usage.target_hash.slice(0, 12) : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {currentTargetHash && targetHashUsage.length > 0 && (
              <section className="rounded-lg border bg-background p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-medium text-foreground">
                    {t('managed.skills.targetHashExposure')}
                  </h3>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                    {currentTargetHash.slice(0, 12)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {t('managed.skills.recentSessions', { count: targetHashUsage.length })}
                  </span>
                </div>
                <div className="flex max-h-40 flex-wrap gap-1 overflow-y-auto pr-1 text-xs">
                  {targetHashUsage.map((usage) => (
                    <span
                      key={usage.id}
                      className="max-w-full truncate rounded-full border bg-muted/30 px-2 py-0.5 text-muted-foreground"
                      title={`${usage.skill_name || usage.skill_id || 'deleted skill'} · ${usage.session_id || ''}`}
                    >
                      {usage.skill_name ||
                        usage.skill_id ||
                        t('managed.skills.runtimeDeletedSkill')}{' '}
                      · {usage.session_id || t('managed.skills.runtimeUnknownSession')}
                    </span>
                  ))}
                </div>
              </section>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Promote a version to a wider tier (project ADMIN submits; an org
          OWNER then reviews). */}
      <Dialog
        open={promoteTarget !== null}
        onOpenChange={(open) => !open && setPromoteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.promotion.submit')}</DialogTitle>
            <DialogDescription>{t('managed.skills.promotion.submitToOrg')}</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-col">
            <Button
              className="w-full"
              variant="outline"
              onClick={() => {
                if (selectedSkillId && promoteTarget) {
                  submitPromotionMutation.mutate({
                    skillId: selectedSkillId,
                    scope: managedScope,
                    version: promoteTarget,
                    targetTier: 'organization',
                  })
                }
                setPromoteTarget(null)
              }}
            >
              {t('managed.skills.promotion.submitToOrg')}
            </Button>
            <Button
              className="w-full"
              onClick={() => {
                if (selectedSkillId && promoteTarget) {
                  submitPromotionMutation.mutate({
                    skillId: selectedSkillId,
                    scope: managedScope,
                    version: promoteTarget,
                    targetTier: 'public',
                  })
                }
                setPromoteTarget(null)
              }}
            >
              {t('managed.skills.promotion.submitToPublic')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject a pending promotion with an optional reason (org OWNER). */}
      <Dialog open={rejectTarget !== null} onOpenChange={(open) => !open && setRejectTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.promotion.reject')}</DialogTitle>
          </DialogHeader>
          <Input
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder={t('managed.skills.promotion.rejectReasonPlaceholder')}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedSkillId && rejectTarget) {
                  rejectPromotionMutation.mutate({
                    skillId: selectedSkillId,
                    scope: managedScope,
                    version: rejectTarget,
                    reason: rejectReason,
                  })
                }
                setRejectTarget(null)
              }}
            >
              {t('managed.skills.promotion.reject')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showSecurityHistoryDialog} onOpenChange={setShowSecurityHistoryDialog}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('managed.skills.securityHistory')}</DialogTitle>
            <DialogDescription>{t('managed.skills.securityHistoryDescription')}</DialogDescription>
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
                    <div
                      key={scan.id}
                      className="grid gap-3 px-4 py-3 md:grid-cols-[1.2fr_1fr_1fr]"
                    >
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
                        {t('managed.skills.securitySeverity')}:{' '}
                        {scan.severity ? t(severityLabelKey(scan.severity)) : '-'} ·{' '}
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
                              {t('managed.skills.securitySeverity')}:{' '}
                              {scan.severity ? t(severityLabelKey(scan.severity)) : '-'}
                            </span>
                            <span className="text-muted-foreground">
                              {t('managed.skills.securityRecommendation')}:{' '}
                              {scan.recommendation || '-'}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {severityDistribution.map((item) => (
                              <span
                                key={item.severity}
                                className={`rounded-full border px-2 py-0.5 font-medium ${securityIssueSeverityClass(item.severity)}`}
                              >
                                {t(severityLabelKey(item.severity))} {item.count}
                              </span>
                            ))}
                          </div>
                          <div className="mt-2 text-muted-foreground">
                            {t('managed.skills.securityAggregateRiskDescription', {
                              score:
                                scan.score !== null && scan.score !== undefined ? scan.score : '-',
                              severity: scan.severity ? t(severityLabelKey(scan.severity)) : '-',
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
                                const isHighRisk =
                                  issue.severity === 'CRITICAL' || issue.severity === 'HIGH'
                                return (
                                  <details
                                    key={issue.key}
                                    open={isHighRisk}
                                    className={`rounded-md border bg-background ${securityIssueBorderClass(issue.severity)}`}
                                  >
                                    <summary className="grid cursor-pointer gap-2 px-3 py-2 text-sm outline-none transition-colors hover:bg-muted/60 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
                                      <span
                                        className={`w-fit rounded-full border px-2 py-0.5 text-[11px] font-medium ${securityIssueSeverityClass(issue.severity)}`}
                                      >
                                        {t('managed.skills.securitySingleIssueSeverity', {
                                          severity: t(severityLabelKey(issue.severity)),
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
                                            {t('managed.skills.securityIssueCategory')}:{' '}
                                            {issue.category}
                                          </span>
                                        ) : null}
                                        {issue.confidence ? (
                                          <span>
                                            {t('managed.skills.securityIssueConfidence')}:{' '}
                                            {issue.confidence}
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
          if (open && !canEditSelectedSkill) return
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
                const currentDepth = newFileDir.split('/').filter(Boolean).length
                const canCreateSubfolder = currentDepth < MAX_FOLDER_DEPTH
                return (
                  <div className="flex gap-2">
                    <Button
                      variant={newFileMode === 'file' ? 'default' : 'outline'}
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
                      variant={newFileMode === 'folder' ? 'default' : 'outline'}
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
                    const action = nextCurrentMutableSkillAction()
                    if (action) {
                      const dir = newFileDir.trim()
                      if (dir && currentFolderFiles(`${dir}/`, action.skillId).length === 0) return
                      createFileMutation.mutate({
                        ...action,
                        dir,
                        fileName: newFileName.trim(),
                        fileType: newFileType,
                        mode: newFileMode,
                      })
                    }
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
                    <SelectItem value="javascript">
                      {t('managed.skills.fileTypeJavaScript')}
                    </SelectItem>
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
            <Button variant="outline" onClick={() => setShowAddFileDialog(false)}>
              {t('managed.skills.cancel')}
            </Button>
            <Button
              onClick={() => {
                const action = nextCurrentMutableSkillAction()
                if (action) {
                  const dir = newFileDir.trim()
                  if (dir && currentFolderFiles(`${dir}/`, action.skillId).length === 0) return
                  createFileMutation.mutate({
                    ...action,
                    dir,
                    fileName: newFileName.trim(),
                    fileType: newFileType,
                    mode: newFileMode,
                  })
                }
              }}
              disabled={
                !canEditSelectedSkill || !newFileName.trim() || createFileMutation.isPending
              }
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
        onOpenChange={(open) => !open && closeDeleteFileDialog()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.deleteFile')}</DialogTitle>
            <DialogDescription>{t('managed.skills.deleteFileConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={closeDeleteFileDialog}>
              {t('managed.skills.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const action = nextCurrentMutableSkillAction()
                if (!action) return
                const target = currentSkillFile(deleteFileTarget, action.skillId)
                if (!target) {
                  closeDeleteFileDialog()
                  return
                }
                deleteFileMutation.mutate({ ...action, fileId: target.id })
              }}
              disabled={!canEditSelectedSkill || deleteFileMutation.isPending}
            >
              {t('managed.skills.deleteFile')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete folder confirmation */}
      <Dialog
        open={deleteFolderTarget !== null}
        onOpenChange={(open) => !open && closeDeleteFolderDialog()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.skills.deleteFolder')}</DialogTitle>
            <DialogDescription>{t('managed.skills.deleteFolderConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={closeDeleteFolderDialog}>
              {t('managed.skills.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const action = nextCurrentMutableSkillAction()
                if (!action) return
                const filesToDelete = currentFolderFiles(deleteFolderTarget, action.skillId)
                if (!deleteFolderTarget || filesToDelete.length === 0) {
                  closeDeleteFolderDialog()
                  return
                }
                deleteFolderMutation.mutate({
                  ...action,
                  folderPath: deleteFolderTarget,
                  filesToDelete,
                })
              }}
              disabled={!canEditSelectedSkill || deleteFolderMutation.isPending}
            >
              {t('managed.skills.deleteFolder')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default function SkillManagerPage() {
  return <SkillManagerPageContent initialSkillId={null} />
}
