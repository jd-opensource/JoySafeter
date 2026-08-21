'use client'

import {
  Zap,
  Bot,
  Building2,
  Brain,
  MessageSquare,
  Server,
  KeyRound,
  Sun,
  Moon,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  FileText,
  Database,
  Network,
  FolderCode,
  Sparkles,
  Shield,
  LogOut,
  Check,
  Globe,
  ChevronsUpDown,
  Search,
  Users,
  BarChart3,
  Activity,
  History,
  CalendarClock,
  Webhook,
  ArrowRight,
  Loader2,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useRef, useState, useSyncExternalStore } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu'
import { toast } from '@/hooks/use-toast'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { managedGet } from '@/lib/api-client'
import { useSession, client } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { roleLabel } from '@/lib/managed/roles'
import { cn } from '@/lib/utils'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'
import { useSidebarStore } from '@/stores/sidebar/store'

interface NavItem {
  to: string
  labelKey: string
  icon: typeof Zap
}

const COMPACT_VIEWPORT_QUERY = '(max-width: 639px)'

function subscribeToCompactViewport(onChange: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined
  const mediaQuery = window.matchMedia(COMPACT_VIEWPORT_QUERY)
  mediaQuery.addEventListener('change', onChange)
  return () => mediaQuery.removeEventListener('change', onChange)
}

function compactViewportSnapshot() {
  return (
    typeof window !== 'undefined' && Boolean(window.matchMedia?.(COMPACT_VIEWPORT_QUERY).matches)
  )
}

function useCompactViewport() {
  return useSyncExternalStore(subscribeToCompactViewport, compactViewportSnapshot, () => false)
}

const buildItems: NavItem[] = [
  { to: '/managed/quickstart', labelKey: 'nav.quickstart', icon: Zap },
  { to: '/managed/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/managed/sessions', labelKey: 'nav.sessions', icon: MessageSquare },
  { to: '/managed/environments', labelKey: 'nav.environments', icon: Server },
]

const automationItems: NavItem[] = [
  { to: '/managed/triggers', labelKey: 'nav.triggers', icon: Webhook },
]

const insightItems: NavItem[] = [
  { to: '/managed/analytics', labelKey: 'nav.analyticsOverview', icon: Activity },
  { to: '/managed/analytics/calls', labelKey: 'nav.analyticsCalls', icon: History },
]

const resourceItems: NavItem[] = [
  { to: '/managed/files', labelKey: 'nav.files', icon: FileText },
  { to: '/managed/storage-volumes', labelKey: 'nav.storageGrants', icon: Database },
  { to: '/managed/skills', labelKey: 'nav.resourceSkills', icon: Sparkles },
  { to: '/managed/credentials', labelKey: 'nav.credentials', icon: KeyRound },
  { to: '/managed/memory-stores', labelKey: 'nav.memory', icon: Brain },
]

const platformManageItems: NavItem[] = [
  { to: '/managed/platform/users', labelKey: 'nav.platformUsers', icon: Users },
  { to: '/managed/platform/storage', labelKey: 'nav.platformStorageVolumes', icon: Database },
  {
    to: '/managed/platform/network-policies',
    labelKey: 'nav.networkPolicyDiagnostics',
    icon: Network,
  },
]

const manageItems: NavItem[] = [
  { to: '/managed/settings', labelKey: 'nav.organization', icon: Building2 },
  { to: '/managed/projects', labelKey: 'nav.projects', icon: FolderCode },
]

const ORGANIZATION_COLORS = [
  'bg-purple-500',
  'bg-blue-500',
  'bg-green-500',
  'bg-orange-500',
  'bg-pink-500',
]

function organizationColor(organizationId?: string) {
  if (!organizationId) return 'bg-primary'
  const hash = Array.from(organizationId).reduce(
    (value, character) => (value * 31 + character.charCodeAt(0)) >>> 0,
    0,
  )
  return ORGANIZATION_COLORS[hash % ORGANIZATION_COLORS.length]
}

