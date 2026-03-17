'use client'

import { X, Copy, Check, FileJson, Code, Loader2 } from 'lucide-react'
import React, { useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/core/utils/cn'

import { schemaService, type GraphSchema } from '../services/schemaService'

interface SchemaExportPanelProps {
    graphId: string
    open: boolean
    onClose: () => void
}

export const SchemaExportPanel: React.FC<SchemaExportPanelProps> = ({
    graphId,
    open,
    onClose,
}) => {
    const [activeTab, setActiveTab] = useState<'json' | 'code'>('json')
    const [schema, setSchema] = useState<GraphSchema | null>(null)
    const [code, setCode] = useState<string>('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [copied, setCopied] = useState(false)

    useEffect(() => {
        if (!open || !graphId) return

        const fetchData = async () => {
            setLoading(true)
            setError(null)
            try {
                const [schemaResult, codeResult] = await Promise.all([
                    schemaService.getSchema(graphId),
                    schemaService.getSchemaCode(graphId),
                ])
                setSchema(schemaResult)
                setCode(typeof codeResult === 'string' ? codeResult : JSON.stringify(codeResult))
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load schema')
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [open, graphId])

    const handleCopy = async () => {
        const content = activeTab === 'json'
            ? JSON.stringify(schema, null, 2)
            : code
        await navigator.clipboard.writeText(content)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    const tabs = [
        { id: 'json' as const, label: 'JSON Schema', icon: FileJson },
        { id: 'code' as const, label: 'Python Code', icon: Code },
    ]

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent hideCloseButton className="sm:max-w-[600px] max-h-[85vh] p-0 bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
                <DialogHeader className="px-4 py-3.5 border-b border-gray-100 shrink-0 flex flex-row items-center justify-between">
                    <div className="flex items-center gap-3 text-gray-900 overflow-hidden">
                        <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-indigo-50 text-indigo-600">
                            <FileJson size={14} />
                        </div>
                        <div className="flex flex-col min-w-0">
                            <DialogTitle className="font-bold text-sm leading-tight truncate">Schema Export</DialogTitle>
                            <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
                                Graph Definition
                            </span>
                        </div>
                    </div>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={onClose}
                        className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100 shrink-0"
                    >
                        <X size={16} />
                    </Button>
                </DialogHeader>

                {/* Tab Bar */}
                <div className="flex border-b border-gray-100 px-4 gap-1">
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={cn(
                                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors -mb-px',
                                activeTab === tab.id
                                    ? 'border-indigo-500 text-indigo-700'
                                    : 'border-transparent text-gray-400 hover:text-gray-600'
                            )}
                        >
                            <tab.icon size={12} />
                            {tab.label}
                        </button>
                    ))}
                    <div className="flex-1" />
                    <button
                        onClick={handleCopy}
                        disabled={loading || !!error}
                        className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-gray-400 hover:text-gray-600 transition-colors disabled:opacity-50"
                    >
                        {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                        {copied ? 'Copied' : 'Copy'}
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
                    {loading && (
                        <div className="flex items-center justify-center py-12 text-gray-400">
                            <Loader2 size={20} className="animate-spin mr-2" />
                            <span className="text-sm">Loading schema...</span>
                        </div>
                    )}
                    {error && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                            {error}
                        </div>
                    )}
                    {!loading && !error && (
                        <pre className="text-[11px] font-mono text-gray-700 bg-gray-50 rounded-lg p-3 border border-gray-100 overflow-x-auto whitespace-pre-wrap break-words leading-relaxed">
                            {activeTab === 'json'
                                ? JSON.stringify(schema, null, 2)
                                : code}
                        </pre>
                    )}
                </div>

                {/* Footer */}
                <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center justify-between text-[9px] text-gray-400 font-mono">
                    <span>{activeTab === 'json' ? 'JSON' : 'Python'}</span>
                    <span className="flex items-center gap-1">
                        {schema && (
                            <>
                                {schema.nodes?.length || 0} nodes · {schema.edges?.length || 0} edges
                            </>
                        )}
                    </span>
                </div>
            </DialogContent>
        </Dialog>
    )
}
