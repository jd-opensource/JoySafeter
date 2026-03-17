'use client'

import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard,
  MessageSquare,
  Blocks,
  Database,
  BarChart3,
  ShieldCheck,
  Terminal,
  Settings,
  LogOut,
  Check,
  Languages,
  Bell,
  ChevronDown,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { SettingsDialog } from '@/components/settings'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from '@/components/ui/dropdown-menu'
import { useSession, client } from '@/lib/auth/auth-client'
import { cn } from '@/lib/core/utils/cn'

export interface NavItem {
  id: string
  labelKey: string
  icon: React.ComponentType<{ className?: string }>
  href: string
  matchPaths?: string[]
}

export const navItems: NavItem[] = [
  {
    id: 'home',
    labelKey: 'sidebar.home',
    icon: LayoutDashboard,
    href: '/',
    matchPaths: ['/'],
  },
  {
    id: 'copilot',
    labelKey: 'sidebar.copilot',
    icon: MessageSquare,
    href: '/copilot',
    matchPaths: ['/copilot', '/chat'],
  },
  {
    id: 'build',
    labelKey: 'sidebar.build',
    icon: Blocks,
    href: '/build',
    matchPaths: ['/build', '/workspace'],
  },
  {
    id: 'knowledge',
    labelKey: 'sidebar.knowledge',
    icon: Database,
    href: '/knowledge',
    matchPaths: ['/knowledge', '/memory'],
  },
  {
    id: 'evaluate',
    labelKey: 'sidebar.evaluate',
    icon: BarChart3,
    href: '/evaluate',
    matchPaths: ['/evaluate'],
  },
  {
    id: 'skills',
    labelKey: 'sidebar.skillsAndTools',
    icon: ShieldCheck,
    href: '/skills',
    matchPaths: ['/skills', '/tools'],
  },
  {
    id: 'openclaw',
    labelKey: 'sidebar.openclaw',
    icon: Terminal,
    href: '/openclaw',
    matchPaths: ['/openclaw'],
  },
]

function getInitials(name?: string | null, email?: string): string {
  if (name) {
    const parts = name.split(' ')
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    return name.slice(0, 2).toUpperCase()
  }
  if (email) return email.slice(0, 2).toUpperCase()
  return 'U'
}

const languages = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
]

function NavLogo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 group flex-shrink-0">
      {/* Double-bezel logo icon */}
      <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-white/5 ring-1 ring-white/10 p-0.5">
        <div className="flex h-full w-full items-center justify-center rounded-[10px] bg-gradient-to-br from-violet-500 to-indigo-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]">
          <svg
            className="h-4 w-4 text-white"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle cx="12" cy="12" r="4" fill="white" opacity="0.95" />
            <path
              d="M12 4 L12 8 M12 16 L12 20 M4 12 L8 12 M16 12 L20 12"
              stroke="white"
              strokeWidth="1.5"
              strokeLinecap="round"
              opacity="0.7"
            />
            <circle cx="6" cy="6" r="1.5" fill="white" opacity="0.5" />
            <circle cx="18" cy="18" r="1.5" fill="white" opacity="0.5" />
            <path
              d="M7.5 7.5 Q12 12 16.5 16.5"
              stroke="white"
              strokeWidth="1"
              opacity="0.4"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </div>
        {/* Glow */}
        <div className="absolute inset-0 rounded-xl bg-violet-500/20 blur-md -z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      </div>

      <span className="text-[15px] font-semibold tracking-tight brand-text">
        JoySafeter
      </span>
    </Link>
  )
}

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname()
  const { t } = useTranslation()
  const Icon = item.icon

  const isActive = item.id === 'home'
    ? pathname === '/'
    : item.matchPaths?.some((p) => pathname.startsWith(p)) ?? pathname.startsWith(item.href)

  return (
    <Link
      href={item.href}
      className={cn(
        'relative flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium rounded-lg',
        'transition-all duration-200 ease-[cubic-bezier(0.32,0.72,0,1)]',
        isActive
          ? 'text-violet-300 bg-violet-500/10'
          : 'text-white/50 hover:text-white/80 hover:bg-white/5'
      )}
    >
      <Icon className="h-3.5 w-3.5 flex-shrink-0" />
      <span>{t(item.labelKey)}</span>

      {/* Active indicator line */}
      <AnimatePresence>
        {isActive && (
          <motion.span
            layoutId="nav-active-line"
            className="absolute bottom-0 left-3 right-3 h-[2px] rounded-full bg-gradient-to-r from-violet-500 to-indigo-500"
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            exit={{ opacity: 0, scaleX: 0 }}
            transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
          />
        )}
      </AnimatePresence>
    </Link>
  )
}

