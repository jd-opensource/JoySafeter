'use client'
/**
 * AI-assisted skill authoring workspace — two-pane layout.
 *
 * ┌──────────────────────────┬───────────────────────────────────────────┐
 * │  💬 chat (transcript +   │  [预览 | 编辑器 | 元数据 | file tabs ...] │
 * │      input area, ~50%)   │  ┌── Projects ──┬────────── editor ─────┐│
 * │                          │  │ SKILL.md     │ ...                    ││
 * │                          │  │ scripts/     │                        ││
 * │                          │  └──────────────┴────────────────────────┘│
 * └──────────────────────────┴───────────────────────────────────────────┘
 *
 * State + side-effects live in ``useSkillAuthoring``. This page wires the
 * chat, tabbed workspace, Projects tree, and Monaco editor together. Multi-
 * file drafts get an IDE-style feel; the Preview tab renders SKILL.md as
 * final Markdown so users can sanity-check the doc without switching pages.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import {
  ArrowLeft,
  Cog,
  Download,
  FilePlus,
  FileText,
  FolderOpen,
  FolderPlus,
  Monitor,
  Play,
  Save,
  Search,
  Sparkles,
  Square,
  Upload,
  X,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { managedGet } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'
import {
  useSkillAuthoring,
  type SkillDraft,
  type SkillDraftFile,
} from '@/hooks/managed/use-skill-authoring'
import { useQuery } from '@tanstack/react-query'
import {
  FileTreeNode,
  buildFileTree,
  type SkillWorkspaceFile,
} from '@/components/managed/skills/skill-workspace'
import { SkillCodeEditor } from '@/components/managed/skills/skill-code-editor'
import { downloadDraftZip } from '@/lib/managed/skill-draft-zip'
import { severityLabelKey } from '@/lib/managed/skill-severity'
import type { Secret } from '@/types/managed'
import { parseSecretListResponse } from '@/lib/managed/secret-response-parsers'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

type SecretsResponse = { data?: unknown[] } | unknown[]

// Sentinel ids used by the tab bar. Preview / Editor / Metadata are pinned
// pseudo-files; everything else is keyed by its draft path.
const TAB_PREVIEW = '__preview__'
const TAB_EDITOR = '__editor__'
const TAB_METADATA = '__metadata__'

// ── adapters ────────────────────────────────────────────────────────────
// The Projects tree was written for the detail page which has fully-formed
// ``SkillFileRecord`` rows (id, size, file_type, ...). Drafts only carry
// ``{path, content}`` pairs. We synthesize the missing fields so the shared
// tree builder Just Works — the id is the draft path itself so callbacks
// round-trip cleanly.
function adaptDraftFiles(files: SkillDraftFile[]): SkillWorkspaceFile[] {
  return files.map((f, idx) => {
    const slashIdx = f.path.lastIndexOf('/')
    const dir = slashIdx >= 0 ? f.path.slice(0, slashIdx + 1) : ''
    const name = slashIdx >= 0 ? f.path.slice(slashIdx + 1) : f.path
    return {
      id: f.path || `__draft_${idx}__`,
      path: dir,
      file_name: name,
      size: f.content?.length || 0,
    }
  })
}

function inferFileType(name: string): string {
  const lower = name.toLowerCase()
  if (lower.endsWith('.py')) return 'python'
  if (lower.endsWith('.md')) return 'markdown'
  if (lower.endsWith('.json')) return 'json'
  if (lower.endsWith('.yaml') || lower.endsWith('.yml')) return 'yaml'
  if (lower.endsWith('.sh')) return 'shell'
  return 'text'
}

// ── page ────────────────────────────────────────────────────────────────

export default function SkillAiAuthoringPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { toast } = useToast()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const isFresh = searchParams.get('new') === '1'
  useEffect(() => {
    if (isFresh && typeof window !== 'undefined') {
      const url = new URL(window.location.href)
      url.searchParams.delete('new')
      window.history.replaceState({}, '', url.pathname + (url.search ? `?${url.searchParams}` : ''))
    }
  }, [isFresh])

  const {
    messages,
    draft,
    draftSkillId,
    streaming,
    scanRunning,
    scanResult,
    publishing,
    hydrated,
    setDraft,
    send,
    cancel,
    saveDraft,
    runScan,
    publish,
    reset,
  } = useSkillAuthoring({ startFresh: isFresh })

  const [input, setInput] = useState('')
  const [secretRef, setSecretRef] = useState('')

  // Tab state — which "file" is currently open in the workspace. Preview,
  // Editor, and Metadata are pinned tabs; per-file tabs live alongside.
  // ``activeFilePath`` remembers which file the Editor tab has focused so
  // the split view keeps its place when you flip to Preview and back.
  const [activeTab, setActiveTab] = useState<string>(TAB_EDITOR)
  const [activeFilePath, setActiveFilePath] = useState<string>('SKILL.md')

  const { data: secretsRes } = useQuery({
    queryKey: ['secrets', managedScope.key],
    queryFn: () => managedGet<SecretsResponse>('/secrets', managedRequestOptions(managedScope)),
    enabled: hasManagedRequestScope(managedScope),
  })
  const secrets = useMemo<Secret[]>(() => {
    if (!secretsRes) return []
    return parseSecretListResponse(Array.isArray(secretsRes) ? secretsRes : secretsRes.data || [])
  }, [secretsRes])

  const effectiveSecretRef = useMemo(() => {
    if (!secrets.length) return ''
    const secretNames = new Set(secrets.map((secret) => secret.name))
    if (secretRef && secretNames.has(secretRef)) return secretRef
    return (secrets.find((s) => s.is_default) || secrets[0]).name
  }, [secretRef, secrets])

  useEffect(() => {
    if (secretRef === effectiveSecretRef) return
    setSecretRef(effectiveSecretRef)
  }, [effectiveSecretRef, secretRef])

  useEffect(() => {
    setSecretRef('')
    setActiveTab(TAB_EDITOR)
    setActiveFilePath('SKILL.md')
  }, [managedScope.key])

  // When the split-view focus is on a file that no longer exists (AI rewrote
  // files[], or the user deleted it), fall back to SKILL.md.
  useEffect(() => {
    const validPaths = new Set(draft.files.map((f) => f.path))
    if (activeFilePath !== 'SKILL.md' && !validPaths.has(activeFilePath)) {
      setActiveFilePath('SKILL.md')
    }
  }, [draft.files, activeFilePath])

  const adaptedFiles = useMemo(() => adaptDraftFiles(draft.files), [draft.files])
  const treeFiles = useMemo(
    () => adaptedFiles.filter((f) => !(f.path === '' && f.file_name.toLowerCase() === 'skill.md')),
    [adaptedFiles],
  )
  const tree = useMemo(() => buildFileTree(treeFiles), [treeFiles])

  // ── file operations ──────────────────────────────────────────────────
  const onTreeSelectFile = (id: string) => {
    // The tree passes the SkillFileRecord.id we synthesized above; that id
    // IS the draft path, so we can route it directly to focus.
    setActiveFilePath(id)
    setActiveTab(TAB_EDITOR)
  }

  const onTreeDeleteFile = (id: string) => {
    if (!currentProjectAllowsWrite()) return
    setDraft((prev) => ({ ...prev, files: prev.files.filter((f) => f.path !== id) }))
  }

  const onTreeDeleteFolder = (folderPath: string) => {
    if (!currentProjectAllowsWrite()) return
    setDraft((prev) => ({
      ...prev,
      files: prev.files.filter((f) => !f.path.startsWith(folderPath)),
    }))
  }

  // Move a file or folder into another folder by rewriting path prefixes.
  // ``sourcePath`` is a file's full path or a folder's path (trailing ``/``);
  // ``destFolder`` is '' (root) or a folder path ending in ``/``.
  const onMove = (sourcePath: string, destFolder: string) => {
    if (!currentProjectAllowsWrite()) return
    const dest = destFolder ? destFolder.replace(/\/*$/, '/') : ''
    const isFolder = !draft.files.some((f) => f.path === sourcePath)

    if (isFolder) {
      const srcFolder = sourcePath.replace(/\/*$/, '/')
      const folderName = srcFolder.replace(/\/$/, '').split('/').pop() || ''
      // No-op if dropped into its own current parent; forbid dropping a folder
      // into itself or its own descendants.
      const currentParent = srcFolder.slice(0, srcFolder.length - (folderName.length + 1))
      if (dest === currentParent) return
      if (dest === srcFolder || dest.startsWith(srcFolder)) return

      let conflict = false
      setDraft((prev) => {
        const existing = new Set(prev.files.map((f) => f.path))
        const moved = prev.files.map((f) => {
          if (!f.path.startsWith(srcFolder)) return f
          const rest = f.path.slice(srcFolder.length)
          const newPath = `${dest}${folderName}/${rest}`
          if (newPath !== f.path && existing.has(newPath)) conflict = true
          return { ...f, path: newPath }
        })
        return { ...prev, files: moved }
      })
      if (conflict) toast({ title: t('managed.skills.aiAuthor.moveConflict') })
      if (activeFilePath.startsWith(srcFolder)) {
        setActiveFilePath(`${dest}${folderName}/${activeFilePath.slice(srcFolder.length)}`)
      }
      return
    }

    // File move.
    const baseName = sourcePath.split('/').pop() || sourcePath
    const currentDir = sourcePath.slice(0, sourcePath.length - baseName.length)
    if (dest === currentDir) return
    const newPath = `${dest}${baseName}`
    if (draft.files.some((f) => f.path === newPath)) {
      toast({ title: t('managed.skills.aiAuthor.moveConflict') })
      return
    }
    setDraft((prev) => ({
      ...prev,
      files: prev.files.map((f) => (f.path === sourcePath ? { ...f, path: newPath } : f)),
    }))
    if (activeFilePath === sourcePath) setActiveFilePath(newPath)
  }

  // Create a file. ``name`` comes from the tree's inline create row; the
  // folder "+" and toolbar "+" both drive that inline row now, so a name is
  // always supplied (no browser prompt).
  const onTreeAddToFolder = (folderPath: string, name?: string) => {
    if (!currentProjectAllowsWrite()) return
    const raw = name
    if (!raw) return
    const cleanName = raw.trim().replace(/^\/+/, '')
    if (!cleanName) return
    const newPath = folderPath + cleanName
    setDraft((prev) => {
      if (prev.files.some((f) => f.path === newPath)) return prev
      return { ...prev, files: [...prev.files, { path: newPath, content: '' }] }
    })
    setActiveFilePath(newPath)
    setActiveTab(TAB_EDITOR)
  }

  const onAddFolder = (name?: string) => {
    if (!currentProjectAllowsWrite()) return
    const raw = name
    if (!raw) return
    const cleanFolder = raw.trim().replace(/^\/+|\/+$/g, '')
    if (!cleanFolder) return
    const placeholderPath = `${cleanFolder}/.gitkeep`
    setDraft((prev) => {
      if (prev.files.some((f) => f.path.startsWith(`${cleanFolder}/`))) return prev
      return { ...prev, files: [...prev.files, { path: placeholderPath, content: '' }] }
    })
  }

  // ── upload / download ──────────────────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null)

  const onUploadClick = () => {
    if (!currentProjectAllowsWrite()) return
    fileInputRef.current?.click()
  }

  const onUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!currentProjectAllowsWrite()) {
      e.target.value = ''
      return
    }
    const list = Array.from(e.target.files || [])
    e.target.value = '' // allow re-selecting the same file
    if (list.length === 0) return

    // Only text files, capped in size, are importable. Non-text / oversized
    // files are skipped silently (surfaced via the count in the toast).
    const MAX_BYTES = 1024 * 1024 // 1MB per file
    const TEXT_EXT =
      /\.(md|markdown|txt|json|ya?ml|py|js|ts|tsx|jsx|sh|toml|cfg|ini|csv|html?|xml|env)$/i

    // Strip a common leading directory (webkitdirectory prefixes every path
    // with the picked folder's name).
    const rels = list.map(
      (f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name,
    )
    const firstSeg = (p: string) => p.split('/')[0]
    const commonRoot =
      rels.length > 1 && rels.every((p) => p.includes('/') && firstSeg(p) === firstSeg(rels[0]))
        ? `${firstSeg(rels[0])}/`
        : ''

    const collected: SkillDraftFile[] = []
    let skillMdBody: string | null = null
    for (let i = 0; i < list.length; i++) {
      const file = list[i]
      if (file.size > MAX_BYTES || !TEXT_EXT.test(file.name)) continue
      let rel = rels[i]
      if (commonRoot && rel.startsWith(commonRoot)) rel = rel.slice(commonRoot.length)
      rel = rel.replace(/^\/+/, '')
      if (!rel) continue
      const content = await file.text()
      if (rel === 'SKILL.md') {
        skillMdBody = content
      } else {
        collected.push({ path: rel, content })
      }
    }

    if (collected.length === 0 && skillMdBody === null) {
      toast({ title: t('managed.skills.aiAuthor.uploadEmpty') })
      return
    }

    setDraft((prev) => {
      const byPath = new Map(prev.files.map((f) => [f.path, f]))
      for (const f of collected) byPath.set(f.path, f) // same-path overwrite
      return {
        ...prev,
        content: skillMdBody !== null ? skillMdBody : prev.content,
        files: Array.from(byPath.values()),
      }
    })
    const count = collected.length + (skillMdBody !== null ? 1 : 0)
    toast({ title: t('managed.skills.aiAuthor.uploadSuccess', { count }) })
  }

  const onDownload = () => {
    downloadDraftZip(draft)
  }

  const updateFileContent = (filePath: string, newContent: string) => {
    if (!currentProjectAllowsWrite()) return
    setDraft((prev) => ({
      ...prev,
      files: prev.files.map((f) => (f.path === filePath ? { ...f, content: newContent } : f)),
    }))
  }

  // ── chat ─────────────────────────────────────────────────────────────
  const onSend = async () => {
    if (!currentProjectAllowsWrite()) return
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    await send(text, effectiveSecretRef)
  }

  // Publish: save → submit → approve → cut first version, so the skill
  // becomes referenceable by agents (which only see published versions).
  const onPublish = async () => {
    if (!currentProjectAllowsWrite()) return
    if (!draft.name.trim()) {
      toast({ title: t('managed.skills.aiAuthor.errors.nameRequired'), variant: 'destructive' })
      return
    }
    const { skillId, error } = await publish()
    if (!skillId) {
      toast({
        title: error || t('managed.skills.aiAuthor.errors.saveFailed'),
        variant: 'destructive',
      })
      return
    }
    if (error) {
      // Saved, but version publish failed — keep the user here with the
      // reason rather than silently navigating away.
      toast({ title: error, variant: 'destructive' })
      return
    }
    toast({ title: t('managed.skills.aiAuthor.publishedToast') })
    reset()
    router.push(`/managed/skills?selected=${stripIdPrefix(skillId)}`)
  }

  // The active file for the Editor tab's right-hand side.
  const activeFile = useMemo(() => {
    if (activeFilePath === 'SKILL.md') return null
    return draft.files.find((f) => f.path === activeFilePath) || null
  }, [activeFilePath, draft.files])

  return (
    <div className="-m-5 flex h-screen flex-col bg-background">
      {/* Hidden file input for uploads (multi-file / folder import) */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={onUploadChange}
        disabled={projectReadOnly}
      />
      {/* Header bar */}
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/managed/skills')}
            className="gap-1"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('managed.skills.aiAuthor.back')}
          </Button>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-purple-500" />
            <h1 className="text-sm font-medium">{t('managed.skills.aiAuthor.title')}</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {secrets.length === 0 && (
            <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
              {t('managed.skills.aiAuthor.noSecrets')}
            </span>
          )}
          {/* Wrapped in a span so the tooltip still shows while the button
              is disabled (disabled buttons don't emit hover events). */}
          <span title={!draftSkillId ? t('managed.skills.aiAuthor.scan.saveFirst') : undefined}>
            <Button
              variant="outline"
              size="sm"
              onClick={runScan}
              disabled={projectReadOnly || !draftSkillId || scanRunning}
            >
              <Search className="mr-1 h-3.5 w-3.5" />
              {scanRunning
                ? t('managed.skills.aiAuthor.scan.running')
                : t('managed.skills.aiAuthor.scan.run')}
            </Button>
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={saveDraft}
            disabled={projectReadOnly || streaming || publishing || !draft.name.trim()}
          >
            <Save className="mr-1 h-3.5 w-3.5" />
            {t('managed.skills.aiAuthor.saveDraft')}
          </Button>
          <Button
            size="sm"
            onClick={onPublish}
            disabled={projectReadOnly || streaming || publishing || !draft.name.trim()}
          >
            {publishing
              ? t('managed.skills.aiAuthor.publishing')
              : t('managed.skills.aiAuthor.publish')}
          </Button>
        </div>
      </div>

      {/* Body: two panes — chat (left, ~50%) | workspace (right, ~50%) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: chat */}
        <div className="flex w-[420px] shrink-0 flex-col">
          <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {hydrated && messages.length === 0 && <Greeting />}
            {messages.map((m, i) => (
              <ChatBubble key={i} role={m.role} content={m.content} />
            ))}
            {streaming && (
              <div className="text-xs text-muted-foreground">
                {t('managed.skills.aiAuthor.thinking')}
              </div>
            )}
            {scanResult && <ScanResultBadge result={scanResult} />}
          </div>
          <ChatComposer
            input={input}
            setInput={setInput}
            onSend={onSend}
            onCancel={cancel}
            streaming={streaming}
            readOnly={projectReadOnly}
          />
        </div>

        {/* Right: tabbed workspace — tabs sit above a rounded card */}
        <div className="flex flex-1 flex-col overflow-hidden bg-muted/20 px-4 pb-3 pt-4">
          {/* Tab bar — bordered active tab, plain non-active */}
          <div className="mb-3 flex shrink-0 items-center gap-2 overflow-x-auto">
            <WorkspaceTab
              icon={<Monitor className="h-4 w-4" />}
              label={t('managed.skills.aiAuthor.tabs.preview')}
              active={activeTab === TAB_PREVIEW}
              onClick={() => setActiveTab(TAB_PREVIEW)}
            />
            <WorkspaceTab
              icon={<FolderOpen className="h-4 w-4" />}
              label={t('managed.skills.aiAuthor.tabs.editor')}
              active={activeTab === TAB_EDITOR}
              onClick={() => setActiveTab(TAB_EDITOR)}
            />
            <WorkspaceTab
              icon={<Cog className="h-4 w-4" />}
              label={t('managed.skills.aiAuthor.tabs.metadata')}
              active={activeTab === TAB_METADATA}
              onClick={() => setActiveTab(TAB_METADATA)}
            />
          </div>

          {/* Content card */}
          <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-border bg-background shadow-sm">
            {/* Active pane */}
            <div className="flex flex-1 flex-col overflow-hidden">
              {activeTab === TAB_PREVIEW ? (
                <>
                  <SectionHeader title={t('managed.skills.aiAuthor.tabs.preview')} />
                  <PreviewPane markdown={draft.content} />
                </>
              ) : activeTab === TAB_METADATA ? (
                <>
                  <SectionHeader title={t('managed.skills.aiAuthor.tabs.metadata')} />
                  <MetadataPane draft={draft} onChange={setDraft} readOnly={projectReadOnly} />
                </>
              ) : (
                <>
                  <SectionHeader title={t('managed.skills.aiAuthor.tabs.editor')} />
                  <EditorSplitPane
                    draft={draft}
                    tree={tree}
                    activeFile={activeFile}
                    activeFilePath={activeFilePath}
                    onAddFolder={onAddFolder}
                    onUpload={onUploadClick}
                    onDownload={onDownload}
                    onTreeSelectFile={onTreeSelectFile}
                    onTreeAddToFolder={onTreeAddToFolder}
                    onTreeDeleteFile={onTreeDeleteFile}
                    onTreeDeleteFolder={onTreeDeleteFolder}
                    onMove={onMove}
                    onSelectMain={() => setActiveFilePath('SKILL.md')}
                    onEditSkillMd={(v) => {
                      if (!currentProjectAllowsWrite()) return
                      setDraft((prev) => ({ ...prev, content: v }))
                    }}
                    onEditFile={updateFileContent}
                    canEdit={!projectReadOnly}
                  />
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── pieces ────────────────────────────────────────────────────────────────

function Greeting() {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg bg-muted/40 p-4">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium">
        <Sparkles className="h-4 w-4 text-purple-500" />
        {t('managed.skills.aiAuthor.greeting.title')}
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t('managed.skills.aiAuthor.greeting.body')}
      </p>
    </div>
  )
}

