'use client'

import { useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { useSidebarStore } from '@/stores/sidebar/store'
import { useSession, client } from '@/lib/auth/auth-client'
import { useTheme } from 'next-themes'
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
  FolderCode,
  LayoutDashboard,
  ListChecks,
  Lock,
  Sparkles,
  Wrench,
  Shield,
  Settings,
  LogOut,
  Check,
  Globe,
  ChevronsUpDown,
  Search,
  Users,
} from 'lucide-react'
import { useProjectStore } from '@/stores/managed/project-store'
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
  { to: '/managed/vaults', labelKey: 'nav.vaults', icon: KeyRound },
]

const resourceItems: NavItem[] = [
  { to: '/managed/files', labelKey: 'nav.files', icon: FileText },
  { to: '/managed/skills', labelKey: 'nav.resourceSkills', icon: Sparkles },
  { to: '/managed/secrets', labelKey: 'nav.secrets', icon: Lock },
  { to: '/managed/memory-stores', labelKey: 'nav.memory', icon: Brain },
]

const platformItems: NavItem[] = [
  { to: '/dashboard', labelKey: 'nav.dashboard', icon: LayoutDashboard },
  { to: '/agents', labelKey: 'nav.platformAgents', icon: Bot },
  { to: '/tasks', labelKey: 'nav.tasks', icon: ListChecks },
  { to: '/skills', labelKey: 'nav.skills', icon: Sparkles },
  { to: '/tools', labelKey: 'nav.tools', icon: Wrench },
  { to: '/settings', labelKey: 'nav.settings', icon: Settings },
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
  const { currentProjectId, currentOrgId, setCurrentOrg, setCurrentProject } = useProjectStore()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [allOrgProjects, setAllOrgProjects] = useState<Record<string, Array<{ id: string; name: string }>>>({})
  const currentProject = projects.find((p) => p.id === currentProjectId)
  const currentOrg = organizations.find((o) => o.id === (currentOrgId || orgId))

  const orgColors = ['bg-purple-500', 'bg-blue-500', 'bg-green-500', 'bg-orange-500', 'bg-pink-500']

  const handleSwitchToProject = async (targetOrgId: string, targetProjectId: string) => {
    try {
      const { managedPost } = await import('@/lib/api-client')
      const { useQueryClient } = await import('@tanstack/react-query')
      await managedPost('/auth/switch-context', { org_id: targetOrgId, project_id: targetProjectId })
      setCurrentOrg(targetOrgId)
      setCurrentProject(targetProjectId)
      setOpen(false)
      setSearch('')
      window.location.reload()
    } catch (e) {
      console.error('Failed to switch:', e)
    }
  }

  // Load projects for all orgs when dropdown opens
  const loadAllProjects = async () => {
    const { managedPost } = await import('@/lib/api-client')
    const result: Record<string, Array<{ id: string; name: string }>> = {}
    for (const org of organizations) {
      if (org.id === (currentOrgId || orgId)) {
        result[org.id] = projects
      } else {
        try {
          const data = await managedPost<{ projects: Array<{ id: string; name: string }> }>('/auth/switch-context', { org_id: org.id })
          result[org.id] = data.projects || []
        } catch {
          result[org.id] = [{ id: '', name: 'Default' }]
        }
      }
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
              className="flex items-center justify-center w-9 h-9 rounded-md border border-border text-xs font-bold hover:bg-accent/50 transition-colors"
              title={`${currentOrg?.name || ''} / ${currentProject?.name || ''}`}
            >
              <div className={`w-6 h-6 rounded-md ${orgColors[organizations.indexOf(currentOrg!) % orgColors.length] || 'bg-primary'} flex items-center justify-center text-white text-[10px] font-bold`}>
                {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" className="w-[240px] p-0">
            <div className="p-2 border-b border-border">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('sidebar.searchOrgProject')}
                  className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  autoFocus
                />
              </div>
            </div>
            <div className="max-h-[360px] overflow-y-auto py-1">
              {organizations.filter((o) => filterMatch(o.name) || (allOrgProjects[o.id] || []).some((p) => filterMatch(p.name))).map((org, idx) => {
                const orgPrjs = (allOrgProjects[org.id] || (org.id === (currentOrgId || orgId) ? projects : []))
                  .filter((p) => filterMatch(p.name) || filterMatch(org.name))
                return (
                  <div key={org.id} className={idx > 0 ? 'border-t border-border/50 mt-1 pt-1' : ''}>
                    <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                      <div className={`w-4 h-4 rounded ${orgColors[idx % orgColors.length]} flex items-center justify-center text-white text-[8px] font-bold shrink-0`}>
                        {org.name.charAt(0).toUpperCase()}
                      </div>
                      {org.name}
                      <span className="text-[10px] font-normal text-muted-foreground/60">{t('sidebar.organizationBadge')}</span>
                    </div>
                    {orgPrjs.map((project, pIdx) => {
                      const isSelected = project.id === currentProjectId && org.id === (currentOrgId || orgId)
                      const isLast = pIdx === orgPrjs.length - 1
                      return (
                        <div
                          key={project.id || pIdx}
                          className={cn(
                            'flex items-center gap-1.5 pl-6 pr-3 py-1 cursor-pointer hover:bg-accent/50 transition-colors text-xs rounded-sm mx-1',
                            isSelected && 'bg-accent font-medium'
                          )}
                          onClick={() => project.id && handleSwitchToProject(org.id, project.id)}
                        >
                          <span className="text-muted-foreground/40 text-[11px] w-3 shrink-0">{isLast ? '└' : '├'}</span>
                          <span className="flex-1 truncate">{project.name}</span>
                          {isSelected && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
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
                <button className="flex items-center gap-2 w-full rounded-md border border-border px-2.5 py-2 text-sm hover:bg-accent/50 transition-colors">
                  <div className={`w-7 h-7 rounded-md ${orgColors[organizations.indexOf(currentOrg!) % orgColors.length] || 'bg-primary'} flex items-center justify-center text-white text-[10px] font-bold shrink-0`}>
                    {currentOrg?.name?.charAt(0)?.toUpperCase() || 'O'}
                  </div>
                  <span className="flex-1 min-w-0 text-left text-[13px] font-medium text-foreground truncate">
                    <span className="text-muted-foreground">{(currentOrg?.name || '').length > 4 ? (currentOrg?.name || '').slice(0, 4) + '…' : (currentOrg?.name || '')}</span>
                    <span className="text-muted-foreground/50 mx-0.5">/</span>
                    {currentProject?.name || 'Project'}
                  </span>
                  <ChevronsUpDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
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
          <div className="p-2 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('sidebar.searchOrgProject')}
                className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                autoFocus
              />
            </div>
          </div>
          <div className="max-h-[360px] overflow-y-auto py-1">
            {organizations.filter((o) => filterMatch(o.name) || (allOrgProjects[o.id] || []).some((p) => filterMatch(p.name))).map((org, idx) => {
              const orgPrjs = (allOrgProjects[org.id] || (org.id === (currentOrgId || orgId) ? projects : []))
                .filter((p) => filterMatch(p.name) || filterMatch(org.name))
              return (
                <div key={org.id} className={idx > 0 ? 'border-t border-border/50 mt-1 pt-1' : ''}>
                  <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                    <div className={`w-4 h-4 rounded ${orgColors[idx % orgColors.length]} flex items-center justify-center text-white text-[8px] font-bold shrink-0`}>
                      {org.name.charAt(0).toUpperCase()}
                    </div>
                    {org.name}
                    <span className="text-[10px] font-normal text-muted-foreground/60">{t('sidebar.organizationBadge')}</span>
                  </div>
                  {orgPrjs.map((project, pIdx) => {
                    const isSelected = project.id === currentProjectId && org.id === (currentOrgId || orgId)
                    const isLast = pIdx === orgPrjs.length - 1
                    return (
                      <div
                        key={project.id || pIdx}
                        className={cn(
                          'flex items-center gap-1.5 pl-6 pr-3 py-1.5 cursor-pointer hover:bg-accent/50 transition-colors text-xs rounded-sm mx-1',
                          isSelected && 'bg-accent font-medium'
                        )}
                        onClick={() => project.id && handleSwitchToProject(org.id, project.id)}
                      >
                        <span className="text-muted-foreground/40 text-[11px] w-3 shrink-0">{isLast ? '└' : '├'}</span>
                        <span className="flex-1 truncate">{project.name}</span>
                        {isSelected && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
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
        {items.map((item) => (
          <Link
            key={item.to}
            href={item.to}
            title={t(item.labelKey)}
            className={cn(
              'flex items-center justify-center w-9 h-9 rounded-md transition-colors',
              pathname?.startsWith(item.to)
                ? 'bg-accent text-accent-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
            )}
          >
            <item.icon className="w-4 h-4" />
          </Link>
        ))}
      </>
    )
  }

  return (
    <div>
      <div className="px-3 py-2">
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center justify-between w-full group"
        >
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Icon className="w-3.5 h-3.5" />
            {t(labelKey)}
          </span>
          <ChevronDown
            className={cn(
              'w-3.5 h-3.5 text-muted-foreground transition-transform',
              !open && '-rotate-90',
            )}
          />
        </button>
      </div>
      {open && (
        <div>
          {items.map((item) => {
            const isActive = pathname?.startsWith(item.to)
            return (
              <Link
                key={item.to}
                href={item.to}
                className={cn(
                  'flex items-center gap-2.5 px-4 py-1.5 mx-1 rounded-md text-sm transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                )}
              >
                <item.icon className="w-4 h-4 shrink-0" />
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
          <Globe className="w-4 h-4 mr-2" />
          <span className="flex-1">{t('nav.language')}</span>
          <ChevronRight className="w-3.5 h-3.5 ml-auto text-muted-foreground" />
        </DropdownMenuSubTrigger>
        <DropdownMenuSubContent>
          <DropdownMenuItem onSelect={() => i18n.changeLanguage('zh')}>
            <span className="flex-1">中文</span>
            {isZh && <Check className="w-4 h-4 ml-2" />}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => i18n.changeLanguage('en')}>
            <span className="flex-1">English</span>
            {!isZh && <Check className="w-4 h-4 ml-2" />}
          </DropdownMenuItem>
        </DropdownMenuSubContent>
      </DropdownMenuSub>
      <DropdownMenuItem onSelect={toggleTheme}>
        {theme === 'light' ? <Moon className="w-4 h-4 mr-2" /> : <Sun className="w-4 h-4 mr-2" />}
        {theme === 'light' ? t('nav.darkMode') : t('nav.lightMode')}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        className="text-red-600 focus:text-red-600"
        onSelect={handleLogout}
      >
        <LogOut className="w-4 h-4 mr-2" />
        {t('nav.logout')}
      </DropdownMenuItem>
    </>
  )

  if (collapsed) {
    return (
      <div className="border-t border-border p-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 text-xs font-medium text-primary hover:bg-primary/20 transition-colors">
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
          <button className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 text-sm hover:bg-accent/50 transition-colors">
            <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium text-primary shrink-0">
              {user?.name?.charAt(0)?.toUpperCase() || '?'}
            </div>
            <div className="flex-1 text-left min-w-0">
              <div className="font-medium truncate text-foreground">{user?.name}</div>
              <div className="text-xs text-muted-foreground truncate">{user?.email}</div>
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
  const toggleSidebar = () => setIsCollapsed(!isCollapsed)

  if (isCollapsed) {
    return (
      <aside className="joysafeter-sidebar fixed left-0 top-0 bottom-0 w-[52px] border-r border-border bg-card flex flex-col items-center z-50">
        <div className="p-3 border-b border-border w-full flex justify-center">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
            <PanelLeftOpen className="w-4 h-4" />
          </Button>
        </div>
        <ProjectSwitcher collapsed />
        <nav className="flex-1 py-2 flex flex-col items-center gap-1 overflow-y-auto">
          <NavSection labelKey="nav.build" icon={FolderCode} items={buildItems} collapsed />
          <div className="w-6 h-px bg-border my-1" />
          <NavSection labelKey="nav.resources" icon={FolderCode} items={resourceItems} collapsed />
          <div className="w-6 h-px bg-border my-1" />
          <NavSection labelKey="nav.manage" icon={Shield} items={manageItems} collapsed />
        </nav>
        <UserMenu collapsed />
      </aside>
    )
  }

  return (
    <aside className="joysafeter-sidebar fixed left-0 top-0 bottom-0 w-[220px] border-r border-border bg-card flex flex-col z-50">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-primary flex items-center justify-center">
            <Shield className="w-3.5 h-3.5 text-primary-foreground" />
          </div>
          <h1 className="text-[15px] font-bold text-foreground">
            {t('sidebar.appTitle')}
          </h1>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}>
          <PanelLeftClose className="w-4 h-4" />
        </Button>
      </div>

      <ProjectSwitcher />

      <nav className="flex-1 py-1 overflow-y-auto">
        <NavSection labelKey="nav.build" icon={FolderCode} items={buildItems} />
        <NavSection labelKey="nav.resources" icon={FolderCode} items={resourceItems} />
        <NavSection labelKey="nav.manage" icon={Shield} items={manageItems} />
      </nav>

      <UserMenu />
    </aside>
  )
}