function UserMenu() {
  const router = useRouter()
  const session = useSession()
  const { t, i18n } = useTranslation()
  const [settingsOpen, setSettingsOpen] = useState(false)

  const user = session.data?.user

  const handleLogout = async () => {
    try {
      await client.signOut()
      await new Promise((resolve) => setTimeout(resolve, 100))
      window.location.href = '/signin'
    } catch {
      window.location.href = '/signin'
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex items-center gap-2 rounded-xl px-2 py-1.5 transition-all duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] hover:bg-white/5 group"
          >
            <div className="relative">
              <Avatar className="h-7 w-7 ring-1 ring-violet-500/40 ring-offset-0">
                {user?.image && <AvatarImage src={user.image} alt={user.name || 'User'} />}
                <AvatarFallback className="bg-gradient-to-br from-violet-500 to-indigo-600 text-[10px] font-semibold text-white">
                  {getInitials(user?.name, user?.email)}
                </AvatarFallback>
              </Avatar>
              <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400 ring-1 ring-[#0a0a0f]" />
            </div>
            <ChevronDown className="h-3 w-3 text-white/40 group-hover:text-white/70 transition-colors" />
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent
          align="end"
          sideOffset={8}
          className="w-52 z-[10000200] border-violet-500/20 bg-[#0d0d14] backdrop-blur-xl"
        >
          <div className="px-3 py-2">
            <p className="truncate text-[13px] font-semibold text-white/90">
              {user?.name || 'User'}
            </p>
            <p className="truncate text-[11px] text-white/40">{user?.email}</p>
          </div>
          <DropdownMenuSeparator className="bg-white/8" />

          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="flex items-center gap-2 text-[13px] text-white/70">
              <Languages className="h-3.5 w-3.5" />
              <span>{t('common.language')}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="bg-[#0d0d14] border-violet-500/20">
              {languages.map((lang) => (
                <DropdownMenuItem
                  key={lang.code}
                  onClick={() => i18n.changeLanguage(lang.code)}
                  className="flex items-center justify-between gap-2 cursor-pointer text-[13px] text-white/70"
                >
                  <span>{lang.label}</span>
                  {i18n.language === lang.code && <Check className="h-3.5 w-3.5 text-violet-400" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSeparator className="bg-white/8" />
          <DropdownMenuItem
            onClick={() => setSettingsOpen(true)}
            className="flex items-center gap-2 text-[13px] text-white/70"
          >
            <Settings className="h-3.5 w-3.5" />
            <span>{t('user.settings')}</span>
          </DropdownMenuItem>

          <DropdownMenuSeparator className="bg-white/8" />
          <DropdownMenuItem
            onClick={handleLogout}
            className="flex items-center gap-2 text-[13px] text-rose-400 focus:text-rose-300"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>{t('user.logout')}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  )
}

export function TopNav() {
  return (
    <header
      className="sticky top-0 z-40 w-full"
      style={{ height: 'var(--topnav-height)' }}
    >
      {/* Glass background — fixed element, safe for backdrop-filter */}
      <div className="absolute inset-0 bg-[rgba(10,10,15,0.75)] backdrop-blur-xl border-b border-violet-500/15" />

      <div className="relative flex h-full items-center justify-between px-5">
        {/* Left: Logo */}
        <NavLogo />

        {/* Center: Nav links */}
        <nav className="absolute left-1/2 -translate-x-1/2 flex items-center gap-0.5">
          {navItems.map((item) => (
            <NavLink key={item.id} item={item} />
          ))}
        </nav>

        {/* Right: Settings + User */}
        <div className="flex items-center gap-1">
          <Link
            href="/settings"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-white/40 transition-all duration-200 hover:text-white/70 hover:bg-white/5"
          >
            <Settings className="h-4 w-4" />
          </Link>

          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-white/40 transition-all duration-200 hover:text-white/70 hover:bg-white/5"
          >
            <Bell className="h-4 w-4" />
          </button>

          <div className="mx-1 h-5 w-px bg-white/10" />

          <UserMenu />
        </div>
      </div>
    </header>
  )
}