function ChatBubble({ role, content }: { role: 'user' | 'assistant'; content: string }) {
  const isUser = role === 'user'
  const isEmpty = !content
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={
          isUser
            ? 'max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground'
            : 'max-w-[85%] whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm'
        }
      >
        {isEmpty && !isUser ? (
          <span className="inline-flex gap-0.5 text-muted-foreground/60">
            <span className="animate-pulse">·</span>
            <span className="animate-pulse [animation-delay:150ms]">·</span>
            <span className="animate-pulse [animation-delay:300ms]">·</span>
          </span>
        ) : (
          content
        )}
      </div>
    </div>
  )
}

function ChatComposer({
  input,
  setInput,
  onSend,
  onCancel,
  streaming,
  readOnly,
}: {
  input: string
  setInput: (v: string) => void
  onSend: () => void
  onCancel: () => void
  streaming: boolean
  readOnly: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="bg-background px-4 py-3">
      <div
        className={`group relative rounded-2xl border bg-background shadow-sm transition-all focus-within:border-primary/50 focus-within:shadow-md focus-within:ring-2 focus-within:ring-primary/10 ${
          streaming ? 'opacity-80' : ''
        }`}
      >
        <Textarea
          value={input}
          onChange={(e) => {
            if (readOnly) return
            setInput(e.target.value)
          }}
          onKeyDown={(e) => {
            if (readOnly) return
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              onSend()
            }
          }}
          placeholder={t('managed.skills.aiAuthor.inputPlaceholder')}
          className="min-h-[80px] resize-none border-0 bg-transparent px-4 pb-12 pt-3 text-sm leading-relaxed shadow-none placeholder:text-muted-foreground/60 focus-visible:ring-0 focus-visible:ring-offset-0"
          disabled={streaming || readOnly}
        />
        {/* Bottom action row overlaid on the textarea */}
        <div className="pointer-events-none absolute inset-x-2 bottom-2 flex items-center justify-end">
          <div className="pointer-events-auto flex items-center gap-1">
            {streaming ? (
              <button
                type="button"
                onClick={onCancel}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-foreground text-background shadow-sm transition-opacity hover:opacity-90"
                title={t('managed.skills.aiAuthor.cancel')}
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={readOnly || !input.trim()}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-foreground text-background shadow-sm transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none"
                title={t('managed.skills.aiAuthor.send')}
              >
                <Play className="h-4 w-4 translate-x-[1px] fill-current" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function WorkspaceTab({
  icon,
  label,
  active,
  closable,
  onClick,
  onClose,
}: {
  icon: React.ReactNode
  label: string
  active: boolean
  closable?: boolean
  onClick: () => void
  onClose?: () => void
}) {
  return (
    <div
      onClick={onClick}
      className={`group flex shrink-0 cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors ${
        active
          ? 'border border-foreground/80 bg-background font-medium text-foreground shadow-sm'
          : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
      }`}
    >
      {icon}
      <span>{label}</span>
      {closable && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onClose?.()
          }}
          className="ml-0.5 rounded p-0.5 text-muted-foreground/70 hover:bg-muted hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="border-border/60 shrink-0 border-b px-5 py-3 text-sm font-medium text-foreground">
      {title}
    </div>
  )
}

// ── Editor tab: Projects tree (left) + Monaco editor (right) ────────────
function EditorSplitPane({
  draft,
  tree,
  activeFile,
  activeFilePath,
  onAddFolder,
  onUpload,
  onDownload,
  onTreeSelectFile,
  onTreeAddToFolder,
  onTreeDeleteFile,
  onTreeDeleteFolder,
  onMove,
  onSelectMain,
  onEditSkillMd,
  onEditFile,
  canEdit,
}: {
  draft: SkillDraft
  tree: ReturnType<typeof buildFileTree>
  activeFile: SkillDraftFile | null
  activeFilePath: string
  onAddFolder: (name?: string) => void
  onUpload: () => void
  onDownload: () => void
  onTreeSelectFile: (id: string) => void
  onTreeAddToFolder: (folderPath: string, name?: string) => void
  onTreeDeleteFile: (id: string) => void
  onTreeDeleteFolder: (folderPath: string) => void
  onMove: (sourcePath: string, destFolderPath: string) => void
  onSelectMain: () => void
  onEditSkillMd: (v: string) => void
  onEditFile: (path: string, v: string) => void
  canEdit: boolean
}) {
  const { t } = useTranslation()
  const showingSkillMd = activeFilePath === 'SKILL.md'
  // Inline "new file / new folder" row shown at the bottom of the tree.
  // ``targetFolder`` is the directory a new file lands in — '' for the root
  // toolbar "+", or a folder path when the "+" on a folder node was clicked.
  const [creating, setCreating] = useState<'file' | 'folder' | null>(null)
  const [newName, setNewName] = useState('')
  const [targetFolder, setTargetFolder] = useState('')

  const startCreate = (kind: 'file' | 'folder', folder = '') => {
    if (!canEdit) return
    setNewName('')
    setTargetFolder(folder)
    setCreating(kind)
  }
  const cancelCreate = () => {
    setCreating(null)
    setNewName('')
    setTargetFolder('')
  }
  const commitCreate = () => {
    if (!canEdit) {
      cancelCreate()
      return
    }
    const name = newName.trim()
    if (name) {
      if (creating === 'folder') onAddFolder(name)
      else onTreeAddToFolder(targetFolder, name)
    }
    cancelCreate()
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Projects panel */}
      <div className="border-border/60 flex w-[320px] shrink-0 flex-col border-r bg-background">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm font-medium text-foreground">
            {t('managed.skills.aiAuthor.tabs.projects')}
          </span>
          <div className="flex items-center gap-0.5">
            {canEdit && (
              <>
                <button
                  onClick={() => startCreate('file')}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={t('managed.skills.aiAuthor.fields.newFileName')}
                >
                  <FilePlus className="h-4 w-4" />
                </button>
                <button
                  onClick={() => startCreate('folder')}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={t('managed.skills.newFolder')}
                >
                  <FolderPlus className="h-4 w-4" />
                </button>
                <button
                  onClick={onUpload}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={t('managed.skills.aiAuthor.upload')}
                >
                  <Upload className="h-4 w-4" />
                </button>
              </>
            )}
            <button
              onClick={onDownload}
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title={t('managed.skills.aiAuthor.download')}
            >
              <Download className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div
          className="flex-1 overflow-y-auto pb-2 text-sm"
          onDragOver={canEdit ? (e) => e.preventDefault() : undefined}
          onDrop={(e) => {
            if (!canEdit) return
            const source = e.dataTransfer.getData('text/plain')
            if (source) onMove(source, '')
          }}
        >
          {/* SKILL.md — always first */}
          <div
            onClick={onSelectMain}
            className={`flex cursor-pointer items-center gap-2 px-4 py-1.5 transition-colors hover:bg-muted/50 ${
              showingSkillMd ? 'bg-muted font-medium' : ''
            }`}
          >
            <FileText className="h-4 w-4 text-blue-500" />
            <span>SKILL.md</span>
          </div>
          {tree.children.length > 0
            ? tree.children.map((child, i) => (
                <FileTreeNode
                  key={child.file?.id ?? child.fullPath + i}
                  node={child}
                  depth={0}
                  selectedFileId={showingSkillMd ? null : activeFilePath}
                  onSelectFile={onTreeSelectFile}
                  onDeleteFile={onTreeDeleteFile}
                  onDeleteFolder={onTreeDeleteFolder}
                  onAddToFolder={(folderPath) => startCreate('file', folderPath)}
                  onMove={canEdit ? onMove : undefined}
                  canEdit={canEdit}
                />
              ))
            : null}

          {/* Inline new-file / new-folder input row */}
          {canEdit && creating && (
            <div className="flex items-center gap-2 px-4 py-1.5">
              {creating === 'folder' ? (
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <FileText className="h-4 w-4 shrink-0 text-blue-500" />
              )}
              {creating === 'file' && targetFolder && (
                <span className="shrink-0 truncate text-xs text-muted-foreground/70">
                  {targetFolder}
                </span>
              )}
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    commitCreate()
                  } else if (e.key === 'Escape') {
                    e.preventDefault()
                    cancelCreate()
                  }
                }}
                onBlur={commitCreate}
                placeholder={
                  creating === 'folder'
                    ? t('managed.skills.aiAuthor.fields.newFolderName')
                    : t('managed.skills.aiAuthor.fields.newFileName')
                }
                className="min-w-0 flex-1 rounded-md border border-primary/50 bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
            </div>
          )}
        </div>
      </div>

      {/* Editor pane */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {showingSkillMd ? (
          <EditorPane
            path="SKILL.md"
            fileType="markdown"
            value={draft.content}
            onChange={onEditSkillMd}
            readOnly={!canEdit}
          />
        ) : activeFile ? (
          <EditorPane
            path={activeFile.path}
            fileType={inferFileType(activeFile.path)}
            value={activeFile.content}
            onChange={(v) => onEditFile(activeFile.path, v)}
            readOnly={!canEdit}
          />
        ) : null}
      </div>
    </div>
  )
}

