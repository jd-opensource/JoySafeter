'use client'

import React from 'react'

import { cn } from '@/lib/core/utils/cn'

import { ExampleScene } from '../../services/exampleData'

interface SceneTabsProps {
  scenes: ExampleScene[]
  activeScene: string
  onSceneChange: (sceneId: string) => void
}

const SceneTabs: React.FC<SceneTabsProps> = ({ scenes, activeScene, onSceneChange }) => {
  return (
    <div className="flex items-center justify-center gap-2 flex-wrap">
      {scenes.map((scene) => (
        <button
          key={scene.id}
          onClick={() => onSceneChange(scene.id)}
          className={cn(
            'px-4 py-2 rounded-full text-sm font-medium transition-all',
            activeScene === scene.id
              ? 'bg-gray-900 text-white'
              : 'bg-white text-gray-600 border border-gray-200 hover:border-gray-300 hover:bg-gray-50'
          )}
        >
          {scene.label}
        </button>
      ))}
    </div>
  )
}

export default SceneTabs
