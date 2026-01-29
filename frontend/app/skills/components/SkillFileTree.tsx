'use client'

import {
    Folder,
    FolderOpen,
    ChevronRight,
    ChevronDown,
    Plus,
    Pencil,
    Trash2,
    FileText,
    FileCode,
    Terminal,
} from 'lucide-react'
import React, { useState } from 'react'

import { cn } from '@/lib/core/utils/cn'
import { getFilenameFromPath } from '@/services/skillService'
import { SkillFile, FileTreeNode } from '@/types'

interface SkillFileTreeProps {
    fileTree: { skillMdFile: SkillFile | null; tree: FileTreeNode[] }
    activeFilePath: string | null
    onSelectFile: (path: string) => void
    onDeleteFile: (file: SkillFile) => void
    onRenameFile: (file: SkillFile) => void
    onAddFile: (directory: string) => void
}

/**
 * Get file icon based on file path and type
 * Exported for use in other components
 */
export const getFileIcon = (path: string, fileType: string) => {
    const filename = getFilenameFromPath(path)
    
    if (filename === 'SKILL.md') return <FileText size={14} className="text-emerald-500" />
    if (filename.endsWith('.md')) return <FileText size={14} className="text-blue-400" />
    if (filename.endsWith('.py')) return <Terminal size={14} className="text-yellow-500" />
    if (filename.endsWith('.js') || filename.endsWith('.ts')) return <FileCode size={14} className="text-amber-500" />
    if (filename.endsWith('.json')) return <FileCode size={14} className="text-green-500" />
    if (filename.endsWith('.sh')) return <Terminal size={14} className="text-gray-500" />
    if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return <FileCode size={14} className="text-purple-400" />
    if (filename.endsWith('.html') || filename.endsWith('.css')) return <FileCode size={14} className="text-pink-500" />
    
    return <FileCode size={14} className="text-gray-400" />
}

interface FileTreeNodeComponentProps {
    node: FileTreeNode
    activeFilePath: string | null
    onSelectFile: (path: string) => void
    onDeleteFile: (file: SkillFile) => void
    onRenameFile: (file: SkillFile) => void
    onAddFile: (directory: string) => void
    depth?: number
}

const FileTreeNodeComponent: React.FC<FileTreeNodeComponentProps> = ({
    node,
    activeFilePath,
    onSelectFile,
    onDeleteFile,
    onRenameFile,
    onAddFile,
    depth = 0,
}) => {
    const [isExpanded, setIsExpanded] = useState(true)
    
    if (node.isDirectory) {
        return (
            <div className="mb-0.5">
                <div 
                    className="flex items-center justify-between px-2 py-1 rounded-lg hover:bg-gray-50 cursor-pointer group"
                    onClick={() => setIsExpanded(!isExpanded)}
                    style={{ paddingLeft: `${depth * 12 + 8}px` }}
                >
                    <div className="flex items-center gap-1.5 text-[10px] font-medium text-gray-600">
                        {isExpanded ? (
                            <ChevronDown size={12} className="text-gray-400" />
                        ) : (
                            <ChevronRight size={12} className="text-gray-400" />
                        )}
                        {isExpanded ? (
                            <FolderOpen size={12} className="text-amber-500" />
                        ) : (
                            <Folder size={12} className="text-amber-500" />
                        )}
                        <span>{node.name}/</span>
                    </div>
                    <button
                        onClick={(e) => { e.stopPropagation(); onAddFile(node.path); }}
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-emerald-600 transition-opacity"
                        title="Add file"
                    >
                        <Plus size={10} />
                    </button>
                </div>
                
                {isExpanded && node.children && node.children.length > 0 && (
                    <div>
                        {node.children.map(child => (
                            <FileTreeNodeComponent
                                key={child.path}
                                node={child}
                                activeFilePath={activeFilePath}
                                onSelectFile={onSelectFile}
                                onDeleteFile={onDeleteFile}
                                onRenameFile={onRenameFile}
                                onAddFile={onAddFile}
                                depth={depth + 1}
                            />
                        ))}
                    </div>
                )}
            </div>
        )
    }
    
    // File node
    return (
        <div
            onClick={() => onSelectFile(node.path)}
            className={cn(
                "flex items-center justify-between gap-1 px-2 py-1 rounded-lg text-xs cursor-pointer transition-colors group/file",
                activeFilePath === node.path 
                    ? "bg-emerald-50 text-emerald-700 font-medium" 
                    : "text-gray-600 hover:bg-gray-50"
            )}
            style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
            <div className="flex items-center gap-2 min-w-0 flex-1">
                {getFileIcon(node.path, node.file?.file_type || '')}
                <span className="truncate">{node.name}</span>
            </div>
            {node.file && (
                <div className="flex items-center gap-0.5 opacity-0 group-hover/file:opacity-100 transition-opacity">
                    <button
                        onClick={(e) => { e.stopPropagation(); onRenameFile(node.file!); }}
                        className="p-0.5 text-gray-400 hover:text-blue-600"
                        title="Rename"
                    >
                        <Pencil size={10} />
                    </button>
                    <button
                        onClick={(e) => { e.stopPropagation(); onDeleteFile(node.file!); }}
                        className="p-0.5 text-gray-400 hover:text-red-600"
                        title="Delete"
                    >
                        <Trash2 size={10} />
                    </button>
                </div>
            )}
        </div>
    )
}

export const SkillFileTree: React.FC<SkillFileTreeProps> = ({
    fileTree,
    activeFilePath,
    onSelectFile,
    onDeleteFile,
    onRenameFile,
    onAddFile,
}) => {
    return (
        <div className="p-2 overflow-y-auto custom-scrollbar flex-1">
            {/* SKILL.md - Always displayed first and prominently */}
            {fileTree.skillMdFile && (
                <div
                    onClick={() => onSelectFile('SKILL.md')}
                    className={cn(
                        "flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer transition-colors mb-2",
                        activeFilePath === 'SKILL.md' 
                            ? "bg-emerald-50 text-emerald-700 font-medium border border-emerald-200" 
                            : "text-gray-700 hover:bg-gray-50 border border-transparent"
                    )}
                >
                    <FileText size={14} className="text-emerald-500" />
                    <span className="font-medium">SKILL.md</span>
                </div>
            )}
            
            {/* File Tree */}
            {fileTree.tree.length > 0 && (
                <div className="border-t border-gray-100 pt-2 mt-1">
                    {fileTree.tree.map(node => (
                        <FileTreeNodeComponent
                            key={node.path}
                            node={node}
                            activeFilePath={activeFilePath}
                            onSelectFile={onSelectFile}
                            onDeleteFile={onDeleteFile}
                            onRenameFile={onRenameFile}
                            onAddFile={onAddFile}
                        />
                    ))}
                </div>
            )}
            
            {/* Empty state */}
            {!fileTree.skillMdFile && fileTree.tree.length === 0 && (
                <div className="text-center py-4 text-gray-400 text-xs">
                    No files yet
                </div>
            )}
        </div>
    )
}
