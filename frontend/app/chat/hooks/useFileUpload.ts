'use client'

import { useState, useRef, useCallback } from 'react'

import { API_BASE, apiUpload } from '@/lib/api-client'
import { isAllowedFile, UPLOAD_LIMITS } from '@/lib/constants/upload-limits'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'

import type { UploadedFile } from '../services/modeHandlers/types'

interface UseFileUploadOptions {
  onFileUploaded?: (file: UploadedFile, rawFile: File) => void
}

export function useFileUpload(options: UseFileUploadOptions = {}) {
  const { t } = useTranslation()
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const uploadFile = useCallback(
    async (file: File) => {
      const validation = isAllowedFile(file)
      if (!validation.allowed) {
        toastError(
          validation.reason || t('chat.fileNotAllowed', { defaultValue: 'File does not meet requirements' }),
          t('chat.fileUploadFailed'),
        )
        return
      }

      setIsUploading(true)
      try {
        const fileData = await apiUpload<{
          filename: string
          path: string
          size: number
          message: string
        }>(`${API_BASE}/files/upload`, file)

        if (!fileData || !fileData.filename || !fileData.path) {
          toastError(
            t('chat.uploadFailed', { defaultValue: 'Upload failed, unexpected response format' }),
            t('chat.fileUploadFailed'),
          )
          return
        }

        const uploadedFile: UploadedFile = {
          id: Date.now().toString(),
          filename: fileData.filename,
          path: fileData.path,
          size: fileData.size,
        }
        setFiles((prev) => [...prev, uploadedFile])
        toastSuccess(fileData.filename, t('chat.fileUploaded'))
        options.onFileUploaded?.(uploadedFile, file)
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : typeof error === 'string'
              ? error
              : t('chat.retry', { defaultValue: 'Please retry' })
        toastError(errorMessage, t('chat.fileUploadFailed'))
      } finally {
        setIsUploading(false)
      }
    },
    [t, options],
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = e.target.files
      if (selectedFiles && selectedFiles.length > 0) {
        if (selectedFiles.length > UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD) {
          toastError(
            t('chat.tooManyFiles', {
              defaultValue: 'You can upload at most {{maxFiles}} files at once',
              maxFiles: UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD,
            }),
            t('chat.fileUploadFailed'),
          )
          if (fileInputRef.current) {
            fileInputRef.current.value = ''
          }
          return
        }
        Array.from(selectedFiles).forEach((file) => {
          uploadFile(file)
        })
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    },
    [t, uploadFile],
  )

  const removeFile = useCallback((fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== fileId))
  }, [])

  const clearFiles = useCallback(() => {
    setFiles([])
  }, [])

  const addFile = useCallback((file: UploadedFile) => {
    setFiles((prev) => [...prev, file])
  }, [])

  return {
    files,
    isUploading,
    fileInputRef,
    uploadFile,
    handleFileSelect,
    removeFile,
    clearFiles,
    addFile,
  }
}