function MetadataPane({
  draft,
  onChange,
  readOnly,
}: {
  draft: SkillDraft
  onChange: (updater: (prev: SkillDraft) => SkillDraft) => void
  readOnly: boolean
}) {
  const { t } = useTranslation()
  const tagsStr = draft.tags.join(', ')
  return (
    <div className="space-y-4 overflow-y-auto p-6">
      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('managed.skills.aiAuthor.fields.name')}
        </label>
        <Input
          value={draft.name}
          maxLength={64}
          onChange={(e) => {
            if (readOnly) return
            onChange((p) => ({ ...p, name: e.target.value }))
          }}
          placeholder={t('managed.skills.aiAuthor.fields.namePlaceholder')}
          disabled={readOnly}
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('managed.skills.aiAuthor.fields.description')}
        </label>
        <Textarea
          value={draft.description}
          maxLength={1024}
          onChange={(e) => {
            if (readOnly) return
            onChange((p) => ({ ...p, description: e.target.value }))
          }}
          placeholder={t('managed.skills.aiAuthor.fields.descriptionPlaceholder')}
          className="min-h-[72px] resize-none"
          disabled={readOnly}
        />
      </div>
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('managed.skills.aiAuthor.fields.tags')}
          </label>
          <Input
            value={tagsStr}
            onChange={(e) => {
              if (readOnly) return
              onChange((p) => ({
                ...p,
                tags: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              }))
            }}
            placeholder={t('managed.skills.aiAuthor.fields.tagsPlaceholder')}
            disabled={readOnly}
          />
        </div>
      </div>
    </div>
  )
}

