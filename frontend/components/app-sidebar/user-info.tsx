'use client'

import { Settings, LogOut, ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { SettingsDialog } from '@/components/settings'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useSession, client } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

interface UserInfoProps {
  isCollapsed?: boolean
  showContent?: boolean
}

/**
 * Get user initials
 */
function getInitials(name?: string | null, email?: string): string {
  if (name) {
    const parts = name.split(' ')
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    }
    return name.slice(0, 2).toUpperCase()
  }
  if (email) {
    return email.slice(0, 2).toUpperCase()
  }
  return 'U'
}

/**
 * User info component
 */
export function UserInfo({ isCollapsed: _isCollapsed = false, showContent = true }: UserInfoProps) {
  const session = useSession()
  const { t } = useTranslation()
  const [settingsOpen, setSettingsOpen] = useState(false)

  const user = session.data?.user

  const handleLogout = async () => {
    try {
      // Call logout API
      await client.signOut()
      // Wait a short time to ensure cookies are deleted
      await new Promise((resolve) => setTimeout(resolve, 100))
      // Redirect to login page
      window.location.href = '/signin'
    } catch (error) {
      console.error('Logout failed:', error)
      // Even on error, redirect to login page (cookies may have been deleted)
      window.location.href = '/signin'
    }
  }

  const handleSettingsClick = () => {
    setSettingsOpen(true)
  }

  return (
    <>
      <div className="relative border-t border-[var(--border)] p-2">
        <div className="flex flex-col gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  'flex w-full items-center rounded-lg px-2 py-2 transition-colors hover:bg-[var(--surface-3)]',
                  showContent ? 'gap-2' : 'justify-center',
                )}
                aria-label={t('user.userMenu', { defaultValue: 'User menu' })}
              >
                <Avatar className="h-8 w-8 flex-shrink-0">
                  {user?.image && (
                    <AvatarImage src={user.image} alt={user.name || t('user.user')} />
                  )}
                  <AvatarFallback className="border border-[var(--brand-400)] bg-[var(--brand-500)] text-2xs text-white">
                    {getInitials(user?.name, user?.email)}
                  </AvatarFallback>
                </Avatar>
                {showContent && (
                  <>
                    <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden">
                      <span className="truncate text-xs-plus font-medium text-[var(--text-primary)]">
                        {user?.name || user?.email || t('user.user')}
                      </span>
                    </div>
                    <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
                  </>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={8}
              className="z-[10000200] w-[180px] border-[var(--border)]"
            >
              <div className="px-2 py-1.5">
                <p className="truncate text-small font-medium">{user?.name || t('user.user')}</p>
                <p className="truncate text-app-xs text-[var(--text-muted)]">{user?.email}</p>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleSettingsClick}
                className="flex items-center gap-2 text-small"
              >
                <Settings className="h-3.5 w-3.5" />
                <span>{t('user.settings')}</span>
              </DropdownMenuItem>

              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="flex items-center gap-2 text-small text-[var(--status-error)] focus:text-[var(--status-error)]"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span>{t('user.logout')}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  )
}
