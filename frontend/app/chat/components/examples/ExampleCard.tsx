'use client'

import React from 'react'

import { cn } from '@/lib/core/utils/cn'

import { ExampleItem } from '../../services/exampleData'

interface ExampleCardProps {
  example: ExampleItem
  onClick: (prompt: string, mode?: string) => void
}

const ExampleCard: React.FC<ExampleCardProps> = ({ example, onClick }) => {
  return (
    <button
      onClick={() => onClick(example.prompt, example.mode)}
      className="group bg-white border border-gray-200 rounded-2xl p-6 text-left transition-all hover:border-gray-300 hover:shadow-md w-full"
    >
      <div className="flex flex-col gap-3">
        {/* Icon and Title */}
        <div className="flex items-center gap-3">
          <span className="text-2xl">{example.icon}</span>
          <h3 className="text-base font-semibold text-gray-900">{example.title}</h3>
        </div>

        {/* Description */}
        <p className="text-sm text-gray-600 leading-relaxed line-clamp-3">
          {example.description}
        </p>

        {/* Action Button */}
        <div className="flex items-center justify-center mt-2">
          <span className={cn(
            'inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all',
            'bg-gray-50 text-gray-700 group-hover:bg-gray-900 group-hover:text-white'
          )}>
            点击使用示例 →
          </span>
        </div>
      </div>
    </button>
  )
}

export default ExampleCard
