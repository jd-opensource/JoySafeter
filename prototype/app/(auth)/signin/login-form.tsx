'use client'

import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { client } from '@/lib/auth/auth-client'
import { toastError } from '@/lib/utils/toast'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [email, setEmail] = useState('demo@joysafeter.com')
  const [password, setPassword] = useState('demo123')
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setIsLoading(true)
    try {
      const result = await client.signIn.email(
        { email: email.trim().toLowerCase(), password },
        { onError: (ctx) => toastError(ctx.error.message || t('auth.invalidCredentials')) }
      )
      if (!result || result.error) {
        toastError(result?.error?.message || t('auth.invalidCredentials'))
        return
      }
      window.location.href = '/'
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : t('auth.invalidCredentials'))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <>
      <div className="space-y-1 text-center">
        <h1 className={`${soehne.className} font-medium text-[32px] text-black tracking-tight`}>
          {t('auth.signIn')}
        </h1>
        <p className={`${inter.className} font-[380] text-[16px] text-muted-foreground`}>
          {t('auth.enterYourDetails')}
        </p>
      </div>

      {/* Prototype hint */}
      <div className="mt-4 rounded-lg border border-dashed border-[var(--brand-500)]/40 bg-[var(--brand-500)]/5 px-4 py-3 text-center">
        <p className="text-[12px] text-[var(--brand-500)] font-medium">
          原型演示 · 任意邮箱 + 任意密码均可登录
        </p>
      </div>

      <form onSubmit={onSubmit} className={`${inter.className} mt-8 space-y-8`}>
        <div className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="email">{t('auth.email')}</Label>
            <Input
              id="email"
              name="email"
              placeholder={t('auth.enterYourEmail')}
              required
              autoCapitalize="none"
              autoComplete="email"
              autoCorrect="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-[10px] shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">{t('auth.password')}</Label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                required
                type={showPassword ? 'text' : 'password'}
                autoCapitalize="none"
                autoComplete="current-password"
                autoCorrect="off"
                placeholder={t('auth.enterYourPassword')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-[10px] pr-10 shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="-translate-y-1/2 absolute top-1/2 right-3 text-gray-500 transition hover:text-gray-700"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>
        </div>

        <Button
          type="submit"
          onMouseEnter={() => setIsButtonHovered(true)}
          onMouseLeave={() => setIsButtonHovered(false)}
          className="group inline-flex w-full items-center justify-center gap-2 rounded-[10px] border border-[#6F3DFA] bg-gradient-to-b from-[#8357FF] to-[#6F3DFA] py-[6px] pr-[10px] pl-[12px] text-[15px] text-white shadow-[inset_0_2px_4px_0_#9B77FF] transition-all"
          disabled={isLoading}
        >
          <span className="flex items-center gap-1">
            {isLoading ? t('auth.signingIn') : t('auth.signIn')}
            <span className="inline-flex transition-transform duration-200 group-hover:translate-x-0.5">
              {isButtonHovered ? (
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              ) : (
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              )}
            </span>
          </span>
        </Button>
      </form>
    </>
  )
}
