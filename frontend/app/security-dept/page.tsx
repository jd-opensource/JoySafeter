'use client'

import {
  Activity,
  AlertTriangle,
  Clock3,
  PlayCircle,
  RefreshCcw,
  Shield,
  Square,
  TerminalSquare,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import {
  SecurityDeptHealthResponse,
  SecurityDeptProfile,
  SecurityDeptSkill,
  SecurityDeptStreamEvent,
  SecurityDeptTask,
  securityDeptService,
} from '@/services/securityDeptService'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'queued':
      return 'bg-slate-100 text-slate-700 border-slate-200'
    case 'running':
      return 'bg-amber-100 text-amber-700 border-amber-200'
    case 'completed':
      return 'bg-emerald-100 text-emerald-700 border-emerald-200'
    case 'failed':
      return 'bg-rose-100 text-rose-700 border-rose-200'
    case 'cancelled':
      return 'bg-zinc-100 text-zinc-600 border-zinc-200'
    default:
      return 'bg-slate-100 text-slate-700 border-slate-200'
  }
}

function formatTime(value: string | null): string {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString()
}

function formatEventLine(event: SecurityDeptStreamEvent): string {
  const at = new Date(event.timestamp).toLocaleTimeString()
  const data = event.data || {}
  if (event.type === 'content') {
    return `[${at}] content: ${String(data.delta || '').trim()}`
  }
  if (event.type === 'status') {
    return `[${at}] status: ${String(data.status || data.message || '')}`
  }
  if (event.type === 'tool_call') {
    return `[${at}] tool_call: ${String(data.tool_name || '')}`
  }
  if (event.type === 'tool_result') {
    return `[${at}] tool_result: ${String(data.tool_use_id || '')}`
  }
  if (event.type === 'summary') {
    return `[${at}] summary generated`
  }
  if (event.type === 'error') {
    return `[${at}] error: ${String(data.message || data.code || '')}`
  }
  if (event.type === 'done') {
    return `[${at}] done: ${String(data.status || '')}`
  }
  return `[${at}] ${event.type}: ${JSON.stringify(data)}`
}

