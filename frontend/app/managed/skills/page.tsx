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
} from 'lucide-react'
import { managedGet, managedPost, managedPut, managedDelete, managedUpload } from '@/lib/api-client'
import type {
  SkillRecord,
  SkillFileRecord,
  SkillVersionRecord,
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

const FILE_TYPE_EXT: Record<string, string> = {
  text: '.txt',
  markdown: '.md',
  json: '.json',
  yaml: '.yaml',
  python: '.py',
  javascript: '.js',
  shell: '.sh',
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
  onCreateVersion: (releaseNotes: string) => void
  isCreatingVersion: boolean
}) {
  const { t, i18n } = useTranslation()
  const [editorTab, setEditorTab] = useState<'editor' | 'versions'>('editor')
  const [contentMode, setContentMode] = useState<'edit' | 'preview'>('edit')
  const [showVersionForm, setShowVersionForm] = useState(false)
  const [newReleaseNotes, setNewReleaseNotes] = useState('')

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
              {/* Name + License row */}
              <div className="grid grid-cols-[1fr,200px] gap-3">
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
                      }}
                    >
                      {t('managed.skills.cancel')}
                    </Button>
                    <Button
                      size="sm"
                      className="h-7 text-xs"
                      disabled={isCreatingVersion}
                      onClick={() => {
                        onCreateVersion(newReleaseNotes.trim())
                        setShowVersionForm(false)
                        setNewReleaseNotes('')
                      }}
                    >
                      <Camera className="mr-1 h-3 w-3" />
                      {t('managed.skills.createVersionBtn')}
                    </Button>
                  </div>
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
      return managedPost<SkillRecord>('/skills', result.skillData)
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
          source_type: form.source_type,
          source_url: form.source_url,
        },
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
      )
    },
    onSuccess: (_file, { mode }) => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
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
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['skill-files', selectedSkillId],
      })
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({
        queryKey: ['skill', selectedSkillId],
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
    mutationFn: ({ releaseNotes }: { releaseNotes: string }) =>
      managedPost<SkillVersionRecord>(
        `/skills/${stripId(selectedSkillId!)}/versions`,
        {
          name: form.name,
          description: form.description,
          content: form.content,
          release_notes: releaseNotes,
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
      matchesSearch(searchQuery, [s.id, s.name, s.description, s.license, s.is_public ? 'public' : 'private']),
    )

    const filters: FilterDef[] = [
      {
        key: 'created',
        ...createCreatedTimeFilter(t),
        value: createdFilter,
        onChange: setCreatedFilter,
      },
    ]

    const columns: Column<SkillRecord>[] = [
      {
        key: 'id',
        header: t('managed.table.id'),
        render: (s) => <MonoId id={s.id} />,
      },
      {
        key: 'name',
        header: t('managed.table.name'),
        render: (s) => (
          <span className="font-medium text-foreground">{s.name}</span>
        ),
      },
      {
        key: 'description',
        header: t('managed.skills.description'),
        render: (s) => (
          <span className="text-muted-foreground line-clamp-1">
            {s.description || '-'}
          </span>
        ),
      },
      {
        key: 'license',
        header: t('managed.skills.license'),
        render: (s) => (
          <span className="text-muted-foreground">{s.license || '-'}</span>
        ),
      },
      {
        key: 'status',
        header: t('managed.table.status'),
        render: (s) => (
          <StatusBadge status={s.is_public ? 'active' : 'private'} />
        ),
      },
      {
        key: 'updated_at',
        header: t('managed.table.lastUpdated'),
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
                <Upload className="h-4 w-4" strokeWidth={2.25} />
                {t('managed.skills.importSkill')}
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

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col px-6 py-5">
      <div className="shrink-0">
        <PageHeader
          title={selectedSkill.name}
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
          onCreateVersion={(notes) =>
            createVersionMutation.mutate({
              releaseNotes: notes,
            })
          }
          isCreatingVersion={createVersionMutation.isPending}
        />
      </div>

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