function EditorPane({
  path,
  fileType,
  value,
  onChange,
  readOnly = false,
}: {
  path: string
  fileType: string
  value: string
  onChange: (v: string) => void
  readOnly?: boolean
}) {
  return (
    <>
      <div className="shrink-0 border-b bg-muted/10 px-4 py-2 text-xs text-muted-foreground">
        <FileText className="mr-1 inline h-3 w-3" />
        {path}
      </div>
      <div className="flex-1 overflow-hidden">
        <SkillCodeEditor
          value={value}
          onChange={onChange}
          readOnly={readOnly}
          fileType={fileType}
          fileName={path.split('/').pop()}
          height="100%"
          minHeight="100%"
        />
      </div>
    </>
  )
}

function PreviewPane({ markdown }: { markdown: string }) {
  const { t } = useTranslation()
  const trimmed = (markdown || '').trim()
  if (!trimmed) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-muted-foreground/70">
        {t('managed.skills.aiAuthor.previewEmpty')}
      </div>
    )
  }
  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <div className="mx-auto max-w-3xl">
        <div className="prose prose-sm max-w-none dark:prose-invert">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              pre: ({ children }) => (
                <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-3 text-xs leading-relaxed text-foreground">
                  {children}
                </pre>
              ),
              code: ({ children, className }) => (
                <code
                  className={
                    className
                      ? 'font-mono text-foreground'
                      : 'rounded bg-muted px-1 py-0.5 font-mono text-foreground'
                  }
                >
                  {children}
                </code>
              ),
            }}
          >
            {trimmed}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}

