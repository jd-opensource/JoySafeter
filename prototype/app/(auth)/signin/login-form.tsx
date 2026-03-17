'use client'

import { ArrowRight, Eye, EyeOff, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { client } from '@/lib/auth/auth-client'
import { cn } from '@/lib/core/utils/cn'
import { toastError } from '@/lib/utils/toast'

export default function LoginPage() {
  const { t } = useTranslation()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [email, setEmail] = useState('demo@joysafeter.com')
  const [password, setPassword] = useState('demo123')

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

  const inputClass = cn(
    'w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-[14px] text-white/90',
    'placeholder:text-white/25 outline-none',
    'transition-all duration-200',
    'focus:border-violet-500/50 focus:bg-white/[0.07] focus:ring-2 focus:ring-violet-500/15',
  )

  return (
    <div className="space-y-6">
      {/* Heading */}
      <div className="space-y-1">
        <h1 className="text-[26px] font-bold tracking-tight text-white/90">
          {t('auth.signIn')}
        </h1>
        <p className="text-[14px] text-white/40">
          {t('auth.enterYourDetails')}
        </p>
      </div>

      {/* Prototype hint */}
      <div className="flex items-center gap-2 rounded-xl border border-violet-500/25 bg-violet-500/8 px-4 py-2.5">
        <Sparkles className="h-3.5 w-3.5 text-violet-400 flex-shrink-0" />
        <p className="text-[12px] text-violet-300 font-medium">
          原型演示 · 任意邮箱 + 任意密码均可登录
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-5">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="block text-[12px] font-medium text-white/50">
              {t('auth.email')}
            </label>
            <input
              id="email"
              name="email"
              type="email"
              placeholder={t('auth.enterYourEmail')}
              required
              autoCapitalize="none"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="block text-[12px] font-medium text-white/50">
              {t('auth.password')}
            </label>
            <div className="relative">
              <input
                id="password"
                name="password"
                required
                type={showPassword ? 'text' : 'password'}
                autoCapitalize="none"
                autoComplete="current-password"
                placeholder={t('auth.enterYourPassword')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={cn(inputClass, 'pr-10')}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute top-1/2 right-3 -translate-y-1/2 text-white/30 transition hover:text-white/60"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={isLoading}
          className={cn(
            'group relative w-full overflow-hidden rounded-xl px-4 py-3 text-[14px] font-semibold text-white',
            'bg-gradient-to-r from-violet-600 to-indigo-600',
            'shadow-[0_0_16px_rgba(139,92,246,0.4)]',
            'transition-all duration-300',
            'hover:shadow-[0_0_28px_rgba(139,92,246,0.6)] hover:-translate-y-0.5',
            'active:scale-[0.98]',
            'disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:translate-y-0',
          )}
        >
          <span className="flex items-center justify-center gap-2">
            {isLoading ? (
              <span className="flex items-center gap-2">
                <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                {t('auth.signingIn')}
              </span>
            ) : (
              <>
                {t('auth.signIn')}
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/15 transition-transform duration-200 group-hover:translate-x-0.5">
                  <ArrowRight className="h-3 w-3" />
                </span>
              </>
            )}
          </span>
        </button>
      </form>
    </div>
  )
}
