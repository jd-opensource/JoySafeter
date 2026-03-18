'use client'

import { ArrowRight, Eye, EyeOff, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { client } from '@/lib/auth/auth-client'
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

  return (
    <div className="space-y-7">
      <div className="space-y-3">
        <div className="section-label">Secure access</div>
        <h1 className="font-display text-[2.1rem] leading-none text-[var(--text-primary)]">
          {t('auth.signIn')}
        </h1>
        <p className="text-[14px] leading-6 text-[var(--text-secondary)]">
          {t('auth.enterYourDetails')}
        </p>
      </div>

      <div className="surface-panel-flat flex items-start gap-3 px-4 py-3">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--brand-500)]">
          <Sparkles className="h-3.5 w-3.5" />
        </div>
        <p className="text-[12px] leading-5 text-[var(--text-secondary)]">
          Prototype access is enabled for review. Any email and password pair can enter the current demo environment.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-5">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">
              {t('auth.email')}
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder={t('auth.enterYourEmail')}
              required
              autoCapitalize="none"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">
              {t('auth.password')}
            </label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                required
                type={showPassword ? 'text' : 'password'}
                autoCapitalize="none"
                autoComplete="current-password"
                placeholder={t('auth.enterYourPassword')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute top-1/2 right-3 -translate-y-1/2 text-[var(--text-muted)] transition hover:text-[var(--text-primary)]"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        </div>

        <Button
          type="submit"
          disabled={isLoading}
          className="group relative h-12 w-full overflow-hidden text-[14px] font-semibold"
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
        </Button>
      </form>
    </div>
  )
}
