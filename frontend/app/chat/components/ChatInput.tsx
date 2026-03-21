'use client'

import { ArrowRight, Square, Paperclip, X, Loader2 } from 'lucide-react'
import React, { useRef, useEffect, useState, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import { ALLOWED_EXTENSIONS_STRING } from '@/lib/constants/upload-limits'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

import { useFileUpload } from '../hooks/useFileUpload'
import type { UploadedFile } from '../services/modeHandlers/types'

interface ChatInputProps {
  input: string
  setInput: (value: string) => void
  onSubmit: (text: string, mode?: string, graphId?: string | null, files?: UploadedFile[]) => void
  isProcessing: boolean
  onStop?: () => void
  currentMode?: string
  currentGraphId?: string | null
}

export default function ChatInput({
  input,
  setInput,
  onSubmit,
  isProcessing,
  onStop,
  currentMode,
  currentGraphId,
}: ChatInputProps) {
  const { t } = useTranslation()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  const handleApkAutoSubmit = useCallback(
    (uploadedFile: UploadedFile, rawFile: File) => {
      if (currentMode === 'apk-vulnerability' && rawFile.name.toLowerCase().endsWith('.apk')) {
        const taskText = t('chat.apkVulnerabilityTaskWithPath', {
          defaultValue: '任务APK IntentBridge漏洞挖掘  apk路径为 {{path}}',
          path: uploadedFile.path,
        })
        onSubmit(taskText, currentMode, currentGraphId || undefined, [uploadedFile])
        clearFiles()
      }
    },
    [currentMode, currentGraphId, onSubmit, t],
  )

  const { files, isUploading, fileInputRef, uploadFile, handleFileSelect, removeFile, clearFiles } =
    useFileUpload({ onFileUploaded: handleApkAutoSubmit })

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [input])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleSubmit = () => {
    if (isProcessing) return
    const text =
      input.trim() ||
      (currentMode === 'apk-vulnerability' && files.length > 0
        ? t('chat.apkVulnerabilityTaskStart', {
            defaultValue: '开启任务：APK IntentBridge 漏洞挖掘',
          })
        : '')
    if (!text && files.length === 0) return

    onSubmit(text, currentMode, null, files.length > 0 ? files : undefined)
    clearFiles()
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)

    const droppedFiles = Array.from(e.dataTransfer.files)
    droppedFiles.forEach((file) => {
      uploadFile(file)
    })
  }

  const canSubmit = input.trim() || (currentMode === 'apk-vulnerability' && files.length > 0)

  return (
    <div className="relative mx-auto w-full max-w-3xl">
      {/* File List */}
      {files.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-1.5 rounded-md bg-gray-100 px-3 py-1.5 text-sm text-gray-700"
            >
              <Paperclip size={14} className="text-gray-500" />
              <span className="max-w-[200px] truncate">{file.filename}</span>
              <button
                onClick={() => removeFile(file.id)}
                className="ml-1 rounded-full p-0.5 transition-colors hover:bg-gray-200"
                aria-label="Remove file"
                disabled={isProcessing || isUploading}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Main Input Container */}
      <div
        className={cn(
          'flex items-end gap-3 rounded-[24px] border border-gray-200 bg-white p-4 shadow-sm transition-all',
          isDragOver && 'border-blue-400 bg-blue-50',
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          multiple
          accept={ALLOWED_EXTENSIONS_STRING}
          className="hidden"
          disabled={isProcessing || isUploading}
        />
        <div className="relative flex flex-1 flex-col gap-1">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('chat.describeHelpNeeded')}
            className="max-h-[200px] min-h-[100px] flex-1 resize-none overflow-y-auto border-none bg-transparent px-0.5 pb-6 pt-4 text-base shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
            rows={1}
            disabled={isProcessing || isUploading}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing || isUploading}
          className={cn(
            'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-2xl border-[1.5px] border-gray-200 bg-transparent p-0 text-gray-500 transition-all duration-200 hover:bg-gray-50 hover:text-gray-700',
            (isUploading || isProcessing) && 'cursor-not-allowed opacity-50',
          )}
          title={t('chat.uploadFile')}
        >
          {isUploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
        </Button>
        {isProcessing && onStop ? (
          <Button
            onClick={onStop}
            size="sm"
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-red-500 p-0 transition-all hover:bg-red-600"
            title={t('chat.stop')}
          >
            <Square size={14} className="fill-white text-white" />
          </Button>
        ) : (
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit || isProcessing || isUploading}
            size="sm"
            className={cn(
              'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full p-0 transition-all',
              canSubmit && !isProcessing && !isUploading
                ? 'bg-gray-900 hover:bg-gray-800'
                : 'cursor-not-allowed bg-gray-100',
            )}
          >
            <ArrowRight
              size={18}
              className={
                canSubmit && !isProcessing && !isUploading ? 'text-white' : 'text-gray-300'
              }
            />
          </Button>
        )}
      </div>
    </div>
  )
}
