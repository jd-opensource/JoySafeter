'use client'

import Link from 'next/link'

interface AppLogoProps {
  isCollapsed?: boolean
}

/**
 * Logo 组件
 */
export function AppLogo({ isCollapsed = false }: AppLogoProps) {
  return (
    <div className="flex h-[86px] items-center px-3 pt-3 min-w-0">
      <Link href="/chat" className="surface-panel-flat flex w-full items-center gap-3 px-3 py-3 min-w-0 bg-[rgba(255,255,255,0.84)]">
        <div className="relative flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px] border border-[rgba(36,56,77,0.16)] bg-[linear-gradient(180deg,var(--brand-400),var(--brand-600))] shadow-[0_10px_18px_rgba(36,56,77,0.14)]">
          <svg
            className="relative z-10 h-5 w-5 text-[var(--text-inverse)]"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <g transform="translate(12, 12)">
              <circle r="4.5" fill="currentColor" opacity="0.94" />
              <path
                d="M -1.5,-3 L 0,3 L 1.5,-3 M -1,0 L 1,0"
                stroke="#21374d"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </g>

            <circle cx="6" cy="6" r="2" fill="currentColor" opacity="0.76" />
            <circle cx="18" cy="18" r="2" fill="currentColor" opacity="0.76" />
            <path
              d="M 8,6 Q 12,12 16,18"
              stroke="currentColor"
              strokeWidth="1.2"
              opacity="0.6"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </div>

        {!isCollapsed && (
          <div className="min-w-0">
            <div className="text-[15px] font-semibold tracking-tight text-[var(--text-primary)] whitespace-nowrap">
              JoySafeter
            </div>
            <div className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--text-secondary)] whitespace-nowrap">
              Security Intelligence
            </div>
          </div>
        )}
      </Link>
    </div>
  )
}