export default function SecurityDeptPage() {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [health, setHealth] = useState<SecurityDeptHealthResponse | null>(null)
  const [profiles, setProfiles] = useState<SecurityDeptProfile[]>([])
  const [skills, setSkills] = useState<SecurityDeptSkill[]>([])
  const [tasks, setTasks] = useState<SecurityDeptTask[]>([])

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)

  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [eventLogByTask, setEventLogByTask] = useState<Record<string, SecurityDeptStreamEvent[]>>({})

  const [profile, setProfile] = useState('pentest_full_access_v1')
  const [target, setTarget] = useState('')
  const [instruction, setInstruction] = useState('')
  const [selectedSkills, setSelectedSkills] = useState<string[]>([])

  const streamAbortRef = useRef<AbortController | null>(null)

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) || null,
    [selectedTaskId, tasks]
  )
  const eventLog = useMemo(
    () => (selectedTaskId ? eventLogByTask[selectedTaskId] || [] : []),
    [eventLogByTask, selectedTaskId]
  )

  const appendEvent = useCallback((event: SecurityDeptStreamEvent) => {
    setEventLogByTask((prev) => {
      const next = [...(prev[event.task_id] || []), event].slice(-250)
      return {
        ...prev,
        [event.task_id]: next,
      }
    })
  }, [])

  const refreshTasks = useCallback(async (keepSelection = true) => {
    const data = await securityDeptService.listTasks({ page: 1, page_size: 30 })
    setTasks(data.items || [])
    setSelectedTaskId((prev) => {
      if (!data.items || data.items.length === 0) {
        return null
      }
      if (keepSelection && prev && data.items.some((task) => task.id === prev)) {
        return prev
      }
      return data.items[0].id
    })
  }, [])

  const stopStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
  }, [])

  const startStream = useCallback(
    (taskId: string) => {
      stopStream()
      setStreamError(null)
      const controller = new AbortController()
      streamAbortRef.current = controller

      void securityDeptService.streamTaskEvents({
        taskId,
        signal: controller.signal,
        onEvent: (event) => {
          appendEvent(event)
          if (event.type === 'summary' || event.type === 'error' || event.type === 'done') {
            void refreshTasks(true)
          }
        },
        onError: (error) => {
          setStreamError(error.message)
        },
      })
    },
    [appendEvent, refreshTasks, stopStream]
  )

  useEffect(() => {
    const bootstrap = async () => {
      setLoading(true)
      try {
        const [healthResponse, profilesResponse, skillsResponse] = await Promise.all([
          securityDeptService.getHealth(),
          securityDeptService.listProfiles(),
          securityDeptService.listSkills(),
        ])
        setHealth(healthResponse)
        setProfiles(profilesResponse)
        setSkills(skillsResponse.items || [])
        if (profilesResponse.length > 0) {
          setProfile(profilesResponse[0].name)
        }
        await refreshTasks(false)
      } catch (error) {
        toast({
          variant: 'destructive',
          title: t('securityDept.loadFailed', { defaultValue: '加载安全部页面失败' }),
          description: error instanceof Error ? error.message : String(error),
        })
      } finally {
        setLoading(false)
      }
    }

    void bootstrap()

    return () => {
      stopStream()
    }
  }, [refreshTasks, stopStream, t, toast])

  useEffect(() => {
    if (!selectedTaskId) {
      stopStream()
      return
    }
    startStream(selectedTaskId)
    return () => {
      stopStream()
    }
  }, [selectedTaskId, startStream, stopStream])

  useEffect(() => {
    const timer = setInterval(() => {
      void refreshTasks(true)
    }, 5000)
    return () => clearInterval(timer)
  }, [refreshTasks])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshTasks(true)
    } finally {
      setRefreshing(false)
    }
  }

  const handleCreateTask = async () => {
    if (!instruction.trim()) {
      toast({
        variant: 'destructive',
        title: t('securityDept.instructionRequired', { defaultValue: '请先填写任务指令' }),
      })
      return
    }
    setIsCreating(true)
    try {
      const created = await securityDeptService.createTask({
        scenario: 'pentest',
        profile,
        target: target.trim() || undefined,
        instruction: instruction.trim(),
        skill_names: selectedSkills,
      })

      toast({
        title: t('securityDept.taskCreated', { defaultValue: '任务已创建' }),
        description: `${t('securityDept.taskId', { defaultValue: '任务 ID' })}: ${created.task_id}`,
      })

      setInstruction('')
      await refreshTasks(false)
      setSelectedTaskId(created.task_id)
    } catch (error) {
      toast({
        variant: 'destructive',
        title: t('securityDept.createFailed', { defaultValue: '创建任务失败' }),
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setIsCreating(false)
    }
  }

  const handleCancelSelectedTask = async () => {
    if (!selectedTask) {
      return
    }
    try {
      await securityDeptService.cancelTask(selectedTask.id)
      toast({
        title: t('securityDept.cancelled', { defaultValue: '任务已取消' }),
      })
      await refreshTasks(true)
    } catch (error) {
      toast({
        variant: 'destructive',
        title: t('securityDept.cancelFailed', { defaultValue: '取消任务失败' }),
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const toggleSkill = (skillName: string) => {
    setSelectedSkills((prev) =>
      prev.includes(skillName) ? prev.filter((item) => item !== skillName) : [...prev, skillName]
    )
  }

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[#f8f8f7]">
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <RefreshCcw className="h-4 w-4 animate-spin" />
          {t('securityDept.loading', { defaultValue: '加载中...' })}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-full bg-[radial-gradient(90%_120%_at_0%_0%,#eef6ff_0%,#f8f8f7_45%,#fdfbf5_100%)] px-4 py-4 md:px-6 md:py-6">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4">
        <Card className="rounded-2xl border-[#d9e0e8] bg-white/90 p-4 shadow-sm backdrop-blur-sm md:p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-start gap-3">
              <div className="rounded-xl border border-[#1f4e7a1f] bg-[#1f4e7a14] p-2.5 text-[#1f4e7a]">
                <Shield className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-semibold tracking-tight text-slate-900">
                  {t('securityDept.title', { defaultValue: '一个人的安全部' })}
                </h1>
                <p className="mt-1 text-sm text-slate-600">
                  {t('securityDept.subtitle', {
                    defaultValue: '在独立目录中编排安全任务，持续扩展而不干扰现有开发流。',
                  })}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={cn(
                  'border',
                  health?.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'
                )}
              >
                {health?.enabled
                  ? t('securityDept.moduleEnabled', { defaultValue: '模块已启用' })
                  : t('securityDept.moduleDisabled', { defaultValue: '模块未启用' })}
              </Badge>
              <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                Redis {health?.redis_available ? 'OK' : 'OFF'}
              </Badge>
              <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                SDK {health?.sdk_installed ? 'OK' : 'MISSING'}
              </Badge>
              <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                CLI {health?.cli_found ? 'OK' : 'MISSING'}
              </Badge>
            </div>
          </div>
        </Card>

        <div className="grid gap-4 lg:grid-cols-[370px_minmax(0,1fr)]">
          <Card className="rounded-2xl border-[#d9e0e8] bg-white/95 p-4 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <PlayCircle className="h-4 w-4 text-[#1f4e7a]" />
              <h2 className="text-sm font-semibold text-slate-900">
                {t('securityDept.createTask', { defaultValue: '创建安全任务' })}
              </h2>
            </div>

            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-slate-600">
                  {t('securityDept.profile', { defaultValue: '执行策略' })}
                </Label>
                <Select value={profile} onValueChange={setProfile}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {profiles.map((item) => (
                      <SelectItem key={item.name} value={item.name}>
                        {item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-slate-600">
                  {t('securityDept.target', { defaultValue: '目标（可选）' })}
                </Label>
                <Input
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  className="h-9"
                  placeholder={t('securityDept.targetPlaceholder', { defaultValue: '例如: https://demo.example.com' })}
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-slate-600">
                  {t('securityDept.instruction', { defaultValue: '任务指令' })}
                </Label>
                <Textarea
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder={t('securityDept.instructionPlaceholder', {
                    defaultValue: '描述你的安全场景、预期目标、输出格式和边界约束...',
                  })}
                  className="min-h-[140px] resize-y"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-slate-600">
                  {t('securityDept.skills', { defaultValue: '技能目录（可选）' })}
                </Label>
                <div className="max-h-[180px] space-y-1.5 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
                  {skills.length === 0 && (
                    <p className="px-2 py-2 text-xs text-slate-500">
                      {t('securityDept.noSkills', { defaultValue: '未发现可用技能目录' })}
                    </p>
                  )}
                  {skills.map((skill) => {
                    const checked = selectedSkills.includes(skill.skill_name)
                    return (
                      <button
                        type="button"
                        key={skill.skill_name}
                        onClick={() => toggleSkill(skill.skill_name)}
                        className={cn(
                          'w-full rounded-lg border px-2 py-1.5 text-left transition-colors',
                          checked
                            ? 'border-[#1f4e7a3f] bg-[#1f4e7a14]'
                            : 'border-slate-200 bg-white hover:bg-slate-100'
                        )}
                      >
                        <p className="text-xs font-medium text-slate-800">{skill.display_name}</p>
                        <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">
                          {skill.description || skill.skill_name}
                        </p>
                      </button>
                    )
                  })}
                </div>
              </div>

              <Button
                onClick={handleCreateTask}
                disabled={isCreating || !health?.enabled}
                className="h-9 w-full bg-[#1f4e7a] text-white hover:bg-[#183d62]"
              >
                {isCreating
                  ? t('securityDept.creating', { defaultValue: '创建中...' })
                  : t('securityDept.runTask', { defaultValue: '启动任务' })}
              </Button>
            </div>
          </Card>

          <div className="flex min-h-[70vh] flex-col gap-4">
            <Card className="rounded-2xl border-[#d9e0e8] bg-white/95 p-4 shadow-sm">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[#1f4e7a]" />
                  <h2 className="text-sm font-semibold text-slate-900">
                    {t('securityDept.taskQueue', { defaultValue: '任务队列' })}
                  </h2>
                </div>
                <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
                  <RefreshCcw className={cn('mr-1 h-3.5 w-3.5', refreshing && 'animate-spin')} />
                  {t('securityDept.refresh', { defaultValue: '刷新' })}
                </Button>
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50/80 hover:bg-slate-50/80">
                      <TableHead className="h-9 text-xs">{t('securityDept.taskId', { defaultValue: '任务 ID' })}</TableHead>
                      <TableHead className="h-9 text-xs">{t('securityDept.status', { defaultValue: '状态' })}</TableHead>
                      <TableHead className="h-9 text-xs">{t('securityDept.target', { defaultValue: '目标' })}</TableHead>
                      <TableHead className="h-9 text-xs">{t('securityDept.createdAt', { defaultValue: '创建时间' })}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasks.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="py-10 text-center text-sm text-slate-500">
                          {t('securityDept.noTasks', { defaultValue: '暂无任务，先在左侧创建一个吧。' })}
                        </TableCell>
                      </TableRow>
                    )}
                    {tasks.map((task) => (
                      <TableRow
                        key={task.id}
                        onClick={() => setSelectedTaskId(task.id)}
                        className={cn(
                          'cursor-pointer transition-colors hover:bg-slate-50/80',
                          selectedTaskId === task.id && 'bg-[#1f4e7a0f]'
                        )}
                      >
                        <TableCell className="font-mono text-xs text-slate-700">{task.id.slice(0, 8)}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={cn('text-xs', statusBadgeClass(task.status))}>
                            {task.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[260px] truncate text-xs text-slate-600">
                          {task.target || '-'}
                        </TableCell>
                        <TableCell className="text-xs text-slate-600">{formatTime(task.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>

            <Card className="flex flex-1 flex-col rounded-2xl border-[#d9e0e8] bg-white/95 p-4 shadow-sm">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <TerminalSquare className="h-4 w-4 text-[#1f4e7a]" />
                  <h2 className="text-sm font-semibold text-slate-900">
                    {t('securityDept.executionDetail', { defaultValue: '执行详情' })}
                  </h2>
                </div>
                <div className="flex items-center gap-2">
                  {selectedTask && !TERMINAL_STATUSES.has(selectedTask.status) && (
                    <Button variant="outline" size="sm" onClick={handleCancelSelectedTask}>
                      <Square className="mr-1 h-3.5 w-3.5" />
                      {t('securityDept.cancelTask', { defaultValue: '取消任务' })}
                    </Button>
                  )}
                  {selectedTask && (
                    <Badge variant="outline" className={cn('text-xs', statusBadgeClass(selectedTask.status))}>
                      {selectedTask.status}
                    </Badge>
                  )}
                </div>
              </div>

              {!selectedTask && (
                <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">
                  {t('securityDept.pickTask', { defaultValue: '请选择左上角任务查看详情' })}
                </div>
              )}

              {selectedTask && (
                <div className="grid flex-1 gap-4 xl:grid-cols-2">
                  <div className="flex min-h-[300px] flex-col rounded-xl border border-slate-200">
                    <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                        {t('securityDept.eventStream', { defaultValue: '实时事件流' })}
                      </p>
                      <p className="text-[11px] text-slate-500">{selectedTask.id}</p>
                    </div>
                    <div className="flex-1 overflow-auto bg-[#0f172a] p-3 text-[12px] leading-relaxed text-emerald-200">
                      {eventLog.length === 0 && (
                        <p className="text-emerald-300/70">
                          {t('securityDept.noEventsYet', { defaultValue: '暂无事件，等待任务输出...' })}
                        </p>
                      )}
                      {eventLog.map((event, index) => (
                        <p key={`${event.timestamp}-${index}`} className="mb-1 whitespace-pre-wrap break-words">
                          {formatEventLine(event)}
                        </p>
                      ))}
                    </div>
                  </div>

                  <div className="flex min-h-[300px] flex-col rounded-xl border border-slate-200 bg-white">
                    <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                        {t('securityDept.summary', { defaultValue: '执行总结' })}
                      </p>
                      <div className="flex items-center gap-2 text-[11px] text-slate-500">
                        <Clock3 className="h-3.5 w-3.5" />
                        {selectedTask.duration_ms ? `${selectedTask.duration_ms}ms` : '-'}
                      </div>
                    </div>
                    <div className="flex-1 overflow-auto p-3">
                      {selectedTask.summary_md ? (
                        <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-700">
                          {selectedTask.summary_md}
                        </pre>
                      ) : (
                        <p className="text-xs text-slate-500">
                          {t('securityDept.noSummaryYet', { defaultValue: '任务尚未生成总结。' })}
                        </p>
                      )}
                      {selectedTask.error_message && (
                        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
                          <p className="font-semibold">{selectedTask.error_code || 'Error'}</p>
                          <p className="mt-1 whitespace-pre-wrap break-words">{selectedTask.error_message}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {streamError && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  <span>{streamError}</span>
                </div>
              )}
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
