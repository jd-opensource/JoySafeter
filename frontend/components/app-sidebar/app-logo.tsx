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
    <div className="flex h-[60px] items-center pl-2 pr-4 min-w-0">
      <Link href="/chat" className="flex items-center gap-1.5 min-w-0 flex-1">
        <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center">
          <div className="absolute inset-0 rounded-lg bg-gradient-to-br from-[#6f3dfa] to-[#0ea5e9] opacity-100" />

          <div className="absolute inset-0 rounded-lg bg-gradient-to-br from-[#6f3dfa] to-[#0ea5e9] opacity-20 blur-md" />

          <svg
            className="relative z-10 h-5 w-5 text-white"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#6f3dfa" />
                <stop offset="100%" stopColor="#0ea5e9" />
              </linearGradient>
            </defs>

            {/* Central AI symbol - white circle with "A" */}
            <g transform="translate(12, 12)">
              <circle r="4.5" fill="white" opacity="0.95" />
              <path
                d="M -1.5,-3 L 0,3 L 1.5,-3 M -1,0 L 1,0"
                stroke="url(#logoGrad)"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </g>

            {/* Two accent nodes */}
            <circle cx="6" cy="6" r="2" fill="white" opacity="0.8" />
            <circle cx="18" cy="18" r="2" fill="white" opacity="0.8" />

            {/* Connection curve */}
            <path
              d="M 8,6 Q 12,12 16,18"
              stroke="white"
              strokeWidth="1.2"
              opacity="0.6"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </div>

        {!isCollapsed && (
          <span className="bg-gradient-to-r from-[#6f3dfa] to-[#0ea5e9] bg-clip-text text-[17px] font-bold tracking-tight text-transparent whitespace-nowrap">
            JoySafeter
          </span>
        )}
      </Link>
    </div>
  )
}
