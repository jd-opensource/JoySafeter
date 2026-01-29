'use client'

import { ArrowRight, Square, Paperclip, X, Loader2 } from 'lucide-react'
import React, { useRef, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { API_BASE, apiUpload } from '@/lib/api-client'
import { isAllowedFile, ALLOWED_EXTENSIONS_STRING, UPLOAD_LIMITS } from '@/lib/constants/upload-limits'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'

interface UploadedFile {
  id: string
  filename: string
  path: string
  size: number
}

interface ChatInputProps {
  input: string
  setInput: (value: string) => void
  onSubmit: (text: string, mode?: string, graphId?: string | null, files?: Array<{ id: string; filename: string; path: string; size: number }>) => void
  isProcessing: boolean
  onStop?: () => void
  currentMode?: string
  currentGraphId?: string | null
  compactToolStatus?: React.ReactNode
}

const ChatInput: React.FC<ChatInputProps> = ({
  input,
  setInput,
  onSubmit,
  isProcessing,
  onStop,
  currentMode,
  currentGraphId,
  compactToolStatus,
}) => {
  const { t } = useTranslation()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)

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
    // Allow submit even if input is empty if there are files (for APK auto-submit)
    const text = input.trim() || (currentMode === 'apk-vulnerability' && files.length > 0 
      ? t('chat.apkVulnerabilityTaskStart', { defaultValue: '开启任务：APK IntentBridge 漏洞挖掘' })
      : '')
    if (!text && files.length === 0) return
    
    onSubmit(text, currentMode, null, files.length > 0 ? files : undefined)
    // Clear files after submit
    setFiles([])
  }

  // File upload handling
  const handleFileUpload = async (file: File) => {
    const validation = isAllowedFile(file)
    if (!validation.allowed) {
      toastError(
        validation.reason || t('chat.fileNotAllowed', { defaultValue: '文件不符合要求' }),
        t('chat.fileUploadFailed')
      )
      return
    }

    setIsUploading(true)
    try {
      // Wait for upload to complete and get response
      const fileData = await apiUpload<{ filename: string; path: string; size: number; message: string }>(
        `${API_BASE}/files/upload`,
        file
      )

      // Verify upload success: check all required fields are present
      if (!fileData || !fileData.filename || !fileData.path) {
        toastError(
          t('chat.uploadFailed', { defaultValue: '上传失败，响应格式异常' }),
          t('chat.fileUploadFailed')
        )
        setIsUploading(false)
        return
      }

      // Upload successful - create uploaded file object
      const uploadedFile: UploadedFile = {
        id: Date.now().toString(),
        filename: fileData.filename,
        path: fileData.path,
        size: fileData.size,
      }
      const newFiles = [...files, uploadedFile]
      setFiles(newFiles)
      toastSuccess(fileData.filename, t('chat.fileUploaded'))

      // Only after upload is completely successful, auto-submit if APK file and apk-vulnerability mode
      if (currentMode === 'apk-vulnerability' && file.name.toLowerCase().endsWith('.apk')) {
        // Ensure we have the path from the successful upload response
        const apkPath = fileData.path
        if (!apkPath) {
          toastError(
            t('chat.uploadFailed', { defaultValue: '上传成功但无法获取文件路径' }),
            t('chat.fileUploadFailed')
          )
          setIsUploading(false)
          return
        }

        // Upload is completely successful, now submit the task
        const taskText = `任务APK IntentBridge漏洞挖掘  apk路径为 ${apkPath}`
        // Use currentGraphId if available, otherwise pass undefined to let handleSubmit resolve it
        onSubmit(taskText, currentMode, currentGraphId || undefined, newFiles)
        // Clear files after submit
        setFiles([])
      }
    } catch (error) {
      // Upload failed - do not submit task
      const errorMessage =
        error instanceof Error
          ? error.message
          : typeof error === 'string'
          ? error
          : t('chat.retry', { defaultValue: '请重试' })
      toastError(errorMessage, t('chat.fileUploadFailed'))
    } finally {
      setIsUploading(false)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (selectedFiles && selectedFiles.length > 0) {
      if (selectedFiles.length > UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD) {
        toastError(
          t('chat.tooManyFiles', {
            defaultValue: '最多只能同时上传 {{maxFiles}} 个文件',
            maxFiles: UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD,
          }),
          t('chat.fileUploadFailed')
        )
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
        return
      }
      Array.from(selectedFiles).forEach((file) => {
        handleFileUpload(file)
      })
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleRemoveFile = (fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== fileId))
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
      handleFileUpload(file)
    })
  }

  const canSubmit = input.trim() || (currentMode === 'apk-vulnerability' && files.length > 0)

  return (
    <div className="relative w-full max-w-3xl mx-auto">
      {/* Compact Tool Status - Above Input, Full Width */}
      {compactToolStatus && (
        <div className="mb-3">
          {compactToolStatus}
        </div>
      )}

      {/* File List */}
      {files.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 rounded-md text-sm text-gray-700"
            >
              <Paperclip size={14} className="text-gray-500" />
              <span className="max-w-[200px] truncate">{file.filename}</span>
              <button
                onClick={() => handleRemoveFile(file.id)}
                className="ml-1 hover:bg-gray-200 rounded-full p-0.5 transition-colors"
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
          'bg-white border border-gray-200 rounded-[24px] shadow-sm transition-all flex items-end gap-3 p-4',
          isDragOver && 'border-blue-400 bg-blue-50'
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
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing || isUploading}
          className={cn(
            'h-10 w-10 p-0 bg-transparent border-[1.5px] border-gray-200 rounded-2xl text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-all duration-200 flex items-center justify-center flex-shrink-0',
            (isUploading || isProcessing) && 'opacity-50 cursor-not-allowed'
          )}
          title={t('chat.uploadFile')}
        >
          {isUploading ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Paperclip size={18} />
          )}
        </Button>
        <div className="flex-1 flex flex-col gap-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('chat.describeHelpNeeded')}
            className="flex-1 bg-transparent border-none shadow-none focus-visible:ring-0 focus:outline-none px-0.5 pb-6 pt-4 min-h-[100px] max-h-[200px] overflow-y-auto resize-none text-base placeholder:text-gray-400"
            rows={1}
            disabled={isProcessing || isUploading}
          />
        </div>
        {isProcessing && onStop ? (
          <Button
            onClick={onStop}
            size="sm"
            className="w-10 h-10 rounded-full transition-all flex-shrink-0 flex items-center justify-center p-0 bg-red-500 hover:bg-red-600"
            title={t('chat.stop')}
          >
            <Square size={14} className="text-white fill-white" />
          </Button>
        ) : (
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit || isProcessing || isUploading}
            size="sm"
            className={cn(
              'w-10 h-10 rounded-full transition-all flex-shrink-0 flex items-center justify-center p-0',
              canSubmit && !isProcessing && !isUploading
                ? 'bg-gray-900 hover:bg-gray-800'
                : 'bg-gray-100 cursor-not-allowed'
            )}
          >
            <ArrowRight
              size={18}
              className={canSubmit && !isProcessing && !isUploading ? 'text-white' : 'text-gray-300'}
            />
          </Button>
        )}
      </div>
    </div>
  )
}

export default ChatInput

