'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import React, { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { ExampleScene, ExampleItem } from '../../services/exampleData'

import ExampleCard from './ExampleCard'
import SceneTabs from './SceneTabs'

interface ExampleCarouselProps {
  scenes: ExampleScene[]
  onExampleSelect: (prompt: string, mode?: string) => void
}

const ExampleCarousel: React.FC<ExampleCarouselProps> = ({ scenes, onExampleSelect }) => {
  const { t } = useTranslation()
  const [activeScene, setActiveScene] = useState(scenes[0]?.id || '')
  const [currentIndex, setCurrentIndex] = useState(0)

  const currentScene = scenes.find((s) => s.id === activeScene)

  // Transform examples to use translations
  const examples: ExampleItem[] = (currentScene?.examples || []).map((ex) => ({
    ...ex,
    title: t(`chat.${ex.title}`),
    description: t(`chat.${ex.description}`),
  }))

  const currentExample = examples[currentIndex]

  // Transform scenes to use translations
  const translatedScenes: ExampleScene[] = scenes.map((scene) => ({
    ...scene,
    label: t(`chat.${scene.label}`),
  }))

  const handlePrev = () => {
    setCurrentIndex((prev) => (prev > 0 ? prev - 1 : examples.length - 1))
  }

  const handleNext = () => {
    setCurrentIndex((prev) => (prev < examples.length - 1 ? prev + 1 : 0))
  }

  const handleSceneChange = (sceneId: string) => {
    setActiveScene(sceneId)
    setCurrentIndex(0)
  }

  const handleDotClick = (index: number) => {
    setCurrentIndex(index)
  }

  if (!currentExample) return null

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Scene Tabs */}
      <div className="mb-6">
        <SceneTabs
          scenes={translatedScenes}
          activeScene={activeScene}
          onSceneChange={handleSceneChange}
        />
      </div>

      {/* Carousel Container */}
      <div className="relative">
        {/* Navigation Header */}
        <div className="flex items-center justify-between mb-4 px-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handlePrev}
            disabled={examples.length <= 1}
            className="text-gray-600 hover:text-gray-900 hover:bg-gray-100 disabled:opacity-30"
          >
            <ChevronLeft size={20} />
          </Button>

          <span className="text-sm text-gray-500 font-medium">
            示例 {currentIndex + 1} / {examples.length}
          </span>

          <Button
            variant="ghost"
            size="sm"
            onClick={handleNext}
            disabled={examples.length <= 1}
            className="text-gray-600 hover:text-gray-900 hover:bg-gray-100 disabled:opacity-30"
          >
            <ChevronRight size={20} />
          </Button>
        </div>

        {/* Example Card */}
        <div className="px-2">
          <ExampleCard
            key={`${activeScene}-${currentIndex}`}
            example={currentExample}
            onClick={onExampleSelect}
          />
        </div>

        {/* Indicators */}
        {examples.length > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            {examples.map((_, index) => (
              <button
                key={index}
                onClick={() => handleDotClick(index)}
                className={cn(
                  'h-2 rounded-full transition-all duration-300',
                  index === currentIndex
                    ? 'bg-gray-900 w-6'
                    : 'bg-gray-300 hover:bg-gray-400 w-2'
                )}
                aria-label={`Go to example ${index + 1}`}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ExampleCarousel