function ScanResultBadge({
  result,
}: {
  result: {
    status?: string
    severity?: string | null
    score?: number | null
    issues_count?: number
    error_message?: string | null
  }
}) {
  const { t } = useTranslation()
  const statusLabel = result.status
    ? t(`managed.skills.aiAuthor.scan.status.${result.status}`, { defaultValue: result.status })
    : '-'
  const color =
    result.status === 'passed'
      ? 'border-emerald-500/40 bg-emerald-500/10'
      : result.status === 'warning'
        ? 'border-amber-500/40 bg-amber-500/10'
        : result.status === 'blocked' || result.status === 'failed'
          ? 'border-destructive/40 bg-destructive/10'
          : 'border-border bg-muted/40'
  return (
    <div className={`rounded border ${color} p-3 text-xs`}>
      <div className="mb-1 font-medium">{t('managed.skills.aiAuthor.scan.title')}</div>
      <div className="space-y-0.5">
        <div>
          <span className="text-muted-foreground">
            {t('managed.skills.aiAuthor.scan.statusLabel')}:{' '}
          </span>
          <span>{statusLabel}</span>
        </div>
        {result.severity && (
          <div>
            <span className="text-muted-foreground">
              {t('managed.skills.aiAuthor.scan.severityLabel')}:{' '}
            </span>
            <span>{t(severityLabelKey(result.severity))}</span>
          </div>
        )}
        {typeof result.issues_count === 'number' && (
          <div>
            <span className="text-muted-foreground">
              {t('managed.skills.aiAuthor.scan.issuesLabel')}:{' '}
            </span>
            <span>{result.issues_count}</span>
          </div>
        )}
        {result.error_message && (
          <div>
            <span className="text-muted-foreground">
              {t('managed.skills.aiAuthor.scan.errorLabel')}:{' '}
            </span>
            <span>{result.error_message}</span>
          </div>
        )}
      </div>
    </div>
  )
}
