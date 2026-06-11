'use client'

import Link from 'next/link'

interface AppLogoProps {
  isCollapsed?: boolean
}

/**
 * Logo component
 */
export function AppLogo({ isCollapsed = false }: AppLogoProps) {
  return (
    <div className="flex h-[60px] min-w-0 items-center pl-2 pr-4">
      <Link href="/agents" className="flex min-w-0 flex-1 items-center gap-1.5">
        <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center">
          <div className="brand-gradient absolute inset-0 rounded-lg opacity-100" />

          <div className="brand-gradient absolute inset-0 rounded-lg opacity-20 blur-md" />

          <svg
            className="relative z-10 h-5 w-5 text-white"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            {/* Molecular/DNA connection structure */}
            {/* Connection lines */}
            <path
              d="M 8,6 L 12,12 L 16,6"
              stroke="white"
              strokeWidth="1.4"
              opacity="0.7"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M 8,18 L 12,12 L 16,18"
              stroke="white"
              strokeWidth="1.4"
              opacity="0.7"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Nodes */}
            <circle cx="12" cy="12" r="3" fill="white" opacity="0.95" />
            <circle cx="8" cy="6" r="2" fill="white" opacity="0.85" />
            <circle cx="16" cy="6" r="2" fill="white" opacity="0.85" />
            <circle cx="8" cy="18" r="2" fill="white" opacity="0.85" />
            <circle cx="16" cy="18" r="2" fill="white" opacity="0.85" />
          </svg>
        </div>

        {!isCollapsed && (
          <span className="brand-gradient-text whitespace-nowrap text-xl font-bold tracking-tight">
            JoySafeter
          </span>
        )}
      </Link>
    </div>
  )
}
