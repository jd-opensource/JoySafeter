'use client'

import { Settings, LogOut, ChevronDown, Languages, Check } from 'lucide-react'
import { useRouter } from 'next/navigation'
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
 * Language options
 */
const languages = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
]

/**
 * User info component
 */
export function UserInfo({ isCollapsed = false, showContent = true }: UserInfoProps) {
  const router = useRouter()
  const session = useSession()
  const { t, i18n } = useTranslation()
  const [settingsOpen, setSettingsOpen] = useState(false)

  const user = session.data?.user

  const handleLogout = async () => {
    try {
      // Call logout API
      await client.signOut()
      // Wait a short time to ensure cookies are deleted
      await new Promise(resolve => setTimeout(resolve, 100))
      // Redirect to login page
      window.location.href = '/signin'
    } catch (error) {
      console.error('Logout failed:', error)
      // Even on error, redirect to login page (cookies may have been deleted)
      window.location.href = '/signin'
    }
  }

  const handleLanguageChange = (langCode: string) => {
    i18n.changeLanguage(langCode)
  }

  const handleSettingsClick = () => {
    setSettingsOpen(true)
  }

  return (
    <>
      <div className="border-t border-[var(--border)] p-2 relative">
        <div className="flex flex-col gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center rounded-lg px-2 py-2 transition-colors hover:bg-[var(--surface-3)]",
                  showContent ? "gap-2" : "justify-center"
                )}
              >
                <Avatar className="h-8 w-8 flex-shrink-0">
                  {user?.image && <AvatarImage src={user.image} alt={user.name || t('user.user')} />}
                  <AvatarFallback className="bg-[var(--brand-500)] text-[10px] text-white border border-[var(--brand-400)]">
                    {getInitials(user?.name, user?.email)}
                  </AvatarFallback>
                </Avatar>
                {showContent && (
                  <>
                    <div className="flex flex-1 flex-col items-start overflow-hidden min-w-0">
                      <span className="truncate text-[12px] font-medium text-[var(--text-primary)]">
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
              className="w-[180px] z-[10000200] border-[var(--border)]"
            >
              <div className="px-2 py-1.5">
                <p className="truncate text-[13px] font-medium">{user?.name || t('user.user')}</p>
                <p className="truncate text-[11px] text-muted-foreground">{user?.email}</p>
              </div>
              <DropdownMenuSeparator />

              <DropdownMenuSub>
                <DropdownMenuSubTrigger className="flex items-center gap-2 text-[13px]">
                  <Languages className="h-3.5 w-3.5" />
                  <span>{t('common.language')}</span>
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent
                  sideOffset={4}
                  alignOffset={-5}
                  className="min-w-[110px] bg-white"
                >
                  {languages.map((lang) => (
                    <DropdownMenuItem
                      key={lang.code}
                      onClick={() => handleLanguageChange(lang.code)}
                      className="flex items-center justify-between gap-2 cursor-pointer text-[13px]"
                    >
                      <span>{lang.label}</span>
                      {i18n.language === lang.code && (
                        <Check className="h-3.5 w-3.5 text-blue-600" />
                      )}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>

              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleSettingsClick}
                className="flex items-center gap-2 text-[13px]"
              >
                <Settings className="h-3.5 w-3.5" />
                <span>{t('user.settings')}</span>
              </DropdownMenuItem>

              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="flex items-center gap-2 text-[13px] text-red-600 focus:text-red-600"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span>{t('user.logout')}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
      />
    </>
  )
}