function ProjectSwitcher({ collapsed }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { projects, organizations, switchProject, orgId } = useProjectContext()
  const { currentProjectId, currentOrgId, currentProject: storedCurrentProject } = useProjectStore()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [allOrgProjects, setAllOrgProjects] = useState<Record<string, ProjectInfo[]>>({})
  const [pendingSwitch, setPendingSwitch] = useState<{
    organizationId: string
    projectId: string
  } | null>(null)
  const pendingSwitchRef = useRef<{
    organizationId: string
    projectId: string
  } | null>(null)
  const loadSeqRef = useRef(0)
  const switchSeqRef = useRef(0)
  const openSeqRef = useRef(0)
  const currentProject =
    projects.find((p) => p.id === currentProjectId) ||
    (storedCurrentProject?.id === currentProjectId ? storedCurrentProject : null)
  const currentOrg = organizations.find((o) => o.id === (currentOrgId || orgId))
  const activeOrgId = currentOrgId || orgId

  const getProjectsForOrg = (targetOrgId: string) => {
    const source =
      allOrgProjects[targetOrgId] ||
      (targetOrgId === activeOrgId
        ? projects.map((project) => ({ ...project, org_id: project.org_id || targetOrgId }))
        : [])

    return source.filter((project) => !project.org_id || project.org_id === targetOrgId)
  }

  const handleSwitchToProject = async (
    targetOrgId: string,
    targetProjectId: string,
    organizationName: string,
    projectName: string,
  ) => {
    if (
      pendingSwitchRef.current ||
      (targetOrgId === activeOrgId && targetProjectId === currentProjectId)
    ) {
      return
    }

    const switchSeq = ++switchSeqRef.current
    const openSeq = openSeqRef.current
    const nextPendingSwitch = { organizationId: targetOrgId, projectId: targetProjectId }
    pendingSwitchRef.current = nextPendingSwitch
    setPendingSwitch(nextPendingSwitch)
    try {
      await switchProject(targetProjectId, targetOrgId)
      if (switchSeq !== switchSeqRef.current) return
      toast({
        variant: 'success',
        title: t('sidebar.switchSuccess', {
          organization: organizationName,
          project: projectName,
        }),
      })
      if (openSeq === openSeqRef.current) {
        openSeqRef.current += 1
        setOpen(false)
        setSearch('')
      }
    } catch (error) {
      if (switchSeq !== switchSeqRef.current) return
      toastOperationError(t, error, 'sidebar.switchFailed')
    } finally {
      if (switchSeq === switchSeqRef.current) {
        pendingSwitchRef.current = null
        setPendingSwitch(null)
      }
    }
  }

  // Load projects for all orgs when dropdown opens
  const loadAllProjects = async () => {
    const loadSeq = ++loadSeqRef.current
    const requestedActiveOrgId = activeOrgId
    const requestedProjectId = currentProjectId
    const entries = await Promise.all(
      organizations.map(async (organization) => {
        if (organization.id === activeOrgId) {
          return [
            organization.id,
            [
              ...projects,
              ...(currentProject &&
              currentProject.archived_at &&
              !projects.some((project) => project.id === currentProject.id)
                ? [currentProject]
                : []),
            ].map((project) => ({
              ...project,
              org_id: project.org_id || organization.id,
            })),
          ] as const
        }

        try {
          const data = await managedGet<ProjectInfo[] | { data: ProjectInfo[] }>(
            '/auth/projects?include_archived=false&limit=200',
            {
              skipManagedContext: true,
              headers: { 'X-Org-Id': organization.id },
            },
          )
          const rows = Array.isArray(data) ? data : data?.data || []
          return [
            organization.id,
            rows
              .filter((project) => !project.org_id || project.org_id === organization.id)
              .map((project) => ({ ...project, org_id: project.org_id || organization.id })),
          ] as const
        } catch {
          return [organization.id, []] as const
        }
      }),
    )
    const result = Object.fromEntries(entries)
    const { currentOrgId: latestOrgId, currentProjectId: latestProjectId } =
      useProjectStore.getState()
    if (
      loadSeq !== loadSeqRef.current ||
      latestOrgId !== requestedActiveOrgId ||
      latestProjectId !== requestedProjectId
    ) {
      return
    }
    setAllOrgProjects(result)
  }

  const handleOpen = (v: boolean) => {
    if (v !== open) openSeqRef.current += 1
    setOpen(v)
    if (v) loadAllProjects()
    if (!v) setSearch('')
  }

  const filterMatch = (...values: Array<string | null | undefined>) => {
    if (!search) return true
    const normalizedSearch = search.trim().toLowerCase()
    return values.some((value) => value?.toLowerCase().includes(normalizedSearch))
  }

  const visibleOrganizations = organizations
    .map((organization) => {
      const organizationMatches = filterMatch(
        organization.name,
        organization.slug,
        organization.owner_name,
        organization.owner_email,
      )
      const matchingProjects = getProjectsForOrg(organization.id).filter(
        (project) => organizationMatches || filterMatch(project.name, project.slug),
      )
      return {
        organization,
        projects: matchingProjects,
        matches: organizationMatches || matchingProjects.length > 0,
      }
    })
    .filter((entry) => entry.matches)

  const organizationGroups = [
    {
      key: 'owned',
      label: t('sidebar.ownedOrganizations'),
      entries: visibleOrganizations.filter((entry) => entry.organization.role === 'owner'),
    },
    {
      key: 'shared',
      label: t('sidebar.sharedOrganizations'),
      entries: visibleOrganizations.filter((entry) => entry.organization.role !== 'owner'),
    },
  ].filter((group) => group.entries.length > 0)

  const organizationContext = (organization: OrgInfo) => {
    if (organization.role === 'owner') return t('sidebar.ownedByYou')
    const ownerIdentity = organization.owner_name || organization.owner_email
    return ownerIdentity
      ? `${roleLabel(t, organization.role)} · ${ownerIdentity}`
      : roleLabel(t, organization.role)
  }

  const currentContextDetail = [
    currentProject?.name || t('sidebar.noProject'),
    currentOrg ? organizationContext(currentOrg) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const switcherContent = (
    <>
      <div className="border-b border-border p-2.5">
        <p className="mb-2 text-[11px] font-medium text-muted-foreground">
          {t('sidebar.switchHint')}
        </p>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('sidebar.searchOrgProject')}
            className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </div>
      </div>
      <div className="max-h-[420px] overflow-y-auto py-1">
        {organizationGroups.map((group) => (
          <div key={group.key} className="py-1">
            <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              {group.label}
            </div>
            {group.entries.map(({ organization, projects: organizationProjects }) => (
              <div key={organization.id} className="border-border/50 mx-1 mb-1 rounded-md border">
                <div className="flex items-center gap-2 px-2 py-2">
                  <div
                    className={cn(
                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white',
                      organizationColor(organization.id),
                    )}
                  >
                    {organization.name.charAt(0).toUpperCase() || 'O'}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-xs font-semibold text-foreground">
                        {organization.name}
                      </span>
                      {organization.id === activeOrgId ? (
                        <span className="shrink-0 text-[10px] font-medium text-primary">
                          {t('sidebar.currentOrganization')}
                        </span>
                      ) : null}
                    </div>
                    <div className="truncate text-[10px] text-muted-foreground">
                      {organizationContext(organization)}
                    </div>
                  </div>
                </div>
                <div className="pb-1">
                  {organizationProjects.map((project) => {
                    const isSelected =
                      project.id === currentProjectId && organization.id === activeOrgId
                    const isPending =
                      pendingSwitch?.organizationId === organization.id &&
                      pendingSwitch.projectId === project.id
                    return (
                      <button
                        key={project.id}
                        type="button"
                        disabled={isSelected || Boolean(pendingSwitch)}
                        aria-current={isSelected ? 'true' : undefined}
                        aria-busy={isPending || undefined}
                        className={cn(
                          'mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2 rounded-sm py-2 pl-8 pr-2 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                          isSelected && 'cursor-default bg-accent font-medium',
                          !isSelected && !pendingSwitch && 'cursor-pointer hover:bg-accent/50',
                          pendingSwitch &&
                            !isPending &&
                            !isSelected &&
                            'cursor-not-allowed opacity-55',
                          isPending && 'cursor-wait bg-accent/70',
                        )}
                        onClick={() =>
                          project.id &&
                          handleSwitchToProject(
                            project.org_id || organization.id,
                            project.id,
                            organization.name,
                            project.name,
                          )
                        }
                      >
                        <FolderCode className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate">{project.name}</span>
                        {project.is_default ? (
                          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                            {t('sidebar.defaultProject')}
                          </span>
                        ) : null}
                        {isPending ? (
                          <span className="flex shrink-0 items-center gap-1 font-medium text-primary">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            {t('sidebar.switching')}
                          </span>
                        ) : isSelected ? (
                          <span className="flex shrink-0 items-center gap-1 font-medium text-primary">
                            {t('sidebar.currentProject')}
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <span className="flex shrink-0 items-center gap-1 font-medium text-primary">
                            {t('sidebar.switchAction')}
                            <ArrowRight className="h-3.5 w-3.5" />
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        ))}
        {organizationGroups.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">
            {t('common.noResults')}
          </div>
        ) : null}
      </div>
      <div className="border-t border-border p-1">
        <Link
          href="/managed/settings"
          className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          onClick={() => setOpen(false)}
        >
          <Building2 className="h-3.5 w-3.5" />
          {t('sidebar.manageOrganizations')}
        </Link>
      </div>
    </>
  )

  if (collapsed) {
    return (
      <div className="px-2 py-1">
        <DropdownMenu open={open} onOpenChange={handleOpen}>
          <DropdownMenuTrigger asChild>
            <button
              className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-xs font-bold transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              title={`${t('sidebar.switchContextTooltip')}: ${currentOrg?.name || ''} / ${currentContextDetail}`}
              aria-label={`${t('sidebar.switchContextTooltip')}: ${currentOrg?.name || ''} / ${currentContextDetail}`}
            >
              <div
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-md text-[10px] font-bold text-white',
                  organizationColor(currentOrg?.id),
                )}
              >
                {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" className="w-[320px] p-0">
            {switcherContent}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    )
  }

  return (
    <div className="px-3 py-2">
      <DropdownMenu open={open} onOpenChange={handleOpen}>
        <DropdownMenuTrigger asChild>
          <button className="flex w-full items-start gap-2 rounded-md border border-border px-2.5 py-2 text-sm transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
            <div
              className={cn(
                'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white',
                organizationColor(currentOrg?.id),
              )}
            >
              {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
            </div>
            <span className="min-w-0 flex-1 text-left">
              <span className="mb-0.5 flex items-center justify-between gap-2">
                <span className="truncate text-[10px] font-medium text-muted-foreground">
                  {t('sidebar.currentContext')}
                </span>
                <span className="flex shrink-0 items-center gap-0.5 text-[10px] font-semibold text-primary">
                  {t('sidebar.switchContext')}
                  <ChevronsUpDown className="h-3 w-3" />
                </span>
              </span>
              <span className="block truncate text-xs font-medium text-foreground">
                {currentOrg?.name || t('sidebar.noOrganization')}
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">
                <span>{currentProject?.name || t('sidebar.noProject')}</span>
                {currentOrg ? (
                  <>
                    <span aria-hidden="true"> · </span>
                    <span>{organizationContext(currentOrg)}</span>
                  </>
                ) : null}
              </span>
            </span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[320px] p-0">
          {switcherContent}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function NavSection({
  labelKey,
  icon: Icon,
  items,
  defaultOpen = true,
  collapsed,
}: {
  labelKey: string
  icon: typeof Zap
  items: NavItem[]
  defaultOpen?: boolean
  collapsed?: boolean
}) {
  const { t } = useTranslation()
  const pathname = usePathname()
  const [open, setOpen] = useState(defaultOpen)

  if (collapsed) {
    return (
      <>
        {items.map((item) => {
          const exactMatch = pathname === item.to
          const prefixMatch = pathname?.startsWith(item.to + '/') ?? false
          const hasSiblingMatch = items.some(
            (other) =>
              other.to !== item.to &&
              other.to.length > item.to.length &&
              pathname?.startsWith(other.to),
          )
          const isItemActive = exactMatch || (prefixMatch && !hasSiblingMatch)
          return (
            <Link
              key={item.to}
              href={item.to}
              title={t(item.labelKey)}
              className={cn(
                'flex h-9 w-9 items-center justify-center rounded-md transition-colors',
                isItemActive
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
              )}
            >
              <item.icon className="h-4 w-4" />
            </Link>
          )
        })}
      </>
    )
  }

  return (
    <div>
      <div className="px-3 py-2">
        <button
          onClick={() => setOpen(!open)}
          className="group flex w-full items-center justify-between"
        >
          <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Icon className="h-3.5 w-3.5" />
            {t(labelKey)}
          </span>
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 text-muted-foreground transition-transform',
              !open && '-rotate-90',
            )}
          />
        </button>
      </div>
      {open && (
        <div>
          {items.map((item) => {
            // Exact match, or starts-with but no sibling has a more specific match
            const exactMatch = pathname === item.to
            const prefixMatch = pathname?.startsWith(item.to + '/') ?? false
            const hasSiblingMatch = items.some(
              (other) =>
                other.to !== item.to &&
                other.to.length > item.to.length &&
                pathname?.startsWith(other.to),
            )
            const isActive = exactMatch || (prefixMatch && !hasSiblingMatch)
            return (
              <Link
                key={item.to}
                href={item.to}
                className={cn(
                  'mx-1 flex items-center gap-2.5 rounded-md px-4 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-accent font-medium text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                )}
              >
                <item.icon className="h-4 w-4 shrink-0" />
                {t(item.labelKey)}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

function UserMenu({ collapsed }: { collapsed?: boolean }) {
  const { t, i18n } = useTranslation()
  const session = useSession()
  const { theme, setTheme } = useTheme()
  const user = session.data?.user
  const isZh = i18n.language.startsWith('zh')

  const toggleTheme = () => setTheme(theme === 'light' ? 'dark' : 'light')

  const handleLogout = async () => {
    try {
      await client.signOut()
      useProjectStore.getState().setContext('', '', [], [])
      await new Promise((resolve) => setTimeout(resolve, 100))
      window.location.href = '/signin'
    } catch {
      useProjectStore.getState().setContext('', '', [], [])
      window.location.href = '/signin'
    }
  }

  const menuContent = (
    <>
      <DropdownMenuSub>
        <DropdownMenuSubTrigger>
          <Globe className="mr-2 h-4 w-4" />
          <span className="flex-1">{t('nav.language')}</span>
          <ChevronRight className="ml-auto h-3.5 w-3.5 text-muted-foreground" />
        </DropdownMenuSubTrigger>
        <DropdownMenuSubContent>
          <DropdownMenuItem onSelect={() => i18n.changeLanguage('zh')}>
            <span className="flex-1">中文</span>
            {isZh && <Check className="ml-2 h-4 w-4" />}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => i18n.changeLanguage('en')}>
            <span className="flex-1">English</span>
            {!isZh && <Check className="ml-2 h-4 w-4" />}
          </DropdownMenuItem>
        </DropdownMenuSubContent>
      </DropdownMenuSub>
      <DropdownMenuItem onSelect={toggleTheme}>
        {theme === 'light' ? <Moon className="mr-2 h-4 w-4" /> : <Sun className="mr-2 h-4 w-4" />}
        {theme === 'light' ? t('nav.darkMode') : t('nav.lightMode')}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem className="text-red-600 focus:text-red-600" onSelect={handleLogout}>
        <LogOut className="mr-2 h-4 w-4" />
        {t('nav.logout')}
      </DropdownMenuItem>
    </>
  )

  if (collapsed) {
    return (
      <div className="border-t border-border p-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary transition-colors hover:bg-primary/20">
              {user?.name?.charAt(0)?.toUpperCase() || '?'}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="end">
            <div className="px-2 py-1.5 text-sm font-medium">{user?.name}</div>
            <div className="px-2 pb-1.5 text-xs text-muted-foreground">{user?.email}</div>
            <DropdownMenuSeparator />
            {menuContent}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    )
  }

  return (
    <div className="border-t border-border p-3">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/50">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
              {user?.name?.charAt(0)?.toUpperCase() || '?'}
            </div>
            <div className="min-w-0 flex-1 text-left">
              <div className="truncate font-medium text-foreground">{user?.name}</div>
              <div className="truncate text-xs text-muted-foreground">{user?.email}</div>
            </div>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-[200px]">
          {menuContent}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function AppSidebar() {
  const { t } = useTranslation()
  const { isCollapsed, setIsCollapsed } = useSidebarStore()
  const session = useSession()
  const isPlatformAdmin = Boolean(session.data?.user?.isSuperUser)
  const isCompactViewport = useCompactViewport()
  const toggleSidebar = () => setIsCollapsed(!isCollapsed)

  if (isCollapsed || isCompactViewport) {
    return (
      <aside className="joysafeter-sidebar fixed bottom-0 left-0 top-0 z-50 flex w-[52px] flex-col items-center border-r border-border bg-card">
        <div className="flex w-full justify-center border-b border-border p-3">
          {isCompactViewport ? (
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary">
              <Shield className="h-3.5 w-3.5 text-primary-foreground" />
            </div>
          ) : (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
              <PanelLeftOpen className="h-4 w-4" />
            </Button>
          )}
        </div>
        <ProjectSwitcher collapsed />
        <nav className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
          <NavSection labelKey="nav.build" icon={FolderCode} items={buildItems} collapsed />
          <div className="my-1 h-px w-6 bg-border" />
          <NavSection
            labelKey="nav.automation"
            icon={CalendarClock}
            items={automationItems}
            collapsed
          />
          <div className="my-1 h-px w-6 bg-border" />
          <NavSection labelKey="nav.resources" icon={FolderCode} items={resourceItems} collapsed />
          <div className="my-1 h-px w-6 bg-border" />
          <NavSection labelKey="nav.insights" icon={BarChart3} items={insightItems} collapsed />
          <div className="my-1 h-px w-6 bg-border" />
          <NavSection labelKey="nav.manage" icon={Shield} items={manageItems} collapsed />
          {isPlatformAdmin ? <div className="my-1 h-px w-6 bg-border" /> : null}
          {isPlatformAdmin ? (
            <NavSection
              labelKey="nav.platformManage"
              icon={Shield}
              items={platformManageItems}
              collapsed
            />
          ) : null}
        </nav>
        <UserMenu collapsed />
      </aside>
    )
  }

  return (
    <aside className="joysafeter-sidebar fixed bottom-0 left-0 top-0 z-50 flex w-[220px] flex-col border-r border-border bg-card">
      <div className="flex items-center justify-between border-b border-border p-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary">
            <Shield className="h-3.5 w-3.5 text-primary-foreground" />
          </div>
          <h1 className="text-[15px] font-bold text-foreground">{t('sidebar.appTitle')}</h1>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
          <PanelLeftClose className="h-4 w-4" />
        </Button>
      </div>

      <ProjectSwitcher />

      <nav className="flex-1 overflow-y-auto py-1">
        <NavSection labelKey="nav.build" icon={FolderCode} items={buildItems} />
        <NavSection labelKey="nav.automation" icon={CalendarClock} items={automationItems} />
        <NavSection labelKey="nav.resources" icon={FolderCode} items={resourceItems} />
        <NavSection labelKey="nav.insights" icon={BarChart3} items={insightItems} />
        <NavSection labelKey="nav.manage" icon={Shield} items={manageItems} />
        {isPlatformAdmin ? (
          <NavSection labelKey="nav.platformManage" icon={Shield} items={platformManageItems} />
        ) : null}
      </nav>

      <UserMenu />
    </aside>
  )
}
