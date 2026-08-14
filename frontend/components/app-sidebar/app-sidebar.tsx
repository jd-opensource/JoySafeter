'use client'

import { useRef, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { useSidebarStore } from '@/stores/sidebar/store'
import { useSession, client } from '@/lib/auth/auth-client'
import { useTheme } from 'next-themes'
import { managedGet } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
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
} from 'lucide-react'
import { useProjectStore } from '@/stores/managed/project-store'
import type { ProjectInfo } from '@/stores/managed/project-store'
import { useProjectContext } from '@/hooks/managed/use-project-context'

interface NavItem {
  to: string
  labelKey: string
  icon: typeof Zap
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
  { to: '/managed/members', labelKey: 'nav.members', icon: Users },
  { to: '/managed/api-keys', labelKey: 'nav.apiKeys', icon: KeyRound },
]

function ProjectSwitcher({ collapsed }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { projects, organizations, switchProject, orgId } = useProjectContext()
  const { currentProjectId, currentOrgId, currentProject: storedCurrentProject } = useProjectStore()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [allOrgProjects, setAllOrgProjects] = useState<Record<string, ProjectInfo[]>>({})
  const loadSeqRef = useRef(0)
  const switchSeqRef = useRef(0)
  const currentProject =
    projects.find((p) => p.id === currentProjectId) ||
    (storedCurrentProject?.id === currentProjectId ? storedCurrentProject : null)
  const currentOrg = organizations.find((o) => o.id === (currentOrgId || orgId))
  const activeOrgId = currentOrgId || orgId

  const orgColors = ['bg-purple-500', 'bg-blue-500', 'bg-green-500', 'bg-orange-500', 'bg-pink-500']

  const getProjectsForOrg = (targetOrgId: string) => {
    const source =
      allOrgProjects[targetOrgId] ||
      (targetOrgId === activeOrgId
        ? projects.map((project) => ({ ...project, org_id: project.org_id || targetOrgId }))
        : [])

    return source.filter((project) => !project.org_id || project.org_id === targetOrgId)
  }

  const handleSwitchToProject = async (targetOrgId: string, targetProjectId: string) => {
    const switchSeq = ++switchSeqRef.current
    try {
      await switchProject(targetProjectId, targetOrgId)
      if (switchSeq !== switchSeqRef.current) return
      setOpen(false)
      setSearch('')
    } catch (e) {
      if (switchSeq !== switchSeqRef.current) return
      console.error('Failed to switch:', e)
    }
  }

  // Load projects for all orgs when dropdown opens
  const loadAllProjects = async () => {
    const loadSeq = ++loadSeqRef.current
    const requestedActiveOrgId = activeOrgId
    const requestedProjectId = currentProjectId
    const result: Record<string, ProjectInfo[]> = {}
    for (const org of organizations) {
      if (org.id === activeOrgId) {
        result[org.id] = [
          ...projects,
          ...(currentProject &&
          currentProject.archived_at &&
          !projects.some((project) => project.id === currentProject.id)
            ? [currentProject]
            : []),
        ].map((project) => ({
          ...project,
          org_id: project.org_id || org.id,
        }))
      } else {
        try {
          const data = await managedGet<ProjectInfo[] | { data: ProjectInfo[] }>(
            '/auth/projects?include_archived=false&limit=200',
            {
              skipManagedContext: true,
              headers: { 'X-Org-Id': org.id },
            },
          )
          const rows = Array.isArray(data) ? data : data?.data || []
          result[org.id] = rows
            .filter((project) => !project.org_id || project.org_id === org.id)
            .map((project) => ({ ...project, org_id: project.org_id || org.id }))
        } catch {
          result[org.id] = []
        }
      }
    }
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
    setOpen(v)
    if (v) loadAllProjects()
    if (!v) setSearch('')
  }

  const filterMatch = (name: string) => {
    if (!search) return true
    return name.toLowerCase().includes(search.toLowerCase())
  }

  if (collapsed) {
    return (
      <div className="px-2 py-1">
        <DropdownMenu open={open} onOpenChange={handleOpen}>
          <DropdownMenuTrigger asChild>
            <button
              className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-xs font-bold transition-colors hover:bg-accent/50"
              title={`${currentOrg?.name || ''} / ${currentProject?.name || ''}`}
            >
              <div
                className={`h-6 w-6 rounded-md ${orgColors[organizations.indexOf(currentOrg!) % orgColors.length] || 'bg-primary'} flex items-center justify-center text-[10px] font-bold text-white`}
              >
                {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" className="w-[240px] p-0">
            <div className="border-b border-border p-2">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('sidebar.searchOrgProject')}
                  className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  autoFocus
                />
              </div>
            </div>
            <div className="max-h-[360px] overflow-y-auto py-1">
              {organizations
                .filter(
                  (o) =>
                    filterMatch(o.name) || getProjectsForOrg(o.id).some((p) => filterMatch(p.name)),
                )
                .map((org, idx) => {
                  const orgPrjs = getProjectsForOrg(org.id).filter(
                    (p) => filterMatch(p.name) || filterMatch(org.name),
                  )
                  return (
                    <div
                      key={org.id}
                      className={idx > 0 ? 'border-border/50 mt-1 border-t pt-1' : ''}
                    >
                      <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                        <div
                          className={`h-4 w-4 rounded ${orgColors[idx % orgColors.length]} flex shrink-0 items-center justify-center text-[8px] font-bold text-white`}
                        >
                          {org.name.charAt(0).toUpperCase()}
                        </div>
                        {org.name}
                        <span className="text-[10px] font-normal text-muted-foreground/60">
                          {t('sidebar.organizationBadge')}
                        </span>
                      </div>
                      {orgPrjs.map((project, pIdx) => {
                        const isSelected =
                          project.id === currentProjectId && org.id === (currentOrgId || orgId)
                        const isLast = pIdx === orgPrjs.length - 1
                        return (
                          <div
                            key={project.id || pIdx}
                            className={cn(
                              'mx-1 flex cursor-pointer items-center gap-1.5 rounded-sm py-1 pl-6 pr-3 text-xs transition-colors hover:bg-accent/50',
                              isSelected && 'bg-accent font-medium',
                            )}
                            onClick={() =>
                              project.id &&
                              handleSwitchToProject(project.org_id || org.id, project.id)
                            }
                          >
                            <span className="w-3 shrink-0 text-[11px] text-muted-foreground/40">
                              {isLast ? '└' : '├'}
                            </span>
                            <span className="flex-1 truncate">{project.name}</span>
                            {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    )
  }

  return (
    <div className="px-3 py-2">
      <DropdownMenu open={open} onOpenChange={handleOpen}>
        <TooltipProvider delayDuration={0}>
          <Tooltip>
            <TooltipTrigger asChild>
              <DropdownMenuTrigger asChild>
                <button className="flex w-full items-center gap-2 rounded-md border border-border px-2.5 py-2 text-sm transition-colors hover:bg-accent/50">
                  <div
                    className={`h-7 w-7 rounded-md ${orgColors[organizations.indexOf(currentOrg!) % orgColors.length] || 'bg-primary'} flex shrink-0 items-center justify-center text-[10px] font-bold text-white`}
                  >
                    {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
                  </div>
                  <span className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-foreground">
                    <span className="text-muted-foreground">
                      {(currentOrg?.name || '').length > 4
                        ? (currentOrg?.name || '').slice(0, 4) + '…'
                        : currentOrg?.name || ''}
                    </span>
                    <span className="mx-0.5 text-muted-foreground/50">/</span>
                    {currentProject?.name || 'Project'}
                  </span>
                  <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </button>
              </DropdownMenuTrigger>
            </TooltipTrigger>
            {!open && (
              <TooltipContent side="bottom" className="text-xs">
                {currentOrg?.name} / {currentProject?.name}
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
        <DropdownMenuContent align="start" className="w-[240px] p-0">
          <div className="border-b border-border p-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('sidebar.searchOrgProject')}
                className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                autoFocus
              />
            </div>
          </div>
          <div className="max-h-[360px] overflow-y-auto py-1">
            {organizations
              .filter(
                (o) =>
                  filterMatch(o.name) || getProjectsForOrg(o.id).some((p) => filterMatch(p.name)),
              )
              .map((org, idx) => {
                const orgPrjs = getProjectsForOrg(org.id).filter(
                  (p) => filterMatch(p.name) || filterMatch(org.name),
                )
                return (
                  <div
                    key={org.id}
                    className={idx > 0 ? 'border-border/50 mt-1 border-t pt-1' : ''}
                  >
                    <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                      <div
                        className={`h-4 w-4 rounded ${orgColors[idx % orgColors.length]} flex shrink-0 items-center justify-center text-[8px] font-bold text-white`}
                      >
                        {org.name.charAt(0).toUpperCase()}
                      </div>
                      {org.name}
                      <span className="text-[10px] font-normal text-muted-foreground/60">
                        {t('sidebar.organizationBadge')}
                      </span>
                    </div>
                    {orgPrjs.map((project, pIdx) => {
                      const isSelected =
                        project.id === currentProjectId && org.id === (currentOrgId || orgId)
                      const isLast = pIdx === orgPrjs.length - 1
                      return (
                        <div
                          key={project.id || pIdx}
                          className={cn(
                            'mx-1 flex cursor-pointer items-center gap-1.5 rounded-sm py-1.5 pl-6 pr-3 text-xs transition-colors hover:bg-accent/50',
                            isSelected && 'bg-accent font-medium',
                          )}
                          onClick={() =>
                            project.id &&
                            handleSwitchToProject(project.org_id || org.id, project.id)
                          }
                        >
                          <span className="w-3 shrink-0 text-[11px] text-muted-foreground/40">
                            {isLast ? '└' : '├'}
                          </span>
                          <span className="flex-1 truncate">{project.name}</span>
                          {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                        </div>
                      )
                    })}
                  </div>
                )
              })}
          </div>
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
  const router = useRouter()
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
  const toggleSidebar = () => setIsCollapsed(!isCollapsed)

  if (isCollapsed) {
    return (
      <aside className="joysafeter-sidebar fixed bottom-0 left-0 top-0 z-50 flex w-[52px] flex-col items-center border-r border-border bg-card">
        <div className="flex w-full justify-center border-b border-border p-3">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
            <PanelLeftOpen className="h-4 w-4" />
          </Button>
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
